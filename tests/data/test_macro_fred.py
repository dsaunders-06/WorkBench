from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

import pytest

from qat.config import Settings
from qat.data.macro_fred import (
    FredMacroSource,
    MacroFeed,
    MacroHistory,
    MacroObservation,
    MockMacroSource,
    load_macro_history,
)
from qat.domain.bus import EventBus
from qat.domain.events import MacroEvent
from qat.presentation import runtime


def test_fred_macro_source_parses_recorded_fixture_and_skips_missing_values():
    fixture = {
        "observations": [
            {"date": "2024-01-02", "value": "5.38"},
            {"date": "2024-01-03", "value": "."},  # FRED's missing-value marker
            {"date": "2024-01-04", "value": "5.40"},
        ]
    }

    observations = FredMacroSource._parse_observations("DGS3MO", fixture)

    assert len(observations) == 2
    assert observations[0].series == "DGS3MO"
    assert observations[0].value == pytest.approx(5.38)
    assert observations[0].ts == datetime(2024, 1, 2, tzinfo=UTC)


@pytest.mark.asyncio
async def test_mock_macro_source_is_deterministic_given_same_seed():
    obs_a = await MockMacroSource(seed=7).fetch_series("VIXCLS")
    obs_b = await MockMacroSource(seed=7).fetch_series("VIXCLS")

    assert obs_a[0].value == obs_b[0].value


@pytest.mark.asyncio
async def test_macro_feed_publishes_macro_event_per_observation():
    bus = EventBus()
    received: list[MacroEvent] = []

    async def handler(event: MacroEvent) -> None:
        received.append(event)

    bus.subscribe(MacroEvent, handler)
    feed = MacroFeed(bus, MockMacroSource(seed=1), ["DGS10", "VIXCLS"])

    await feed.poll_once()

    assert len(received) == 2
    assert {event.series for event in received} == {"DGS10", "VIXCLS"}


class _HistorySource:
    """Stands in for FredMacroSource, which returns a series' whole history -
    VIXCLS is over nine thousand daily observations back to 1990."""

    def __init__(self, count: int = 500) -> None:
        self.count = count
        self.calls: list[str] = []

    async def fetch_series(self, series_id: str) -> list[MacroObservation]:
        self.calls.append(series_id)
        start = datetime(2024, 1, 1, tzinfo=UTC)
        return [
            MacroObservation(series=series_id, ts=start + timedelta(days=i), value=float(i))
            for i in range(self.count)
        ]


@pytest.mark.asyncio
async def test_macro_feed_publishes_only_the_current_reading_of_a_long_history():
    bus = EventBus()
    received: list[MacroEvent] = []

    async def handler(event: MacroEvent) -> None:
        received.append(event)

    bus.subscribe(MacroEvent, handler)
    feed = MacroFeed(bus, _HistorySource(count=500), ["VIXCLS"])

    await feed.poll_once()

    # One event, not 500: replaying decades of history onto the bus every poll
    # would publish tens of thousands of events to say what five numbers are now.
    assert len(received) == 1
    assert received[0].value == pytest.approx(499.0)
    assert received[0].ts == datetime(2024, 1, 1, tzinfo=UTC) + timedelta(days=499)


@pytest.mark.asyncio
async def test_one_failing_series_does_not_stop_the_others():
    bus = EventBus()
    received: list[MacroEvent] = []

    async def handler(event: MacroEvent) -> None:
        received.append(event)

    class _PartlyBroken:
        async def fetch_series(self, series_id: str) -> list[MacroObservation]:
            if series_id == "VIXCLS":
                raise RuntimeError("FRED timed out")
            return [MacroObservation(series=series_id, ts=datetime.now(UTC), value=1.0)]

    bus.subscribe(MacroEvent, handler)
    feed = MacroFeed(bus, _PartlyBroken(), ["VIXCLS", "DGS10"])

    await feed.poll_once()

    assert [event.series for event in received] == ["DGS10"]


@pytest.mark.asyncio
async def test_poll_loop_survives_a_failing_poll():
    """A network source can fail; the mock never could. An unhandled exception
    in the loop would kill the task silently and freeze every macro feature at
    its last value for the rest of the session."""
    bus = EventBus()
    received: list[MacroEvent] = []

    async def handler(event: MacroEvent) -> None:
        received.append(event)

    bus.subscribe(MacroEvent, handler)

    class _FailsOnce:
        def __init__(self) -> None:
            self.calls = 0

        async def fetch_series(self, series_id: str) -> list[MacroObservation]:
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("FRED unreachable")
            return [MacroObservation(series=series_id, ts=datetime.now(UTC), value=17.5)]

    feed = MacroFeed(bus, _FailsOnce(), ["VIXCLS"], poll_interval_seconds=0.01)
    await feed.start()
    for _ in range(50):
        if received:
            break
        await asyncio.sleep(0.01)
    await feed.stop()

    assert received, "the poll loop died on the first failure instead of retrying"
    assert received[0].value == pytest.approx(17.5)


def _observations(series: str, points: list[tuple[str, float]]) -> list[MacroObservation]:
    return [
        MacroObservation(
            series=series,
            ts=datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=UTC),
            value=value,
        )
        for day, value in points
    ]


def test_macro_history_carries_the_last_reading_forward():
    """A series published on Friday is genuinely the market's best information
    all weekend. Interpolating would invent a number nobody could have seen."""
    history = MacroHistory(
        {"VIXCLS": _observations("VIXCLS", [("2026-07-24", 14.0), ("2026-07-27", 18.21)])}
    )

    assert history.as_of("VIXCLS", datetime(2026, 7, 24, tzinfo=UTC)) == pytest.approx(14.0)
    assert history.as_of("VIXCLS", datetime(2026, 7, 26, tzinfo=UTC)) == pytest.approx(14.0)
    assert history.as_of("VIXCLS", datetime(2026, 7, 27, tzinfo=UTC)) == pytest.approx(18.21)
    assert history.as_of("VIXCLS", datetime(2026, 12, 1, tzinfo=UTC)) == pytest.approx(18.21)


def test_macro_history_never_looks_ahead():
    """Pairing a bar from three months ago with today's VIX would be lookahead
    of the plainest kind, and the seeded matrix is what the HMM fits on."""
    history = MacroHistory({"VIXCLS": _observations("VIXCLS", [("2026-07-24", 14.0)])})

    assert history.as_of("VIXCLS", datetime(2026, 7, 23, tzinfo=UTC)) is None
    assert history.as_of("UNKNOWN", datetime(2026, 7, 24, tzinfo=UTC)) is None


@pytest.mark.asyncio
async def test_load_macro_history_seeds_with_what_it_can_fetch():
    class _PartlyBroken:
        async def fetch_series(self, series_id: str) -> list[MacroObservation]:
            if series_id == "BAA10Y":
                raise RuntimeError("FRED timed out")
            return _observations(series_id, [("2026-07-24", 1.0)])

    history = await load_macro_history(_PartlyBroken(), ["VIXCLS", "BAA10Y", "T10Y3M"])

    assert set(history.series) == {"VIXCLS", "T10Y3M"}


def test_resolve_macro_source_uses_fred_when_a_key_is_configured(monkeypatch, caplog):
    monkeypatch.setattr(runtime, "get_secret", lambda name: "a-key")

    with caplog.at_level(logging.INFO, logger="qat.presentation.runtime"):
        source = runtime.resolve_macro_source(Settings())

    assert isinstance(source, FredMacroSource)
    assert "FRED" in caplog.text


def test_resolve_macro_source_warns_loudly_when_falling_back_to_the_mock(monkeypatch, caplog):
    """The absence of this warning is the M27a root cause: MockMacroSource was
    wired in directly from M2 to M27, so three of the regime engine's six
    features were random numbers and nothing anywhere said so."""
    monkeypatch.setattr(runtime, "get_secret", lambda name: None)

    with caplog.at_level(logging.WARNING, logger="qat.presentation.runtime"):
        source = runtime.resolve_macro_source(Settings())

    assert isinstance(source, MockMacroSource)
    assert "RANDOM NUMBERS" in caplog.text
    assert "FRED_API_KEY" in caplog.text


@pytest.mark.asyncio
async def test_macro_history_retries_a_transient_failure_once():
    """Losing a series here costs a whole session: its feature sits at the
    default for every row, which is the constant column that makes the
    covariance matrix singular. Seen in a smoke test on VIXCLS."""

    class _FailsOnce:
        def __init__(self) -> None:
            self.calls = 0

        async def fetch_series(self, series_id: str) -> list[MacroObservation]:
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("FRED rate limit")
            return _observations(series_id, [("2026-07-24", 18.21)])

    source = _FailsOnce()
    history = await load_macro_history(source, ["VIXCLS"])

    assert source.calls == 2
    assert history.as_of("VIXCLS", datetime(2026, 7, 25, tzinfo=UTC)) == pytest.approx(18.21)


@pytest.mark.asyncio
async def test_a_series_that_keeps_failing_is_reported_and_omitted(caplog):
    class _AlwaysFails:
        async def fetch_series(self, series_id: str) -> list[MacroObservation]:
            raise RuntimeError("FRED unreachable")

    with caplog.at_level(logging.ERROR, logger="qat.data.macro_fred"):
        history = await load_macro_history(_AlwaysFails(), ["VIXCLS"])

    assert history.series == ()
    assert "constant for this session" in caplog.text

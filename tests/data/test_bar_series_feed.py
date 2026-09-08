"""A Yahoo ticker reaching a regime-engine column, and every reason it should not.

`RegimeFeatureBuilder.vix_series` became configurable on 8 September and could
not be pointed at anything: the column fills from `MacroEvent`, which only FRED
published. The test that made it configurable said so - *"NAMING IT IS NOT
FEEDING IT... pointing this at it would leave the column at its default forever
- silently."*

⚠️ The interesting tests here are the refusals. This feeds the engine that sizes
the book, where `vix_level` led the raw feature spread at 85.1% in the 8
September live fit. What must never happen is a fabricated or stale number
entering that column wearing a real ticker's name.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from qat.data.bar_series_feed import BarSeriesFeed
from qat.domain.bus import EventBus
from qat.domain.events import MacroEvent


def _frame(closes: list[float], *, last_ts: datetime | None = None) -> pd.DataFrame:
    last_ts = last_ts or datetime.now(UTC)
    return pd.DataFrame(
        {
            "ts": [last_ts - timedelta(days=len(closes) - 1 - i) for i in range(len(closes))],
            "close": closes,
        }
    )


class _Source:
    def __init__(self, frames: dict[str, pd.DataFrame], synthetic: bool = False) -> None:
        self.frames = frames
        self.last_was_synthetic = synthetic
        self.asked: list[str] = []

    async def get_bars(self, symbol: str, period: str = "3mo", interval: str = "1d"):
        self.asked.append(symbol)
        frame = self.frames.get(symbol)
        if frame is None:
            raise RuntimeError(f"no such ticker: {symbol}")
        return frame


async def _published(feed: BarSeriesFeed, bus: EventBus) -> list[MacroEvent]:
    seen: list[MacroEvent] = []

    async def capture(event: MacroEvent) -> None:
        seen.append(event)

    bus.subscribe(MacroEvent, capture)
    await feed.poll_once()
    return seen


@pytest.mark.asyncio
async def test_the_latest_close_is_published_under_the_ticker() -> None:
    """⚠️ Under the TICKER, not a translated name. A consumer selecting on
    `vix_series="^AXVI"` has to match without a mapping table in between, or
    the bridge just moves the silent gap one step along."""
    bus = EventBus()
    source = _Source({"^AXVI": _frame([12.4, 11.9, 11.97])})
    feed = BarSeriesFeed(bus, source, ["^AXVI"])

    events = await _published(feed, bus)

    assert len(events) == 1
    assert events[0].series == "^AXVI"
    assert events[0].value == pytest.approx(11.97)


@pytest.mark.asyncio
async def test_an_empty_frame_publishes_nothing_and_warns(caplog) -> None:
    """⚠️ NOT HYPOTHETICAL. Measured 8 September 2026: `^AJOVIX` returns a 404
    and `AU3M=F` returns zero rows. A ticker that does not exist looks exactly
    like this, and inventing a value for it is how a wrong number gets into the
    engine that sizes the book."""
    bus = EventBus()
    feed = BarSeriesFeed(bus, _Source({"AU3M=F": pd.DataFrame()}), ["AU3M=F"])

    with caplog.at_level(logging.WARNING):
        events = await _published(feed, bus)

    assert events == []
    assert "no usable bars" in caplog.text


@pytest.mark.asyncio
async def test_a_stale_bar_is_refused_rather_than_republished(caplog) -> None:
    """⚠️ THE TEST THIS FILE EXISTS FOR. Publishing the last available close
    freezes the column at a reading the market has left behind - and a frozen
    column is invisible, because the engine fits happily on a flat feature."""
    bus = EventBus()
    stale = _frame([11.5, 11.9], last_ts=datetime.now(UTC) - timedelta(days=30))
    feed = BarSeriesFeed(bus, _Source({"^AXVI": stale}), ["^AXVI"])

    with caplog.at_level(logging.WARNING):
        events = await _published(feed, bus)

    assert events == []
    assert "30 days ago" in caplog.text


@pytest.mark.asyncio
async def test_a_long_weekend_is_not_treated_as_a_stalled_series() -> None:
    """Smoothing must not become deafness: four days covers Easter."""
    bus = EventBus()
    frame = _frame([11.5, 11.9], last_ts=datetime.now(UTC) - timedelta(days=4))
    feed = BarSeriesFeed(bus, _Source({"^AXVI": frame}), ["^AXVI"])

    assert len(await _published(feed, bus)) == 1


@pytest.mark.asyncio
async def test_synthetic_bars_never_reach_the_engine(caplog) -> None:
    """⚠️ `RealHistorySource` falls back to SYNTHETIC bars on a failed fetch -
    deliberately, so one screen degrades rather than going blank. That fallback
    reaching the regime engine would put a random walk into the column that
    sizes the book, wearing a real ticker's name."""
    bus = EventBus()
    source = _Source({"^AXVI": _frame([11.9, 11.97])}, synthetic=True)
    feed = BarSeriesFeed(bus, source, ["^AXVI"])

    with caplog.at_level(logging.WARNING):
        events = await _published(feed, bus)

    assert events == []
    assert "SYNTHETIC" in caplog.text


@pytest.mark.asyncio
async def test_a_non_finite_close_is_refused() -> None:
    bus = EventBus()
    feed = BarSeriesFeed(bus, _Source({"^AXVI": _frame([11.9, float("nan")])}), ["^AXVI"])

    assert await _published(feed, bus) == []


@pytest.mark.asyncio
async def test_one_failing_ticker_does_not_mute_the_others() -> None:
    """The rule `MacroFeed` already records: one bad series must not silence
    the rest of the poll."""
    bus = EventBus()
    source = _Source({"^AXVI": _frame([11.9, 11.97])})
    feed = BarSeriesFeed(bus, source, ["^AJOVIX", "^AXVI"])

    events = await _published(feed, bus)

    assert [event.series for event in events] == ["^AXVI"]
    assert source.asked == ["^AJOVIX", "^AXVI"]


@pytest.mark.asyncio
async def test_the_bar_date_travels_with_the_value() -> None:
    """The event's `ts` is the BAR's, not now. A consumer that wants to judge
    freshness for itself needs the reading's own date."""
    bus = EventBus()
    when = datetime.now(UTC) - timedelta(days=1)
    feed = BarSeriesFeed(bus, _Source({"^AXVI": _frame([11.9, 11.97], last_ts=when)}), ["^AXVI"])

    events = await _published(feed, bus)

    assert events[0].ts.date() == when.date()


@pytest.mark.asyncio
async def test_nothing_is_polled_when_nothing_is_configured() -> None:
    """The default. Naming a ticker is an operator decision, and an unasked
    feed must not reach the network on its own."""
    bus = EventBus()
    source = _Source({})
    feed = BarSeriesFeed(bus, source, [])

    assert await _published(feed, bus) == []
    assert source.asked == []


# --- the resolver and the path it completes -------------------------------


def test_no_bridge_is_built_when_nothing_is_named() -> None:
    from qat.config import Settings
    from qat.data.bar_series_feed import resolve_bar_series_feed

    assert resolve_bar_series_feed(Settings(_env_file=None), EventBus()) is None


def test_a_synthetic_market_data_setting_refuses_to_bridge(caplog) -> None:
    """⚠️ There is no real ticker behind a synthetic feed, and a generated
    series entering the regime engine as `^AXVI` is exactly what the synthetic
    guard exists to stop. Refuse and say why, rather than bridge anyway."""
    from qat.config import Settings
    from qat.data.bar_series_feed import resolve_bar_series_feed

    settings = Settings(_env_file=None, bar_macro_series=("^AXVI",), market_data_source="synthetic")

    with caplog.at_level(logging.WARNING):
        assert resolve_bar_series_feed(settings, EventBus()) is None

    assert "not started" in caplog.text.lower()


@pytest.mark.asyncio
async def test_the_bridged_series_actually_reaches_the_regime_column() -> None:
    """⚠️ THE POINT OF THE WHOLE ITEM. Every piece of this existed separately -
    a configurable `vix_series`, a bus, a feature builder - and the path
    between them did not, so pointing the setting at `^AXVI` would have left
    the column at ZERO for a whole session while the engine fitted happily on
    a flat feature."""
    from qat.domain.regime_engine.feature_matrix import RegimeFeatureBuilder

    bus = EventBus()
    builder = RegimeFeatureBuilder(vix_series="^AXVI")

    async def fill(event: MacroEvent) -> None:
        builder.update_macro(event.series, event.value)

    bus.subscribe(MacroEvent, fill)
    feed = BarSeriesFeed(bus, _Source({"^AXVI": _frame([12.4, 11.97])}), ["^AXVI"])

    await feed.poll_once()

    assert builder._vix == pytest.approx(11.97)


@pytest.mark.asyncio
async def test_a_refused_bar_leaves_the_column_at_its_previous_value() -> None:
    """The refusals are only safe if they are also silent about the column -
    a refusal must not write a zero over a good reading."""
    from qat.domain.regime_engine.feature_matrix import RegimeFeatureBuilder

    bus = EventBus()
    builder = RegimeFeatureBuilder(vix_series="^AXVI")
    builder.update_macro("^AXVI", 11.97)

    async def fill(event: MacroEvent) -> None:
        builder.update_macro(event.series, event.value)

    bus.subscribe(MacroEvent, fill)
    stale = _frame([31.0], last_ts=datetime.now(UTC) - timedelta(days=40))
    await BarSeriesFeed(bus, _Source({"^AXVI": stale}), ["^AXVI"]).poll_once()

    assert builder._vix == pytest.approx(11.97)


def test_the_engine_passes_the_configured_series_to_its_builder() -> None:
    """⚠️ The last link. A `RegimeEngine` that built its feature matrix with
    the default would leave the setting inert - configurable in `Settings`,
    configurable on the builder, and connected to neither."""
    from qat.domain.regime_engine.engine import RegimeEngine

    engine = RegimeEngine(EventBus(), benchmark_symbol="^AXJO", vix_series="^AXVI")

    assert engine._feature_builder.vix_series == "^AXVI"


def test_the_runtime_hands_the_setting_through() -> None:
    from qat.config import Settings
    from qat.presentation.runtime import Runtime

    runtime = Runtime.build_demo(settings=Settings(_env_file=None, regime_vix_series="^AXVI"))

    assert runtime.regime_engine._feature_builder.vix_series == "^AXVI"

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from qat.data.macro_fred import FredMacroSource, MacroFeed, MockMacroSource
from qat.domain.bus import EventBus
from qat.domain.events import MacroEvent


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

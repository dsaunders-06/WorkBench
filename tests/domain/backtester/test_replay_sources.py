"""The warm-start ports, bounded at the replay boundary (W2 step 4).

Both exist to feed the PRODUCTION WarmStart from bars already in memory. The
property that matters is the same one SimulatedBroker.get_historical carries:
a simulator holds the whole series and must refuse to answer past the boundary.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
import pytest

from qat.data.macro_fred import MacroObservation
from qat.domain.backtester.replay_sources import ReplayHistorySource, ReplayMacroSource


def _bars(days: int = 100) -> pd.DataFrame:
    index = pd.date_range("2026-01-05", periods=days, freq="B", tz="UTC")
    closes = [100.0 + i for i in range(days)]
    return pd.DataFrame(
        {
            "open": closes,
            "high": [c + 1 for c in closes],
            "low": [c - 1 for c in closes],
            "close": closes,
            "volume": [1_000.0] * days,
        },
        index=index,
    )


@pytest.mark.asyncio
async def test_history_stops_at_the_replay_boundary():
    source = ReplayHistorySource({"AAA": _bars()}, until_index=60)

    frame = await source.get_daily_bars("AAA", n_bars=500)

    assert len(frame) == 60, "the warm prefix only - never a bar the replay has not reached"
    assert list(frame.columns) == ["ts", "open", "high", "low", "close", "volume"]


@pytest.mark.asyncio
async def test_history_respects_the_requested_count():
    source = ReplayHistorySource({"AAA": _bars()}, until_index=60)
    frame = await source.get_daily_bars("AAA", n_bars=10)
    assert len(frame) == 10
    assert frame["close"].iloc[-1] == pytest.approx(159.0), "the newest of the prefix"


@pytest.mark.asyncio
async def test_an_unknown_symbol_answers_empty():
    source = ReplayHistorySource({"AAA": _bars()}, until_index=60)
    assert (await source.get_daily_bars("ZZZ")).empty


@pytest.mark.asyncio
async def test_macro_stops_at_the_replay_boundary():
    boundary = datetime(2026, 3, 1, tzinfo=UTC)
    observations = {
        "VIXCLS": [
            MacroObservation(series="VIXCLS", ts=datetime(2026, 2, 1, tzinfo=UTC), value=14.0),
            MacroObservation(series="VIXCLS", ts=datetime(2026, 4, 1, tzinfo=UTC), value=30.0),
        ]
    }
    source = ReplayMacroSource(observations, until=boundary)

    got = await source.fetch_series("VIXCLS")

    assert [o.value for o in got] == [14.0], "the April reading had not happened yet"


@pytest.mark.asyncio
async def test_an_unknown_series_answers_empty():
    source = ReplayMacroSource({}, until=datetime(2026, 3, 1, tzinfo=UTC))
    assert await source.fetch_series("NOPE") == []

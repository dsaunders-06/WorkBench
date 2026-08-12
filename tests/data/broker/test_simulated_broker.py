"""SimulatedBroker in isolation - no OMS, no session loop (W2 step 1).

The guard that matters most here is the one with no equivalent in any real
adapter: a simulator can see the future, and must refuse to.
"""

from __future__ import annotations

import pandas as pd
import pytest

from qat.data.broker.simulated_broker import SimulatedBroker
from qat.domain.backtester.costs import CostModel


def _bars(closes: list[float], symbol_high: float = 1.0) -> pd.DataFrame:
    """Daily bars with a controllable body. High/low straddle the close."""
    index = pd.date_range("2026-01-05", periods=len(closes), freq="B")
    return pd.DataFrame(
        {
            "open": closes,
            "high": [c + symbol_high for c in closes],
            "low": [c - symbol_high for c in closes],
            "close": closes,
        },
        index=index,
    )


def _broker(**kwargs) -> SimulatedBroker:
    bars = {"AAA": _bars([100.0, 101.0, 102.0, 103.0, 104.0])}
    return SimulatedBroker(
        bars=bars, cost_model=CostModel(commission_bps=0.0, slippage_bps=0.0), **kwargs
    )


def test_the_session_starts_on_the_first_bar():
    broker = _broker()
    assert broker.current_date == pd.Timestamp("2026-01-05")


def test_advance_moves_one_trading_day_and_reports_the_end():
    broker = _broker()
    moved = [broker.advance() for _ in range(6)]
    assert moved[:4] == [True, True, True, True]
    assert moved[4] is False, "there are five bars, so the fifth advance runs out"


@pytest.mark.asyncio
async def test_market_data_is_the_current_bar_not_the_last_one():
    broker = _broker()
    broker.advance()
    quote = await broker.get_market_data("AAA")
    assert quote["last"] == pytest.approx(101.0)


@pytest.mark.asyncio
async def test_get_historical_cannot_see_the_future():
    """The guard with no equivalent in a real adapter. A simulator holds the
    whole series in memory, so nothing but this stops the strategy being handed
    bars that had not happened yet - which would manufacture an edge from
    nothing and look entirely plausible doing it."""
    broker = _broker()
    broker.advance()  # now on bar index 1, close 101.0

    history = await broker.get_historical("AAA", 10)

    assert [row["close"] for row in history] == [100.0, 101.0]
    assert len(history) == 2, "only the bars that have happened"


@pytest.mark.asyncio
async def test_get_historical_returns_at_most_the_bars_asked_for():
    broker = _broker()
    for _ in range(4):
        broker.advance()
    history = await broker.get_historical("AAA", 2)
    assert [row["close"] for row in history] == [103.0, 104.0]


@pytest.mark.asyncio
async def test_an_unknown_symbol_answers_empty_rather_than_raising():
    """A universe member with no bars in the window must not end the run."""
    broker = _broker()
    assert await broker.get_historical("ZZZ", 5) == []

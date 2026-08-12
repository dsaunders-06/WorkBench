"""SimulatedBroker in isolation - no OMS, no session loop (W2 step 1).

The guard that matters most here is the one with no equivalent in any real
adapter: a simulator can see the future, and must refuse to.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
import pytest

from qat.data.broker.adapter import Order
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


def _buy(symbol: str = "AAA", quantity: float = 10.0, **kwargs) -> Order:
    return Order(symbol=symbol, side="buy", quantity=quantity, order_id="o-1", **kwargs)


@pytest.mark.asyncio
async def test_a_market_entry_does_not_fill_on_the_bar_that_signalled_it():
    """Filling on the signal bar's close is look-ahead in its most ordinary
    form: the signal was computed FROM that close."""
    broker = _broker()

    placed = await broker.place_order(_buy())

    assert placed.status == "transmitted"
    assert placed.filled_price is None
    assert await broker.positions() == []


@pytest.mark.asyncio
async def test_a_market_entry_fills_at_the_next_bars_open():
    broker = _broker()
    await broker.place_order(_buy())

    broker.advance()

    positions = await broker.positions()
    assert [p.symbol for p in positions] == ["AAA"]
    assert positions[0].quantity == pytest.approx(10.0)
    assert positions[0].avg_price == pytest.approx(101.0), "bar index 1's open"


@pytest.mark.asyncio
async def test_slippage_moves_a_buy_fill_against_the_buyer():
    bars = {"AAA": _bars([100.0, 101.0, 102.0])}
    broker = SimulatedBroker(bars=bars, cost_model=CostModel(commission_bps=0.0, slippage_bps=10.0))
    await broker.place_order(_buy())

    broker.advance()

    positions = await broker.positions()
    # 101.0 * (1 + 10bps) = 101.101
    assert positions[0].avg_price == pytest.approx(101.101)


@pytest.mark.asyncio
async def test_a_bracket_entry_leaves_its_protective_legs_resting_once_filled():
    broker = _broker()
    await broker.place_order(_buy(stop_price=95.0, take_profit_price=115.0))

    assert await broker.resting_stops() == {}, "nothing rests before the shares exist"

    broker.advance()

    assert await broker.resting_stops() == {"AAA": 95.0}


def _ohlc(rows: list[tuple[float, float, float, float]]) -> pd.DataFrame:
    """Explicit open/high/low/close per bar, for the ambiguous cases."""
    index = pd.date_range("2026-01-05", periods=len(rows), freq="B")
    return pd.DataFrame(
        {
            "open": [r[0] for r in rows],
            "high": [r[1] for r in rows],
            "low": [r[2] for r in rows],
            "close": [r[3] for r in rows],
        },
        index=index,
    )


async def _entered(bars: pd.DataFrame, stop: float, target: float) -> SimulatedBroker:
    broker = SimulatedBroker(
        bars={"AAA": bars}, cost_model=CostModel(commission_bps=0.0, slippage_bps=0.0)
    )
    await broker.place_order(_buy(stop_price=stop, take_profit_price=target))
    broker.advance()  # fills at bar 1's open, legs go resting
    return broker


@pytest.mark.asyncio
async def test_a_stop_fills_when_the_low_touches_it():
    bars = _ohlc([(100, 101, 99, 100), (100, 101, 99, 100), (100, 101, 94, 95)])
    broker = await _entered(bars, stop=95.0, target=115.0)

    broker.advance()

    assert await broker.positions() == []
    fills = await broker.recent_fills(since=datetime(2020, 1, 1, tzinfo=UTC))
    assert [(f.symbol, f.side, f.price) for f in fills] == [("AAA", "sell", 95.0)]


@pytest.mark.asyncio
async def test_a_bar_that_touches_both_levels_is_recorded_as_the_STOP():
    """The decision that makes every expectancy figure a floor. The bar cannot
    say which came first, so the unfavourable one is assumed."""
    bars = _ohlc([(100, 101, 99, 100), (100, 101, 99, 100), (100, 120, 94, 100)])
    broker = await _entered(bars, stop=95.0, target=115.0)

    broker.advance()

    fills = await broker.recent_fills(since=datetime(2020, 1, 1, tzinfo=UTC))
    assert [f.price for f in fills] == [95.0], "the target was touched too, and loses"


@pytest.mark.asyncio
async def test_a_gap_through_the_stop_fills_at_the_OPEN_not_the_stop():
    """The MNST lesson in the simulator. A bar opening below the stop does not
    fill politely at the trigger."""
    bars = _ohlc([(100, 101, 99, 100), (100, 101, 99, 100), (80, 82, 78, 80)])
    broker = await _entered(bars, stop=95.0, target=115.0)

    broker.advance()

    fills = await broker.recent_fills(since=datetime(2020, 1, 1, tzinfo=UTC))
    assert [f.price for f in fills] == [80.0], "the open, which is worse than the stop"


@pytest.mark.asyncio
async def test_a_gap_through_the_target_fills_at_the_TARGET_not_the_better_open():
    """The same rule pointed the other way: never flatter."""
    bars = _ohlc([(100, 101, 99, 100), (100, 101, 99, 100), (130, 132, 128, 130)])
    broker = await _entered(bars, stop=95.0, target=115.0)

    broker.advance()

    fills = await broker.recent_fills(since=datetime(2020, 1, 1, tzinfo=UTC))
    assert [f.price for f in fills] == [115.0], "the target, not the 130 open"


@pytest.mark.asyncio
async def test_a_stop_can_fire_on_the_bar_the_entry_filled():
    """The entry filled at the open, so the rest of that bar follows it. A stop
    that could not fire on entry day would be optimistic about gap days."""
    bars = _ohlc([(100, 101, 99, 100), (100, 101, 90, 92)])
    broker = SimulatedBroker(
        bars={"AAA": bars}, cost_model=CostModel(commission_bps=0.0, slippage_bps=0.0)
    )
    await broker.place_order(_buy(stop_price=95.0, take_profit_price=115.0))

    broker.advance()

    assert await broker.positions() == []
    fills = await broker.recent_fills(since=datetime(2020, 1, 1, tzinfo=UTC))
    assert [f.price for f in fills] == [95.0]

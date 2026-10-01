"""An order still filling is not a divergence (Defect B).

⚠️ MEASURED LIVE, 31 August 2026. The reconciliation poll landed NINE SECONDS
into a forty-five-second fill:

    10:30:06-10:30:51  JHX.AX buy, 17 executions, cumQty 1,097
    10:30:15           Broker reconciliation mismatch: JHX.AX tracked=1097 broker=378
    10:30:15           KILL-SWITCH TRIPPED

`oms.py:861` books `filled.quantity` - the ORDER'S SIZE, not what executed - so
the app counts the whole order the instant the broker accepts it.

The number that explains the gap was already in hand, in the same scan cycle and
the same second:

    10:30:15  RESTING ORDER ORPHAN: JHX.AX BUY resting=719 justified=0 excess=719

1097 - 378 - 719 == 0.
"""

from __future__ import annotations

import pandas as pd
import pytest

from qat.config import Settings
from qat.data.broker.adapter import Position
from qat.data.broker.mock_broker import MockBroker
from qat.domain.bus import EventBus
from qat.domain.oms.oms import OMS
from qat.domain.oms.resting_orders import RestingOrder
from qat.domain.risk_engine.engine import OrderCandidate, RiskEngine
from qat.domain.risk_engine.kill_switch import KillSwitch


def _resting(symbol: str, side: str, remaining: float, order_type: str = "market") -> RestingOrder:
    """`quantity` IS the unfilled remainder - `from_ib_open_order` builds it from
    `trade.orderStatus.remaining`."""
    return RestingOrder(
        symbol=symbol,
        side=side,
        quantity=remaining,
        total_quantity=remaining,
        order_id=f"{symbol}-{side}-{order_type}",
        order_type=order_type,
        status="Submitted",
        limit_price=None,
        stop_price=None,
        oca_group=None,
        parent_perm_id=None,
        owner_client_id=1,
        why_held=None,
    )


class _Broker(MockBroker):
    """A broker whose positions and open orders are set by the test."""

    def __init__(self, positions=None, open_orders=None, raises: bool = False) -> None:
        super().__init__(seed=1)
        for symbol, qty in (positions or {}).items():
            self._positions[symbol] = Position(symbol=symbol, quantity=qty, avg_price=10.0)
        self._open = list(open_orders or [])
        self._raises = raises

    async def open_orders(self) -> list[RestingOrder]:
        if self._raises:
            raise RuntimeError("broker refused open_orders")
        return self._open


def _oms(broker: _Broker) -> tuple[OMS, KillSwitch]:
    bus = EventBus()
    switch = KillSwitch()
    settings = Settings(_env_file=None)
    engine = RiskEngine(bus, switch, settings=settings)
    return OMS(broker, engine, switch, max_order_pct_of_cash=1.0, bus=bus), switch


@pytest.mark.asyncio
async def test_a_working_buy_reports_its_remainder() -> None:
    oms, _ = _oms(_Broker(open_orders=[_resting("JHX.AX", "buy", 719.0)]))

    assert await oms._in_flight_buy_remainders() == {"JHX.AX": 719.0}


@pytest.mark.asyncio
async def test_resting_protective_sells_report_NOTHING() -> None:
    """⚠️ PLANTED, and this is the trap the whole design exists to avoid.

    The twenty resting protective legs are WORKING SELL orders whose remaining
    is the full position - BOQ's is 13,586. But a protective stop RETURNS EARLY
    at sign-off and never touches `_filled_quantities`: the `return filled` sits
    two lines above `signed_qty`. Subtracting these would invent a 13,586-share
    tolerance on a symbol with no divergence at all.
    """
    oms, _ = _oms(
        _Broker(
            open_orders=[
                _resting("BOQ.AX", "sell", 13586.0, order_type="stop"),
                _resting("BOQ.AX", "sell", 13586.0, order_type="limit"),
            ]
        )
    )

    assert await oms._in_flight_buy_remainders() == {}


@pytest.mark.asyncio
async def test_buys_and_sells_together_report_only_the_buys() -> None:
    oms, _ = _oms(
        _Broker(
            open_orders=[
                _resting("JHX.AX", "buy", 719.0),
                _resting("JHX.AX", "sell", 1097.0, order_type="stop"),
            ]
        )
    )

    assert await oms._in_flight_buy_remainders() == {"JHX.AX": 719.0}


@pytest.mark.asyncio
async def test_a_broker_that_raises_reports_nothing_rather_than_guessing() -> None:
    """No evidence means NO TOLERANCE, which trips. A rail that loses its
    evidence must get stricter, never laxer."""
    oms, _ = _oms(_Broker(raises=True))

    assert await oms._in_flight_buy_remainders() == {}


@pytest.mark.asyncio
async def test_an_adapter_without_open_orders_reports_nothing() -> None:
    class _NoOpenOrders(MockBroker):
        open_orders = None  # type: ignore[assignment]

    bus = EventBus()
    switch = KillSwitch()
    settings = Settings(_env_file=None)
    oms = OMS(
        _NoOpenOrders(seed=1),
        RiskEngine(bus, switch, settings=settings),
        switch,
        max_order_pct_of_cash=1.0,
        bus=bus,
    )

    assert await oms._in_flight_buy_remainders() == {}


def _flat_returns(n: int = 30) -> pd.Series:
    dates = pd.date_range("2024-01-01", periods=n)
    return pd.Series([0.001] * n, index=dates)


def _candidate(symbol: str = "JHX.AX") -> OrderCandidate:
    return OrderCandidate(
        symbol=symbol,
        side="buy",
        price=100.0,
        atr=2.0,
        win_rate=0.6,
        win_loss_ratio=2.0,
        candidate_returns=_flat_returns(),
    )


@pytest.mark.asyncio
async def test_a_partial_fill_is_not_a_mismatch() -> None:
    """⚠️ THE LIVE CASE, with its real numbers. 1097 - 378 - 719 == 0."""
    broker = _Broker(
        positions={"JHX.AX": 378.0},
        open_orders=[_resting("JHX.AX", "buy", 719.0)],
    )
    oms, switch = _oms(broker)
    oms._filled_quantities["JHX.AX"] = 378.0

    assert await oms.check_reconciliation() is False
    assert switch.tripped is False


@pytest.mark.asyncio
async def test_the_same_gap_with_nothing_in_flight_still_trips() -> None:
    """⚠️ THE RAIL'S TEETH. Identical numbers, no working order - this MUST
    halt. Without this, the tolerance could be blinding rather than explaining."""
    broker = _Broker(positions={"JHX.AX": 378.0}, open_orders=[])
    oms, switch = _oms(broker)
    oms._filled_quantities["JHX.AX"] = 1097.0

    assert await oms.check_reconciliation() is True
    assert switch.tripped is True


@pytest.mark.asyncio
async def test_a_gap_LARGER_than_the_remainder_still_trips() -> None:
    """⚠️ PLANTED. tracked 1097, broker 300, remaining 719 - the gap is 797 and
    the tolerance is 719, so 78 shares are unexplained and it must halt.

    Without this, an implementation that simply SKIPPED any symbol with a
    working order would pass both tests above.
    """
    broker = _Broker(
        positions={"JHX.AX": 300.0},
        open_orders=[_resting("JHX.AX", "buy", 719.0)],
    )
    oms, switch = _oms(broker)
    oms._filled_quantities["JHX.AX"] = 1097.0

    assert await oms.check_reconciliation() is True
    assert switch.tripped is True


@pytest.mark.asyncio
async def test_a_clean_book_with_resting_protective_sells_stays_clean() -> None:
    """⚠️ PLANTED, the trap again but at the RAIL. tracked == broker, and the
    symbol carries full-size resting sell legs. An implementation that
    subtracted sell remainders turns this green book RED - inventing a
    13,586-share divergence on a position that agrees perfectly."""
    broker = _Broker(
        positions={"BOQ.AX": 13586.0},
        open_orders=[
            _resting("BOQ.AX", "sell", 13586.0, order_type="stop"),
            _resting("BOQ.AX", "sell", 13586.0, order_type="limit"),
        ],
    )
    oms, switch = _oms(broker)
    oms._filled_quantities["BOQ.AX"] = 13586.0

    assert await oms.check_reconciliation() is False
    assert switch.tripped is False

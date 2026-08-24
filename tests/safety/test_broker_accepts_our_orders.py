"""Orders this system builds must be ones the real broker will accept (M31a).

The end-to-end test proved the path from tick to fill, but against MockBroker,
which accepts anything. Alpaca does not:

    {"code":42210000,"message":"fractional orders must be simple orders"}

The sizer works in continuous shares - 1% of equity over a stop distance
almost never lands on an integer - and every buy leaves with a protective
bracket. On 31 July that combination meant every auto-signed order was refused
by the broker and the account could not trade at all, while the blotter showed
three orders as `transmitted` that Alpaca had never accepted.

This stub enforces the two constraints that actually bit, so a regression
fails here rather than in a live session.
"""

from __future__ import annotations

import logging

import pandas as pd
import pytest

from qat.config import Settings
from qat.data.broker.adapter import AccountSummary, Order, Position
from qat.domain.bus import EventBus
from qat.domain.oms.oms import OMS
from qat.domain.risk_engine.engine import OrderCandidate, RiskEngine
from qat.domain.risk_engine.kill_switch import KillSwitch


class _AlpacaLikeBroker:
    """Refuses what Alpaca refuses, and nothing else."""

    def __init__(self) -> None:
        self.placed: list[Order] = []

    async def account(self) -> AccountSummary:
        return AccountSummary(net_liquidation=100_000.0, cash=100_000.0, buying_power=100_000.0)

    async def positions(self) -> list[Position]:
        return []

    async def place_order(self, order: Order) -> Order:
        has_bracket = bool(order.stop_price or order.take_profit_price)
        is_fractional = order.quantity != int(order.quantity)
        if is_fractional and has_bracket:
            raise RuntimeError(
                '{"code":42210000,"message":"fractional orders must be simple orders"}'
            )
        self.placed.append(order)
        order.status = "filled"
        order.filled_price = order.reference_price
        return order

    async def get_market_data(self, symbol: str) -> dict[str, float]:
        return {"last": 100.0, "bid": 99.99, "ask": 100.01}


def _candidate(price: float = 100.0) -> OrderCandidate:
    dates = pd.date_range("2024-01-01", periods=30)
    return OrderCandidate(
        symbol="AAPL",
        side="buy",
        price=price,
        atr=2.0,
        win_rate=0.6,
        win_loss_ratio=2.0,
        candidate_returns=pd.Series([0.001] * 30, index=dates),
        strategy="swing",
        stop_price=price * 0.95,
    )


def _oms(broker: _AlpacaLikeBroker) -> OMS:
    settings = Settings(_env_file=None, max_single_name_concentration_pct=1.0)
    switch = KillSwitch()
    engine = RiskEngine(EventBus(), switch, settings=settings)
    return OMS(broker, engine, switch, max_order_pct_of_cash=1.0)


@pytest.mark.asyncio
async def test_a_sized_order_is_acceptable_to_the_real_broker():
    """The regression that cost a live session: a bracket order must carry a
    whole-share quantity."""
    broker = _AlpacaLikeBroker()
    oms = _oms(broker)

    order = await oms.submit_order(_candidate(), 100_000.0, {}, {})
    assert order.status == "pending_signoff"
    assert order.quantity == int(order.quantity), "a bracket order must be whole shares"

    signed = await oms.sign_off(order.order_id, operator="test")

    assert signed.status == "filled"
    assert broker.placed, "the broker refused an order this system built"


@pytest.mark.asyncio
async def test_a_position_too_small_for_one_share_is_refused_not_rounded_up():
    """Rounding up would take more risk than the sizer approved, and the whole
    sizing chain treats its output as a ceiling."""
    broker = _AlpacaLikeBroker()
    oms = _oms(broker)

    # A price far above what 1% of equity over the stop distance can buy.
    order = await oms.submit_order(_candidate(price=2_000_000.0), 100_000.0, {}, {})

    assert order.status == "rejected"
    assert order.quantity == 0
    assert not broker.placed


@pytest.mark.asyncio
async def test_a_broker_refusal_never_leaves_an_order_looking_live():
    """The blotter showed three orders as `transmitted` while Alpaca held
    nothing. Reconciliation cannot catch that - it compares FILLED quantities,
    and an order that never reached the broker has filled nothing on either
    side, so both agree."""

    class _AlwaysRefuses(_AlpacaLikeBroker):
        async def place_order(self, order: Order) -> Order:
            raise RuntimeError("broker said no")

    broker = _AlwaysRefuses()
    oms = _oms(broker)
    order = await oms.submit_order(_candidate(), 100_000.0, {}, {})

    signed = await oms.sign_off(order.order_id, operator="test")

    assert signed.status == "rejected", "a refused order must not read as transmitted"
    stored = next(o for o in oms.orders() if o.order_id == order.order_id)
    assert stored.status == "rejected"


# --- Stops are verified, not assumed (M31b/2) ------------------------------


class _BrokerWithStops(_AlpacaLikeBroker):
    def __init__(self, held: dict[str, float], resting: dict[str, float]) -> None:
        super().__init__()
        self._held = held
        self._resting = resting

    async def positions(self) -> list[Position]:
        return [Position(symbol=s, quantity=q, avg_price=100.0) for s, q in self._held.items()]

    async def resting_stops(self) -> dict[str, float]:
        return dict(self._resting)


@pytest.mark.asyncio
async def test_a_stop_that_is_no_longer_resting_is_dropped_from_the_record(caplog):
    """On 31 July six positions lost their stops when the bracket legs expired
    at the close, and nothing noticed: reconciliation compares FILLED
    QUANTITIES, which an expired protective leg does not change. The governor
    kept sizing new positions as though the book were protected."""
    broker = _BrokerWithStops(held={"CSCO": 44.0, "UNP": 17.0}, resting={"CSCO": 110.0})
    oms = _oms(broker)
    oms._position_stops = {"CSCO": 110.0, "UNP": 280.0}

    with caplog.at_level(logging.ERROR, logger="qat.domain.oms.oms"):
        lost = await oms.verify_position_stops()

    assert lost == ["UNP"]
    assert "UNP" not in oms.position_stops(), "an unprotected position must not look protected"
    assert oms.position_stops()["CSCO"] == 110.0
    assert "POSITION UNPROTECTED" in caplog.text


@pytest.mark.asyncio
async def test_a_broker_that_cannot_answer_changes_nothing():
    """An adapter without the capability must not read as "no stops rest
    anywhere", which would drop every stop the app holds."""
    broker = _AlpacaLikeBroker()  # no resting_stops attribute
    oms = _oms(broker)
    oms._position_stops = {"CSCO": 110.0}

    lost = await oms.verify_position_stops()

    assert lost == []
    assert oms.position_stops() == {"CSCO": 110.0}

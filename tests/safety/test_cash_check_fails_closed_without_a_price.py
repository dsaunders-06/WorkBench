"""The sign-off cash check must fail CLOSED when it cannot price the order.

Regression cover for a real hole: `_reference_price` used to return 0.0 when
the broker could not quote, which made the order's cost 0 and let the
no-leverage check pass unconditionally. AlpacaAdapter raises on
get_market_data by design (it is execution-only), so on a real Alpaca account
that was not a rare outage path - it was every single buy.
"""

from __future__ import annotations

import pandas as pd
import pytest

from qat.config import Settings
from qat.data.broker.adapter import AccountSummary, Order, Position
from qat.domain.bus import EventBus
from qat.domain.oms.oms import OMS
from qat.domain.risk_engine.engine import OrderCandidate, RiskEngine
from qat.domain.risk_engine.kill_switch import KillSwitch


class _QuotelessBroker:
    """Mirrors AlpacaAdapter: real execution and account state, no market data."""

    def __init__(self, cash: float, equity: float = 100_000.0) -> None:
        self._cash = cash
        self._equity = equity
        self.placed: list[Order] = []
        self.held: list[Position] = []

    async def get_market_data(self, symbol: str) -> dict[str, float]:
        raise NotImplementedError("execution and account state only")

    async def get_historical(self, symbol: str, bars: int) -> list[dict[str, float]]:
        raise NotImplementedError("execution and account state only")

    async def place_order(self, order: Order) -> Order:
        self.placed.append(order)
        order.status = "filled"
        order.filled_price = order.reference_price or 0.0
        return order

    async def modify_order(self, order_id: str, **changes: object) -> Order:
        raise NotImplementedError

    async def cancel_order(self, order_id: str) -> Order:
        raise NotImplementedError

    async def positions(self) -> list[Position]:
        return self.held

    async def account(self) -> AccountSummary:
        return AccountSummary(
            net_liquidation=self._equity, cash=self._cash, buying_power=self._cash
        )


def _candidate(price: float = 100.0) -> OrderCandidate:
    dates = pd.date_range("2024-01-01", periods=30)
    return OrderCandidate(
        symbol="AAA",
        side="buy",
        price=price,
        atr=2.0,
        win_rate=0.6,
        win_loss_ratio=2.0,
        candidate_returns=pd.Series([0.001] * 30, index=dates),
    )


def _oms(broker) -> OMS:
    bus = EventBus()
    switch = KillSwitch()
    settings = Settings(_env_file=None)
    engine = RiskEngine(bus, switch, settings=settings)
    return OMS(broker, engine, switch, max_order_pct_of_cash=1.0)


@pytest.mark.asyncio
async def test_submission_records_the_price_the_order_was_sized_against():
    oms = _oms(_QuotelessBroker(cash=100_000.0))
    order = await oms.submit_order(_candidate(price=123.45), 100_000.0, {}, {})
    assert order.reference_price == 123.45


@pytest.mark.asyncio
async def test_a_quoteless_broker_still_enforces_the_cash_check():
    """The submission price carries the check when no live quote exists.

    Cash is dropped between submission and sign-off, which is the case this
    check exists for: an order affordable when sized is not necessarily
    affordable when approved, and bulk sign-off makes that routine.
    """
    broker = _QuotelessBroker(cash=100_000.0)
    oms = _oms(broker)
    order = await oms.submit_order(_candidate(price=100.0), 100_000.0, {}, {})
    assert order.status == "pending_signoff"

    broker._cash = 10.0  # spent elsewhere before this order was approved
    signed = await oms.sign_off(order.order_id, operator="tester")

    assert signed.status == "rejected"
    assert broker.placed == [], "an unaffordable buy must never reach the broker"


@pytest.mark.asyncio
async def test_an_affordable_buy_still_transmits_without_a_quote():
    """Failing closed must not mean failing always - a legitimate order still
    goes through on an execution-only adapter."""
    broker = _QuotelessBroker(cash=100_000.0)
    oms = _oms(broker)
    order = await oms.submit_order(_candidate(price=100.0), 100_000.0, {}, {})

    signed = await oms.sign_off(order.order_id, operator="tester")

    assert signed.status == "filled"
    assert len(broker.placed) == 1


@pytest.mark.asyncio
async def test_an_order_with_no_price_at_all_is_rejected():
    """The last resort: no limit price, no quote, no submission price. There is
    no way to know the cost, so it must not transmit."""
    broker = _QuotelessBroker(cash=100_000.0)
    oms = _oms(broker)
    order = await oms.submit_order(_candidate(price=100.0), 100_000.0, {}, {})
    order.reference_price = None  # simulate a pre-M13 order with no price

    signed = await oms.sign_off(order.order_id, operator="tester")

    assert signed.status == "rejected"
    assert broker.placed == []


@pytest.mark.asyncio
async def test_a_live_quote_is_preferred_over_the_submission_price():
    """A broker that can quote should still be asked - the submission price is
    a fallback, not the primary source."""

    class _FixedQuoteBroker(_QuotelessBroker):
        async def get_market_data(self, symbol: str) -> dict[str, float]:
            return {"ask": 250.0, "last": 249.0}

    broker = _FixedQuoteBroker(cash=100_000.0)
    oms = _oms(broker)
    order = await oms.submit_order(_candidate(price=100.0), 100_000.0, {}, {})
    assert order.reference_price == 100.0

    priced = await oms._costing_price(order)

    assert priced == 250.0, "the live ask should win over the stale submission price"


@pytest.mark.asyncio
async def test_a_sell_is_never_blocked_by_the_pricing_check():
    """Exits raise cash. Refusing to let the account de-risk because a quote is
    missing would be exactly backwards."""
    broker = _QuotelessBroker(cash=0.0)
    broker.held = [Position("AAA", 10.0, 50.0)]
    oms = _oms(broker)
    order = await oms.submit_exit_order("AAA", quantity=10.0, price=50.0)

    signed = await oms.sign_off(order.order_id, operator="tester")

    assert signed.status == "filled"
    assert len(broker.placed) == 1

"""Sign-off re-checks cash against the CURRENT balance (spec M12).

This is load-bearing rather than belt-and-braces. M11 added bulk sign-off, so
several orders that were each individually affordable at submission time can
collectively overdraw the account when approved together - the per-submission
check alone cannot catch that, because it ran when the cash was still there.
"""

from __future__ import annotations

import pandas as pd
import pytest

from qat.config import Settings
from qat.data.broker.adapter import Order
from qat.data.broker.mock_broker import MockBroker
from qat.domain.bus import EventBus
from qat.domain.oms.oms import OMS
from qat.domain.risk_engine.engine import OrderCandidate, RiskEngine
from qat.domain.risk_engine.kill_switch import KillSwitch


class PlaceOrderSpy(MockBroker):
    def __init__(self, seed: int = 1) -> None:
        super().__init__(seed=seed)
        self.place_order_calls = 0

    async def place_order(self, order: Order) -> Order:
        self.place_order_calls += 1
        return await super().place_order(order)


def _candidate(symbol: str) -> OrderCandidate:
    return OrderCandidate(
        symbol=symbol,
        side="buy",
        price=100.0,
        atr=2.0,
        win_rate=0.6,
        win_loss_ratio=2.0,
        candidate_returns=pd.Series([0.01, -0.02] * 30),
    )


def _build() -> tuple[OMS, PlaceOrderSpy, Settings]:
    settings = Settings(_env_file=None)
    engine = RiskEngine(EventBus(), KillSwitch(), settings=settings)
    broker = PlaceOrderSpy(seed=1)
    oms = OMS(broker, engine, engine.kill_switch, max_order_notional=1_000_000.0)
    return oms, broker, settings


@pytest.mark.asyncio
async def test_bulk_signoff_cannot_collectively_overdraw_the_account():
    oms, broker, settings = _build()
    account = await broker.account()

    # Submit everything first, while the full cash balance is still available -
    # so each one passes the submission-time check.
    orders = [
        await oms.submit_order(_candidate(f"S{i}"), account.net_liquidation, {}, {})
        for i in range(12)
    ]
    pending = [o for o in orders if o.status == "pending_signoff"]
    assert len(pending) > 1, "need several pending orders to exercise bulk approval"

    # Then approve them all, as the blotter's bulk sign-off does.
    results = [await oms.sign_off(o.order_id, operator="alice") for o in pending]

    final = await broker.account()
    assert final.cash >= settings.min_cash_reserve
    assert final.cash > 0
    assert any(r.status == "rejected" for r in results), "cash limit must stop the later ones"
    assert broker.place_order_calls == sum(1 for r in results if r.status == "filled")


@pytest.mark.asyncio
async def test_a_rejected_signoff_never_reaches_the_broker():
    oms, broker, _settings = _build()
    account = await broker.account()
    orders = [
        await oms.submit_order(_candidate(f"S{i}"), account.net_liquidation, {}, {})
        for i in range(12)
    ]
    pending = [o for o in orders if o.status == "pending_signoff"]

    calls_before = broker.place_order_calls
    rejected_any = False
    for order in pending:
        result = await oms.sign_off(order.order_id, operator="alice")
        if result.status == "rejected":
            rejected_any = True
            # A rejection must not have incremented the broker call count.
            assert broker.place_order_calls == calls_before
        calls_before = broker.place_order_calls

    assert rejected_any


@pytest.mark.asyncio
async def test_exit_signoff_is_not_blocked_when_cash_is_exhausted():
    """Selling raises cash, so it must stay possible even at the floor."""
    oms, broker, _settings = _build()
    account = await broker.account()
    for i in range(12):
        order = await oms.submit_order(_candidate(f"S{i}"), account.net_liquidation, {}, {})
        if order.status == "pending_signoff":
            await oms.sign_off(order.order_id, operator="alice")

    held = next(p for p in await broker.positions() if p.quantity > 0)
    exit_order = await oms.submit_exit_order(held.symbol, quantity=held.quantity, price=100.0)
    result = await oms.sign_off(exit_order.order_id, operator="alice")

    assert result.status == "filled"

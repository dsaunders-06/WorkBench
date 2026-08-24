"""Spec-mandated safety test 2/5: no order reaches the broker without an
explicit human sign-off (spec §I, §M, §O). This is the safety-critical
invariant the whole OMS is built around - tested here directly against a
broker spy, not just indirectly through OMS unit tests.
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


def _flat_returns(n: int = 30) -> pd.Series:
    dates = pd.date_range("2024-01-01", periods=n)
    return pd.Series([0.001] * n, index=dates)


def _candidate(symbol: str = "AAA") -> OrderCandidate:
    return OrderCandidate(
        symbol=symbol,
        side="buy",
        price=100.0,
        atr=2.0,
        win_rate=0.6,
        win_loss_ratio=2.0,
        candidate_returns=_flat_returns(),
    )


def _build_oms() -> tuple[OMS, PlaceOrderSpy]:
    bus = EventBus()
    switch = KillSwitch()
    # Portfolio caps are set generously here on purpose: these tests
    # exercise the SIGN-OFF gate, and the governor blocking first would
    # mean they stopped testing what they claim to.
    engine = RiskEngine(
        bus,
        switch,
        settings=Settings(
            _env_file=None,
            max_aggregate_risk_at_stop_pct=1.0,
            max_concurrent_positions=100,
            # M30's caps relaxed for the same stated reason: these isolate the
            # sign-off gate, and a position trimmed by concentration or the gap
            # budget never reaches the cash limit under test.
            max_single_name_concentration_pct=1.0,
            max_gap_risk_at_shock_pct=1.0,
        ),
    )
    broker = PlaceOrderSpy(seed=1)
    oms = OMS(broker, engine, switch, max_order_pct_of_cash=1.0)
    return oms, broker


@pytest.mark.asyncio
async def test_submit_order_alone_never_calls_broker_place_order():
    oms, broker = _build_oms()

    order = await oms.submit_order(_candidate(), 100_000.0, {}, {})

    assert order.status == "pending_signoff"
    assert broker.place_order_calls == 0


@pytest.mark.asyncio
async def test_many_submissions_without_signoff_never_call_broker():
    oms, broker = _build_oms()

    for i in range(20):
        await oms.submit_order(_candidate(f"SYM{i}"), 100_000.0, {}, {})

    assert broker.place_order_calls == 0
    assert all(order.status == "pending_signoff" for order in oms.orders())


@pytest.mark.asyncio
async def test_reject_and_cancel_never_call_broker_place_order():
    oms, broker = _build_oms()

    order_a = await oms.submit_order(_candidate("AAA"), 100_000.0, {}, {})
    await oms.reject_order(order_a.order_id, operator="alice", reason="test")

    order_b = await oms.submit_order(_candidate("BBB"), 100_000.0, {}, {})
    await oms.cancel_order(order_b.order_id)

    assert broker.place_order_calls == 0


@pytest.mark.asyncio
async def test_sign_off_is_the_only_path_that_calls_broker_place_order():
    oms, broker = _build_oms()

    order = await oms.submit_order(_candidate(), 100_000.0, {}, {})
    assert broker.place_order_calls == 0

    await oms.sign_off(order.order_id, operator="alice")

    assert broker.place_order_calls == 1


@pytest.mark.asyncio
async def test_kill_switch_active_prevents_signoff_from_reaching_broker():
    oms, broker = _build_oms()
    order = await oms.submit_order(_candidate(), 100_000.0, {}, {})

    oms.kill_switch.trigger_manual("operator")  # trips between submission and sign-off

    result = await oms.sign_off(order.order_id, operator="alice")

    assert result.status == "rejected"
    assert broker.place_order_calls == 0

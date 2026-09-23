"""Broker-accepted order identity must survive an application restart.

Unsigned proposals deliberately do not survive: their price, cash and risk
evidence is stale after a restart and restoring them would let the autonomy
retry path sign a decision made against the previous session.  Once an order
has been handed to the broker, however, forgetting either its application id
or broker id makes a later execution look unrelated and removes the independent
duplicate-transmission guard.
"""

from __future__ import annotations

from dataclasses import replace

import pandas as pd
import pytest

from qat.config import Settings
from qat.data.broker.adapter import Order
from qat.data.broker.mock_broker import MockBroker
from qat.domain.bus import EventBus
from qat.domain.events import OrderRejectedEvent
from qat.domain.oms.oms import OMS
from qat.domain.risk_engine.engine import OrderCandidate, RiskEngine
from qat.domain.risk_engine.kill_switch import KillSwitch


class _ReIdingBroker(MockBroker):
    async def place_order(self, order: Order) -> Order:
        placed = await super().place_order(order)
        return replace(
            placed,
            order_id="broker-9001",
            status="transmitted",
            filled_quantity=0.0,
            filled_price=None,
        )


class _CountingBroker(MockBroker):
    def __init__(self) -> None:
        super().__init__(seed=1)
        self.place_calls = 0

    async def place_order(self, order: Order) -> Order:
        self.place_calls += 1
        return await super().place_order(order)


class _LateIdBroker(_CountingBroker):
    async def place_order(self, order: Order) -> Order:
        self.place_calls += 1
        return replace(
            order,
            status="transmitted",
            filled_quantity=0.0,
            filled_price=None,
        )


class _CancellableLateIdBroker(_LateIdBroker):
    async def cancel_order(self, order_id: str) -> Order:
        return Order(
            symbol="AAA",
            side="buy",
            quantity=150.0,
            order_id=order_id,
            status="cancelled",
            reference_price=100.0,
            strategy="swing",
        )


class _AcknowledgementLostBroker(_CountingBroker):
    async def place_order(self, order: Order) -> Order:
        self.place_calls += 1
        raise TimeoutError("acceptance unknown")


def _oms(tmp_path, broker=None) -> tuple[OMS, KillSwitch]:
    settings = Settings(_env_file=None, data_dir=str(tmp_path))
    bus = EventBus()
    switch = KillSwitch(data_dir=tmp_path)
    engine = RiskEngine(bus, switch, settings=settings)
    return (
        OMS(
            broker or _ReIdingBroker(seed=1),
            engine,
            switch,
            max_order_pct_of_cash=1.0,
            bus=bus,
            settings=settings,
        ),
        switch,
    )


def _candidate() -> OrderCandidate:
    returns = pd.Series([0.001] * 30, index=pd.date_range("2026-01-01", periods=30))
    return OrderCandidate(
        symbol="AAA",
        side="buy",
        price=100.0,
        atr=2.0,
        win_rate=0.6,
        win_loss_ratio=2.0,
        candidate_returns=returns,
        strategy="swing",
    )


@pytest.mark.asyncio
async def test_broker_accepted_order_and_both_ids_survive_restart(tmp_path) -> None:
    first, _ = _oms(tmp_path)
    proposed = await first.submit_order(_candidate(), 100_000.0, {}, {})
    app_id = proposed.order_id
    transmitted = await first.sign_off(app_id, "operator")

    assert transmitted.order_id == "broker-9001"

    restarted, switch = _oms(tmp_path, MockBroker(seed=2))

    restored_by_app = restarted.get_order(app_id)
    restored_by_broker = restarted.get_order("broker-9001")
    assert restored_by_app is restored_by_broker
    assert restored_by_broker.status == "transmitted"
    assert restored_by_broker.strategy == "swing"
    assert app_id in restarted._transmitted
    assert "broker-9001" in restarted._broker_order_ids
    assert restarted.pending_orders() == [restored_by_broker]
    assert not switch.tripped


def test_unsigned_proposal_is_not_restored_for_later_signoff(tmp_path) -> None:
    first, _ = _oms(tmp_path)
    first._new_pending_order("AAA", "buy", 10.0, 100.0, "swing")

    restarted, _ = _oms(tmp_path, MockBroker(seed=2))

    assert restarted.awaiting_signoff() == []
    assert restarted.orders() == []


@pytest.mark.asyncio
async def test_completed_order_is_retired_only_after_fill_state_is_saved(tmp_path) -> None:
    first, _ = _oms(tmp_path, MockBroker(seed=1))
    proposed = await first.submit_order(_candidate(), 100_000.0, {}, {})
    completed = await first.sign_off(proposed.order_id, "operator")
    assert completed.status == "filled"

    restarted, _ = _oms(tmp_path, MockBroker(seed=2))

    assert restarted.orders() == []
    assert restarted._absorbed_fills[completed.order_id].quantity == completed.quantity


@pytest.mark.asyncio
async def test_broker_is_not_called_when_transmission_intent_cannot_be_saved(
    tmp_path, monkeypatch
) -> None:
    broker = _CountingBroker()
    oms, switch = _oms(tmp_path, broker)
    proposed = await oms.submit_order(_candidate(), 100_000.0, {}, {})
    assert oms._order_identity is not None

    def fail_save(*_args, **_kwargs):
        raise OSError("disk unavailable")

    monkeypatch.setattr(oms._order_identity, "_save", fail_save)
    refused = await oms.sign_off(proposed.order_id, "operator")

    assert refused.status == "rejected"
    assert broker.place_calls == 0
    assert switch.tripped


@pytest.mark.asyncio
async def test_restart_halts_on_order_whose_broker_acknowledgement_was_lost(tmp_path) -> None:
    broker = _AcknowledgementLostBroker()
    first, switch = _oms(tmp_path, broker)
    proposed = await first.submit_order(_candidate(), 100_000.0, {}, {})
    result = await first.sign_off(proposed.order_id, "operator")

    assert result.status == "transmitted"
    assert broker.place_calls == 1
    assert proposed.order_id in first._transmitted
    assert first.pending_orders() == [result]
    assert first.awaiting_signoff() == []
    assert switch.tripped

    restarted, restarted_switch = _oms(tmp_path, MockBroker(seed=2))
    restored = restarted.get_order(proposed.order_id)
    assert restored.status == "transmitted"
    assert restarted.pending_orders() == [restored]
    assert restarted.awaiting_signoff() == []
    assert restarted_switch.tripped


@pytest.mark.asyncio
async def test_confirmed_async_rejection_is_not_resurrected_as_working(tmp_path) -> None:
    first, _ = _oms(tmp_path, _LateIdBroker())
    proposed = await first.submit_order(_candidate(), 100_000.0, {}, {})
    accepted = await first.sign_off(proposed.order_id, "operator")
    assert accepted.status == "transmitted"

    await first._on_order_rejected(
        OrderRejectedEvent(
            order_id=proposed.order_id,
            symbol=proposed.symbol,
            side=proposed.side,
            booked_quantity=proposed.quantity,
            executed_quantity=0.0,
            reason="broker confirmed the order is dead",
        )
    )

    restarted, switch = _oms(tmp_path, MockBroker(seed=2))
    restored = restarted.get_order(proposed.order_id)
    assert restored.status == "rejected"
    assert restarted.pending_orders() == []
    assert not switch.tripped


@pytest.mark.asyncio
async def test_broker_id_resolved_after_acceptance_is_durable(tmp_path) -> None:
    first, _ = _oms(tmp_path, _LateIdBroker())
    proposed = await first.submit_order(_candidate(), 100_000.0, {}, {})
    app_id = proposed.order_id
    await first.sign_off(app_id, "operator")
    first.register_broker_order_id("late-broker-42", app_id)

    restarted, switch = _oms(tmp_path, MockBroker(seed=2))

    assert restarted.get_order(app_id) is restarted.get_order("late-broker-42")
    assert "late-broker-42" in restarted._broker_order_ids
    assert not switch.tripped


@pytest.mark.asyncio
async def test_confirmed_cancellation_is_not_resurrected_as_working(tmp_path) -> None:
    first, _ = _oms(tmp_path, _CancellableLateIdBroker())
    proposed = await first.submit_order(_candidate(), 100_000.0, {}, {})
    accepted = await first.sign_off(proposed.order_id, "operator")
    assert accepted.status == "transmitted"
    cancelled = await first.cancel_order(proposed.order_id)
    assert cancelled.status == "cancelled"

    restarted, switch = _oms(tmp_path, MockBroker(seed=2))
    restored = restarted.get_order(proposed.order_id)
    assert restored.status == "cancelled"
    assert restarted.pending_orders() == []
    assert not switch.tripped


def test_unreadable_identity_store_halts_order_flow(tmp_path) -> None:
    (tmp_path / "inflight_orders.json").write_text("{not-json", encoding="utf-8")

    restarted, switch = _oms(tmp_path, MockBroker(seed=2))

    assert restarted.orders() == []
    assert switch.tripped
    assert "identity unreadable" in switch.reason

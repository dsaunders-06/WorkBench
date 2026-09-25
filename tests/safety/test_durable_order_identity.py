"""Broker-accepted order identity must survive an application restart.

Unsigned proposals deliberately do not survive: their price, cash and risk
evidence is stale after a restart and restoring them would let the autonomy
retry path sign a decision made against the previous session.  Once an order
has been handed to the broker, however, forgetting either its application id
or broker id makes a later execution look unrelated and removes the independent
duplicate-transmission guard.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime

import pandas as pd
import pytest

from qat.config import Settings
from qat.data.broker.adapter import BrokerFill, Order
from qat.data.broker.mock_broker import MockBroker
from qat.domain.bus import EventBus
from qat.domain.events import BrokerOrderIdResolvedEvent, OrderFilledEvent, OrderRejectedEvent
from qat.domain.oms.oms import OMS
from qat.domain.oms.signal_bridge import SignalToOrderBridge
from qat.domain.performance.trades import TradeLedger
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


async def _restart_stack(tmp_path):
    oms, _ = _oms(tmp_path, _LateIdBroker())
    ledger = TradeLedger(oms.bus, tmp_path, settings=oms.settings)
    bridge = SignalToOrderBridge(oms.bus, oms, settings=oms.settings, trade_ledger=ledger)
    oms.bus.subscribe(OrderFilledEvent, bridge._on_fill, critical=True)
    oms.bus.subscribe(BrokerOrderIdResolvedEvent, bridge._on_order_id_resolved)
    await ledger.start()
    await bridge.restore_open_lots()
    oms.watch_symbols_for_fills(["WOW.AX"])
    return oms, oms.broker, bridge, ledger


async def _partially_filled_qat_order(tmp_path, quantity=4.0):
    oms, broker, bridge, ledger = await _restart_stack(tmp_path)
    order = oms._new_pending_order("WOW.AX", "buy", 10.0, 100.0, "swing")
    app_id = order.order_id
    await oms.sign_off(app_id, "operator")
    broker._broker_fills[:] = [
        BrokerFill(app_id, "WOW.AX", "buy", quantity, 101.0, datetime.now(UTC))
    ]
    await oms.absorb_broker_fills()
    assert bridge.position_entries()["WOW.AX"].quantity == quantity
    return oms, broker, bridge, ledger, app_id


async def _stop_at_identity_boundary(first, cumulative, crash_point, monkeypatch):
    if crash_point == "before_resolution":
        return
    store = first._order_identity
    assert store is not None
    if crash_point == "after_identity":
        original = store.put

        def crash(*args, **kwargs):
            original(*args, **kwargs)
            raise SystemExit("after_identity")

        monkeypatch.setattr(store, "put", crash)
    elif crash_point == "after_alias":
        original = first._save_fill_state

        def crash():
            result = original()
            if getattr(first, "_fill_aliases", {}).get("998877") == cumulative.app_order_id:
                assert result
                raise SystemExit("after_alias")
            return result

        monkeypatch.setattr(first, "_save_fill_state", crash)
    else:
        original = store.remove

        def crash(*args, **kwargs):
            original(*args, **kwargs)
            raise SystemExit("after_retirement")

        monkeypatch.setattr(store, "remove", crash)
    first.broker._broker_fills[:] = [cumulative]
    with pytest.raises(SystemExit, match=crash_point):
        first.register_broker_order_id("998877", cumulative.app_order_id)
        await first.bus.publish(
            BrokerOrderIdResolvedEvent(order_id="998877", app_order_id=cumulative.app_order_id)
        )
        await first.absorb_broker_fills()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "crash_point", ["before_resolution", "after_identity", "after_alias", "after_retirement"]
)
async def test_late_broker_id_restart_keeps_one_cumulative_receipt(
    tmp_path, crash_point, monkeypatch
):
    first, _, _, _, app_id = await _partially_filled_qat_order(tmp_path)
    cumulative = BrokerFill("998877", "WOW.AX", "buy", 10.0, 102.0, datetime.now(UTC), app_id)
    await _stop_at_identity_boundary(first, cumulative, crash_point, monkeypatch)

    restarted, broker, bridge, ledger = await _restart_stack(tmp_path)
    broker._broker_fills[:] = [cumulative]
    await restarted.absorb_broker_fills()
    await restarted.absorb_broker_fills()

    entry = bridge.position_entries()["WOW.AX"]
    lots = ledger.open_lots("WOW.AX")
    assert entry.quantity == 10.0
    assert entry.price == pytest.approx(102.0)
    assert entry.order_id == app_id
    assert sum(lot.quantity for lot in lots) == 10.0
    assert {lot.order_id for lot in lots} == {app_id}
    assert {fill_id for lot in lots for fill_id in lot.fill_ids} == {
        f"{app_id}|WOW.AX|buy|4",
        f"{app_id}|WOW.AX|buy|10",
    }
    assert sum(lot.entry_cost for lot in lots) == pytest.approx(ledger._fill_cost(10.0, 102.0))
    assert not restarted.kill_switch.tripped


@pytest.mark.asyncio
@pytest.mark.parametrize("crash_point", ["after_identity", "after_alias", "after_retirement"])
async def test_durable_resolution_handles_a_broker_only_replay(tmp_path, monkeypatch, crash_point):
    first, _, _, _, app_id = await _partially_filled_qat_order(tmp_path)
    cumulative = BrokerFill("998877", "WOW.AX", "buy", 10.0, 102.0, datetime.now(UTC), app_id)
    await _stop_at_identity_boundary(first, cumulative, crash_point, monkeypatch)
    restarted, broker, bridge, ledger = await _restart_stack(tmp_path)
    broker._broker_fills[:] = [replace(cumulative, app_order_id=None)]
    await restarted.absorb_broker_fills()
    await restarted.absorb_broker_fills()
    assert bridge.position_entries()["WOW.AX"].quantity == 10.0
    assert sum(lot.quantity for lot in ledger.open_lots("WOW.AX")) == 10.0
    assert sum(lot.entry_cost for lot in ledger.open_lots("WOW.AX")) == pytest.approx(6.60)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["identity", "aliases", "missing_alias_path"])
async def test_failed_resolution_keeps_receipt_and_identity_replayable(
    tmp_path, monkeypatch, failure
):
    first, broker, bridge, ledger, app_id = await _partially_filled_qat_order(tmp_path)
    cumulative = BrokerFill("998877", "WOW.AX", "buy", 10.0, 102.0, datetime.now(UTC), app_id)
    broker._broker_fills[:] = [cumulative]
    with monkeypatch.context() as patch:
        if failure == "identity":

            def fail(*args, **kwargs):
                raise OSError("identity disk unavailable")

            patch.setattr(first._order_identity, "put", fail)
        elif failure == "aliases":
            patch.setattr(first, "_save_fill_state", lambda: False)
        else:
            patch.setattr(first, "_fill_state_path", None)
        await first.absorb_broker_fills()
        first._prune_completed_order_identities()
    assert first.kill_switch.tripped
    assert bridge.position_entries()["WOW.AX"].quantity == 4.0
    assert sum(lot.quantity for lot in ledger.open_lots("WOW.AX")) == 4.0
    assert app_id in first._order_identity.records
    assert "998877" not in first._fill_aliases
    restarted, broker, bridge, ledger = await _restart_stack(tmp_path)
    broker._broker_fills[:] = [cumulative]
    await restarted.absorb_broker_fills()
    assert bridge.position_entries()["WOW.AX"].quantity == 10.0
    assert sum(lot.entry_cost for lot in ledger.open_lots("WOW.AX")) == pytest.approx(6.60)


@pytest.mark.asyncio
async def test_pending_canonical_delivery_survives_late_resolution_and_restart(tmp_path):
    first, broker, bridge, _, app_id = await _partially_filled_qat_order(tmp_path)

    async def fail(_event):
        raise OSError("consumer unavailable after entry persistence")

    first.bus.subscribe(OrderFilledEvent, fail, critical=True)
    cumulative = BrokerFill("998877", "WOW.AX", "buy", 10.0, 102.0, datetime.now(UTC), app_id)
    broker._broker_fills[:] = [cumulative]
    await first.absorb_broker_fills()
    assert first.kill_switch.tripped
    assert bridge.position_entries()["WOW.AX"].quantity == 10.0
    assert list(first._pending_fill_deliveries) == [f"{app_id}|WOW.AX|buy|10"]
    assert app_id in first._order_identity.records
    restarted, broker, bridge, ledger = await _restart_stack(tmp_path)
    broker._broker_fills[:] = [replace(cumulative, app_order_id=None)]
    await restarted.absorb_broker_fills()
    await restarted.absorb_broker_fills()
    assert bridge.position_entries()["WOW.AX"].quantity == 10.0
    assert sum(lot.quantity for lot in ledger.open_lots("WOW.AX")) == 10.0
    assert sum(lot.entry_cost for lot in ledger.open_lots("WOW.AX")) == pytest.approx(6.60)
    assert restarted._pending_fill_deliveries == {}


@pytest.mark.parametrize(
    "aliases", [{"": "app"}, {"broker": ""}, {"broker": 42}, {"a": "b", "b": "a"}, []]
)
def test_invalid_fill_aliases_halt_restart(tmp_path, aliases):
    (tmp_path / "absorbed_fills.json").write_text(
        json.dumps(
            {"watermark": datetime.now(UTC).isoformat(), "absorbed": {}, "aliases": aliases}
        ),
        encoding="utf-8",
    )
    _, switch = _oms(tmp_path)
    assert switch.tripped
    assert "journal unreadable" in switch.reason


@pytest.mark.asyncio
async def test_legacy_fill_file_without_aliases_retains_its_receipt(tmp_path):
    first, _, _, _, app_id = await _partially_filled_qat_order(tmp_path)
    path = tmp_path / "absorbed_fills.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data.pop("aliases", None)
    path.write_text(json.dumps(data), encoding="utf-8")
    restarted, broker, bridge, _ = await _restart_stack(tmp_path)
    broker._broker_fills[:] = [
        BrokerFill("998877", "WOW.AX", "buy", 10.0, 102.0, datetime.now(UTC), app_id)
    ]
    await restarted.absorb_broker_fills()
    assert bridge.position_entries()["WOW.AX"].quantity == 10.0

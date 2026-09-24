"""Confirmed fills must not be retired before every durable record accepts them."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from qat.config import Settings
from qat.data.broker.adapter import Position
from qat.data.broker.mock_broker import MockBroker
from qat.domain.bus import EventBus
from qat.domain.events import OrderFilledEvent
from qat.domain.oms.oms import OMS
from qat.domain.oms.signal_bridge import SignalToOrderBridge
from qat.domain.performance.trades import TradeLedger
from qat.domain.risk_engine.engine import OrderCandidate, RiskEngine
from qat.domain.risk_engine.kill_switch import KillSwitch


def _candidate() -> OrderCandidate:
    return OrderCandidate(
        symbol="AAA",
        side="buy",
        price=100.0,
        atr=2.0,
        win_rate=0.55,
        win_loss_ratio=1.5,
        candidate_returns=pd.Series([0.01, -0.01] * 30),
        strategy="swing",
    )


@pytest.mark.asyncio
async def test_a_failed_closed_trade_write_keeps_the_fill_replayable(tmp_path):
    """A logged ledger failure must not become a permanently absorbed fill.

    Reproduces the current crash boundary with production-shaped components:
    the ledger cannot append the close, while the OMS can still write its
    cumulative-fill file.  A restart would otherwise skip the broker fill and
    lose the closed trade permanently.
    """
    settings = Settings(_env_file=None, data_dir=str(tmp_path))
    bus = EventBus()
    kill_switch = KillSwitch()
    broker = MockBroker(seed=1)
    broker._positions["AAA"] = Position(symbol="AAA", quantity=10.0, avg_price=100.0)
    broker._resting_stops["AAA"] = 95.0

    ledger = TradeLedger(bus, tmp_path, settings=settings)
    await ledger.start()
    assert ledger.restore_open_lot(
        "AAA",
        10.0,
        100.0,
        95.0,
        "swing",
        datetime(2026, 9, 1, tzinfo=UTC),
    )

    oms = OMS(
        broker,
        RiskEngine(bus, kill_switch, settings=settings),
        kill_switch,
        bus=bus,
        settings=settings,
    )
    await oms.adopt_broker_positions()
    oms._last_fill_scan -= timedelta(seconds=1)

    # Replacing a directory with the atomic CSV image raises OSError.
    blocked = tmp_path / "blocked-ledger"
    blocked.mkdir()
    ledger.path = blocked

    broker.fill_resting_stop("AAA", price=94.0)
    await oms.absorb_broker_fills()

    assert kill_switch.tripped is True
    assert "AAA" not in {trade.symbol for trade in ledger.closed_trades()}
    failed_state = json.loads((tmp_path / "absorbed_fills.json").read_text(encoding="utf-8"))
    assert failed_state["absorbed"] == {}
    assert len(failed_state["pending_deliveries"]) == 1

    ledger.path = tmp_path / "closed_trades.csv"
    kill_switch.reset("test operator repaired the ledger destination")
    replayed = await oms.absorb_broker_fills()

    assert len(replayed) == 1
    assert [trade.symbol for trade in ledger.closed_trades()] == ["AAA"]
    assert (tmp_path / "absorbed_fills.json").exists()

    await oms.absorb_broker_fills()
    assert [trade.symbol for trade in ledger.closed_trades()] == ["AAA"]


@pytest.mark.asyncio
async def test_a_failed_entry_write_keeps_an_acknowledged_buy_replayable(tmp_path):
    settings = Settings(_env_file=None, data_dir=str(tmp_path))
    bus = EventBus()
    kill_switch = KillSwitch()
    broker = MockBroker(seed=1)
    oms = OMS(
        broker,
        RiskEngine(bus, kill_switch, settings=settings),
        kill_switch,
        bus=bus,
        settings=settings,
    )
    bridge = SignalToOrderBridge(bus, oms, settings=settings)
    bus.subscribe(OrderFilledEvent, bridge._on_fill, critical=True)

    blocked = tmp_path / "blocked-entries"
    blocked.mkdir()
    bridge._entries_path = blocked

    pending = await oms.submit_order(_candidate(), 100_000.0, {}, {})
    await oms.sign_off(pending.order_id, "test operator")

    assert kill_switch.tripped is True
    assert pending.symbol not in bridge.position_entries()
    failed_state = json.loads((tmp_path / "absorbed_fills.json").read_text(encoding="utf-8"))
    assert failed_state["absorbed"] == {}
    assert len(failed_state["pending_deliveries"]) == 1


@pytest.mark.asyncio
async def test_replaying_after_a_sibling_failure_does_not_double_the_entry(tmp_path):
    settings = Settings(_env_file=None, data_dir=str(tmp_path))
    bus = EventBus()
    kill_switch = KillSwitch()
    broker = MockBroker(seed=1)
    oms = OMS(
        broker,
        RiskEngine(bus, kill_switch, settings=settings),
        kill_switch,
        bus=bus,
        settings=settings,
    )
    bridge = SignalToOrderBridge(bus, oms, settings=settings)
    bus.subscribe(OrderFilledEvent, bridge._on_fill, critical=True)

    async def fail_after_the_entry_writes(_event: OrderFilledEvent) -> None:
        raise OSError("second durable consumer failed")

    bus.subscribe(OrderFilledEvent, fail_after_the_entry_writes, critical=True)
    pending = await oms.submit_order(_candidate(), 100_000.0, {}, {})
    await oms.sign_off(pending.order_id, "test operator")

    first_quantity = bridge.position_entries()[pending.symbol].quantity
    assert first_quantity is not None
    assert kill_switch.tripped is True

    restarted_bus = EventBus()
    restarted_switch = KillSwitch()
    restarted_oms = OMS(
        broker,
        RiskEngine(restarted_bus, restarted_switch, settings=settings),
        restarted_switch,
        bus=restarted_bus,
        settings=settings,
    )
    restarted_bridge = SignalToOrderBridge(restarted_bus, restarted_oms, settings=settings)
    restarted_bus.subscribe(OrderFilledEvent, restarted_bridge._on_fill, critical=True)
    replayed = await restarted_oms.absorb_broker_fills()

    assert len(replayed) == 1
    assert restarted_bridge.position_entries()[pending.symbol].quantity == first_quantity
    assert (tmp_path / "absorbed_fills.json").exists()
    completed_state = json.loads((tmp_path / "absorbed_fills.json").read_text(encoding="utf-8"))
    assert completed_state["pending_deliveries"] == {}


@pytest.mark.asyncio
async def test_a_partial_close_receipt_survives_sibling_failure_and_restart(tmp_path):
    settings = Settings(_env_file=None, data_dir=str(tmp_path))
    bus = EventBus()
    ledger = TradeLedger(bus, tmp_path, settings=settings)
    await ledger.start()
    opened_at = datetime(2026, 9, 1, tzinfo=UTC)
    assert ledger.restore_open_lot("AAA", 100.0, 100.0, 95.0, "swing", opened_at)

    async def fail_after_the_ledger_writes(_event: OrderFilledEvent) -> None:
        raise OSError("second durable consumer failed")

    bus.subscribe(OrderFilledEvent, fail_after_the_ledger_writes, critical=True)
    event = OrderFilledEvent(
        order_id="sell-1",
        symbol="AAA",
        side="sell",
        quantity=40.0,
        cumulative_quantity=40.0,
        price=94.0,
        fill_id="sell-1|AAA|sell|40",
        ts=datetime(2026, 9, 24, tzinfo=UTC),
    )
    assert len(await bus.publish(event)) == 1
    assert [trade.quantity for trade in ledger.closed_trades()] == [40.0]
    assert [lot.quantity for lot in ledger.open_lots("AAA")] == [60.0]

    bus.unsubscribe(OrderFilledEvent, fail_after_the_ledger_writes)
    assert await bus.publish(event) == ()
    assert [trade.quantity for trade in ledger.closed_trades()] == [40.0]
    assert [lot.quantity for lot in ledger.open_lots("AAA")] == [60.0]

    await ledger.stop()
    restarted_bus = EventBus()
    restarted = TradeLedger(restarted_bus, tmp_path, settings=settings)
    assert restarted.restore_open_lot("AAA", 60.0, 100.0, 95.0, "swing", opened_at)
    await restarted.start()
    assert await restarted_bus.publish(event) == ()
    assert [trade.quantity for trade in restarted.closed_trades()] == [40.0]
    assert [lot.quantity for lot in restarted.open_lots("AAA")] == [60.0]

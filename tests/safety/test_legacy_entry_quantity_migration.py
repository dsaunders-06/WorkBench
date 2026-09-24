"""Legacy entry quantities must be settled before startup fill replay."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from qat.config import Settings
from qat.data.broker.adapter import BrokerFill, Position
from qat.data.broker.mock_broker import MockBroker
from qat.domain.bus import EventBus
from qat.domain.oms.oms import OMS
from qat.domain.oms.signal_bridge import SignalToOrderBridge
from qat.domain.performance.trades import TradeLedger
from qat.domain.risk_engine.engine import RiskEngine
from qat.domain.risk_engine.kill_switch import KillSwitch


def _legacy_entry_file(tmp_path, symbol: str = "OLD") -> bytes:
    path = tmp_path / "open_position_entries.json"
    path.write_text(
        json.dumps(
            {
                symbol: {
                    "opened_at": "2026-07-20T00:00:00+00:00",
                    "price": 50.0,
                    "stop_price": 45.0,
                    "target_price": 60.0,
                    "strategy": "swing",
                }
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return path.read_bytes()


def _fill_state(tmp_path, before: datetime) -> None:
    (tmp_path / "absorbed_fills.json").write_text(
        json.dumps({"watermark": before.isoformat(), "absorbed": {}}), encoding="utf-8"
    )


async def _started_bridge(tmp_path, broker: MockBroker):
    settings = Settings(_env_file=None, data_dir=str(tmp_path), deployed_strategies="swing")
    bus = EventBus()
    switch = KillSwitch()
    ledger = TradeLedger(bus, tmp_path, settings=settings)
    await ledger.start()
    oms = OMS(
        broker, RiskEngine(bus, switch, settings=settings), switch, bus=bus, settings=settings
    )
    bridge = SignalToOrderBridge(bus, oms, settings=settings, trade_ledger=ledger)
    await oms.adopt_broker_positions()
    await bridge.start()
    return bridge, ledger, switch


@pytest.mark.asyncio
async def test_a_partial_offline_exit_migrates_the_pre_replay_quantity(tmp_path):
    """Restoring only the current remainder makes the replay close shares twice."""
    original = _legacy_entry_file(tmp_path)
    stamp = datetime.now(UTC) - timedelta(minutes=1)
    _fill_state(tmp_path, stamp - timedelta(seconds=1))
    broker = MockBroker(seed=1)
    broker._positions["OLD"] = Position("OLD", 60.0, 50.0)
    broker._broker_fills = [BrokerFill("sell-1", "OLD", "sell", 40.0, 44.0, stamp)]

    bridge, ledger, switch = await _started_bridge(tmp_path, broker)
    try:
        assert [trade.quantity for trade in ledger.closed_trades()] == [40.0]
        assert [lot.quantity for lot in ledger.open_lots("OLD")] == [60.0]
        assert bridge.position_entries()["OLD"].quantity == 60.0
        stored = json.loads((tmp_path / "open_position_entries.json").read_text(encoding="utf-8"))
        assert stored["OLD"]["quantity"] == 60.0
        assert (
            tmp_path / "open_position_entries.json.bak-pre-quantity-migration"
        ).read_bytes() == original
        assert switch.tripped is False
    finally:
        await bridge.stop()
        await ledger.stop()


@pytest.mark.asyncio
async def test_a_completed_quantity_migration_is_idempotent_at_the_next_restart(tmp_path):
    original = _legacy_entry_file(tmp_path)
    stamp = datetime.now(UTC) - timedelta(minutes=1)
    _fill_state(tmp_path, stamp - timedelta(seconds=1))
    broker = MockBroker(seed=1)
    broker._positions["OLD"] = Position("OLD", 60.0, 50.0)
    broker._broker_fills = [BrokerFill("sell-1", "OLD", "sell", 40.0, 44.0, stamp)]

    first, first_ledger, first_switch = await _started_bridge(tmp_path, broker)
    await first.stop()
    await first_ledger.stop()
    migrated = (tmp_path / "open_position_entries.json").read_bytes()

    second, second_ledger, second_switch = await _started_bridge(tmp_path, broker)
    try:
        assert [trade.quantity for trade in second_ledger.closed_trades()] == [40.0]
        assert [lot.quantity for lot in second_ledger.open_lots("OLD")] == [60.0]
        assert second.position_entries()["OLD"].quantity == 60.0
        assert (tmp_path / "open_position_entries.json").read_bytes() == migrated
        assert (
            tmp_path / "open_position_entries.json.bak-pre-quantity-migration"
        ).read_bytes() == original
        assert first_switch.tripped is False
        assert second_switch.tripped is False
    finally:
        await second.stop()
        await second_ledger.stop()


@pytest.mark.asyncio
async def test_a_fully_closed_legacy_entry_is_migrated_before_replay(tmp_path):
    original = _legacy_entry_file(tmp_path)
    stamp = datetime.now(UTC) - timedelta(minutes=1)
    _fill_state(tmp_path, stamp - timedelta(seconds=1))
    broker = MockBroker(seed=1)
    broker._broker_fills = [BrokerFill("sell-1", "OLD", "sell", 100.0, 44.0, stamp)]

    bridge, ledger, switch = await _started_bridge(tmp_path, broker)
    try:
        assert [trade.quantity for trade in ledger.closed_trades()] == [100.0]
        assert bridge.position_entries() == {}
        assert (
            json.loads((tmp_path / "open_position_entries.json").read_text(encoding="utf-8")) == {}
        )
        assert (
            tmp_path / "open_position_entries.json.bak-pre-quantity-migration"
        ).read_bytes() == original
        assert switch.tripped is False
    finally:
        await bridge.stop()
        await ledger.stop()


@pytest.mark.asyncio
async def test_a_flat_legacy_record_without_unabsorbed_fills_is_retired(tmp_path):
    original = _legacy_entry_file(tmp_path, "STALE")
    broker = MockBroker(seed=1)

    bridge, ledger, switch = await _started_bridge(tmp_path, broker)
    try:
        assert bridge.position_entries() == {}
        assert (
            json.loads((tmp_path / "open_position_entries.json").read_text(encoding="utf-8")) == {}
        )
        assert (
            tmp_path / "open_position_entries.json.bak-pre-quantity-migration"
        ).read_bytes() == original
        assert switch.tripped is False
    finally:
        await bridge.stop()
        await ledger.stop()


@pytest.mark.asyncio
async def test_contradictory_legacy_quantity_evidence_fails_closed(tmp_path):
    original = _legacy_entry_file(tmp_path)
    stamp = datetime.now(UTC) - timedelta(minutes=1)
    _fill_state(tmp_path, stamp - timedelta(seconds=1))
    broker = MockBroker(seed=1)
    broker._positions["OLD"] = Position("OLD", 10.0, 50.0)
    broker._broker_fills = [BrokerFill("buy-1", "OLD", "buy", 20.0, 49.0, stamp)]

    bridge, ledger, switch = await _started_bridge(tmp_path, broker)
    try:
        assert switch.tripped is True
        assert switch.reason == "legacy entry quantities contradict stable broker evidence"
        assert (tmp_path / "open_position_entries.json").read_bytes() == original
        assert not (tmp_path / "open_position_entries.json.bak-pre-quantity-migration").exists()
        assert ledger.closed_trades() == []
    finally:
        await bridge.stop()
        await ledger.stop()


@pytest.mark.asyncio
async def test_a_failed_legacy_backup_leaves_the_entry_file_unchanged(tmp_path):
    original = _legacy_entry_file(tmp_path)
    broker = MockBroker(seed=1)
    broker._positions["OLD"] = Position("OLD", 20.0, 50.0)
    (tmp_path / "open_position_entries.json.bak-pre-quantity-migration").mkdir()

    bridge, ledger, switch = await _started_bridge(tmp_path, broker)
    try:
        assert switch.tripped is True
        assert switch.reason == "legacy entry quantity backup could not be secured"
        assert (tmp_path / "open_position_entries.json").read_bytes() == original
        assert bridge.position_entries()["OLD"].quantity is None
    finally:
        await bridge.stop()
        await ledger.stop()

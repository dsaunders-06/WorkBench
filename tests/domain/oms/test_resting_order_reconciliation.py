"""The orphan scan, wired into the OMS (M141, item 23)."""

from __future__ import annotations

import logging

import pytest

from qat.config import Settings
from qat.data.broker.adapter import Position, RestingOrder
from qat.domain.bus import EventBus
from qat.domain.oms.oms import OMS
from qat.domain.risk_engine.engine import RiskEngine
from qat.domain.risk_engine.kill_switch import KillSwitch


def _order(order_id, symbol="TNE.AX", side="sell", qty=3051.0, oca=None):
    return RestingOrder(
        symbol=symbol,
        order_id=str(order_id),
        side=side,
        order_type="STP",
        quantity=qty,
        status="PreSubmitted",
        oca_group=oca,
        owner_client_id=1,
        stop_price=30.69,
    )


class _Broker:
    def __init__(self, orders, positions):
        self._orders, self._positions = orders, positions
        self.cancelled: list[str] = []

    async def open_orders(self):
        return self._orders

    async def positions(self):
        return self._positions

    async def cancel_order(self, order_id):
        self.cancelled.append(order_id)


@pytest.fixture
def oms_factory(tmp_path):
    """Mirrors `test_oms.py`'s `_oms` helper: `Settings(_env_file=None, ...)`
    so construction never reads `%LOCALAPPDATA%\\QuantAdvisoryTerminal\\.env`.

    Unlike that helper, `settings` here IS passed through to `OMS` - with
    `data_dir=tmp_path` - so `RestingOrderAnomalyStore` gets a real,
    test-isolated place to persist to rather than reading `oms.settings is
    None` and going memory-only.

    `resting_order_cancel_enabled` does not exist on `Settings` yet (Task 6
    adds it); `Settings.model_config` sets `extra="ignore"`, so passing it
    ahead of that is silently dropped rather than raising, and this fixture's
    signature is already the one Task 7 depends on.
    """

    def _make(broker, cancel_enabled: bool = False):
        settings = Settings(
            _env_file=None,
            data_dir=str(tmp_path),
            resting_order_cancel_enabled=cancel_enabled,  # ignored until Task 6
        )
        switch = KillSwitch()
        engine = RiskEngine(EventBus(), switch, settings=settings)
        return OMS(broker, engine, switch, settings=settings)

    return _make


@pytest.mark.asyncio
async def test_a_flat_symbol_with_legs_is_quarantined(oms_factory):
    broker = _Broker(
        [_order(1), _order(2)], [Position(symbol="TNE.AX", quantity=0.0, avg_price=0.0)]
    )
    oms = oms_factory(broker)
    found = await oms.check_resting_orders()
    assert len(found) == 1
    assert oms.resting_order_anomalies.is_quarantined("TNE.AX")


@pytest.mark.asyncio
async def test_the_live_TNE_bracket_is_left_alone(oms_factory):
    broker = _Broker(
        [_order(1, oca="OCA-1"), _order(2, oca="OCA-1")],
        [Position(symbol="TNE.AX", quantity=3051.0, avg_price=32.9783)],
    )
    oms = oms_factory(broker)
    assert await oms.check_resting_orders() == []
    assert not oms.resting_order_anomalies.is_quarantined("TNE.AX")


@pytest.mark.asyncio
async def test_every_leg_is_named_in_the_log(oms_factory, caplog):
    broker = _Broker([_order(1), _order(2)], [])
    with caplog.at_level(logging.ERROR):
        await oms_factory(broker).check_resting_orders()
    logged = caplog.text
    assert "RESTING ORDER ORPHAN" in logged
    assert "1 sell STP" in logged and "2 sell STP" in logged


@pytest.mark.asyncio
async def test_a_broker_without_the_capability_judges_nothing(oms_factory):
    class _Old:
        async def positions(self):
            return []

    oms = oms_factory(_Old())
    assert await oms.check_resting_orders() == []


@pytest.mark.asyncio
async def test_it_does_not_touch_the_position_kill_switch(oms_factory):
    broker = _Broker([_order(1)], [])
    oms = oms_factory(broker)
    await oms.check_resting_orders()
    assert not oms.kill_switch.tripped


@pytest.mark.asyncio
async def test_the_scan_quarantines_the_symbol(oms_factory):
    """The refusal itself is exercised by the existing entry-path tests; what
    this asserts is that the scan puts the symbol into the store those read."""
    broker = _Broker([_order(1)], [])
    oms = oms_factory(broker)
    await oms.check_resting_orders()
    assert oms.resting_order_anomalies.get("TNE.AX").excess == 3051.0


@pytest.mark.asyncio
async def test_the_scan_runs_at_startup_before_any_strategy_could_trade(oms_factory, monkeypatch):
    """The 24 August orphans were INHERITED across a restart. A poll-only rail
    would have found them one interval late.

    Both stubs must be COROUTINES. `start()` awaits the scan and passes `_run()`
    to `asyncio.create_task`, so a plain lambda raises rather than failing the
    assertion, which reads as an unrelated error.
    """
    from qat.domain.oms.reconciliation import ReconciliationMonitor

    calls: list[str] = []

    async def _scan():
        calls.append("scan")
        return []

    async def _never_run():
        return None

    oms = oms_factory(_Broker([_order(1)], []))
    monkeypatch.setattr(oms, "check_resting_orders", _scan)
    monitor = ReconciliationMonitor(oms)
    monkeypatch.setattr(monitor, "_run", _never_run)
    await monitor.start()
    await monitor.stop()
    assert calls == ["scan"]


def test_the_settings_default_correctly():
    """Detection on, cancelling off. The second is the one that matters."""
    from qat.config import Settings

    settings = Settings()
    assert settings.resting_order_reconcile_enabled is True
    assert settings.resting_order_cancel_enabled is False


@pytest.mark.asyncio
async def test_detection_can_be_switched_off(oms_factory, monkeypatch):
    from qat.config import Settings
    from qat.domain.oms.reconciliation import ReconciliationMonitor

    calls: list[str] = []

    async def _scan():
        calls.append("scan")
        return []

    async def _never_run():
        return None

    oms = oms_factory(_Broker([_order(1)], []))
    monkeypatch.setattr(oms, "check_resting_orders", _scan)
    monitor = ReconciliationMonitor(oms, settings=Settings(resting_order_reconcile_enabled=False))
    monkeypatch.setattr(monitor, "_run", _never_run)
    await monitor.start()
    await monitor.stop()
    assert calls == []

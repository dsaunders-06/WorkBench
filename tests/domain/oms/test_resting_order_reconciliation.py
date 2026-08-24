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
    """

    def _make(broker, cancel_enabled: bool = False):
        settings = Settings(
            _env_file=None,
            data_dir=str(tmp_path),
            resting_order_cancel_enabled=cancel_enabled,
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
async def test_a_broker_without_the_capability_judges_nothing(oms_factory, caplog):
    """I2, final review: `[]` is also what a CLEAN scan returns, so asserting
    only the return value cannot tell "checked, clean" from "never checked".
    The ERROR line is the only thing that can - it must name the adapter and
    say plainly that this was not a clean scan."""

    class _Old:
        async def positions(self):
            return []

    oms = oms_factory(_Old())
    with caplog.at_level(logging.ERROR):
        assert await oms.check_resting_orders() == []
    assert "RESTING ORDER SCAN" in caplog.text
    assert "_Old" in caplog.text
    assert "not a clean scan" in caplog.text.lower()


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
    """Detection on, cancelling off. The second is the one that matters.

    `_env_file=None` is load-bearing: without it this asserts whatever the
    operator's real .env says, not the declared defaults.
    """
    from qat.config import Settings

    settings = Settings(_env_file=None)  # type: ignore[arg-type]
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
    settings = Settings(  # type: ignore[arg-type]
        _env_file=None, resting_order_reconcile_enabled=False
    )
    monitor = ReconciliationMonitor(oms, settings=settings)
    monkeypatch.setattr(monitor, "_run", _never_run)
    await monitor.start()
    await monitor.stop()
    assert calls == []


@pytest.mark.asyncio
async def test_cancel_is_off_by_default(oms_factory):
    broker = _Broker([_order(1), _order(2)], [])
    await oms_factory(broker).check_resting_orders()
    assert broker.cancelled == []


@pytest.mark.asyncio
async def test_with_the_flag_on_a_flat_symbol_is_cancelled(oms_factory):
    broker = _Broker([_order(1), _order(2)], [])
    oms = oms_factory(broker, cancel_enabled=True)
    await oms.check_resting_orders()
    assert broker.cancelled == ["1", "2"]


@pytest.mark.asyncio
async def test_a_HELD_symbol_is_never_cancelled(oms_factory):
    """Excess on a held name is reported and quarantined, never trimmed.
    Choosing which OCA group dies strips the stop from a real long."""
    broker = _Broker(
        [_order(1, qty=3076.0), _order(2, qty=3076.0), _order(3, qty=3076.0)],
        [Position(symbol="TNE.AX", quantity=3076.0, avg_price=32.0)],
    )
    oms = oms_factory(broker, cancel_enabled=True)
    found = await oms.check_resting_orders()
    assert found and found[0].excess > 0
    assert broker.cancelled == []
    assert oms.resting_order_anomalies.is_quarantined("TNE.AX")


@pytest.mark.asyncio
async def test_one_refused_cancel_does_not_abort_the_rest(oms_factory, caplog):
    """Error 10147: visible via reqAllOpenOrders, not cancellable from here."""

    class _Stubborn(_Broker):
        async def cancel_order(self, order_id):
            if order_id == "1":
                raise RuntimeError("Error 10147: order not found from this client")
            self.cancelled.append(order_id)

    broker = _Stubborn([_order(1), _order(2), _order(3)], [])
    with caplog.at_level(logging.ERROR):
        await oms_factory(broker, cancel_enabled=True).check_resting_orders()
    assert broker.cancelled == ["2", "3"]
    assert "10147" in caplog.text or "could not be cancelled" in caplog.text


# --- I2: the heartbeat -----------------------------------------------------


@pytest.mark.asyncio
async def test_a_clean_scan_emits_the_heartbeat(oms_factory, caplog):
    """I2, final review. `[]` is what a scan that ran and found nothing
    returns - the same as an adapter stub, a disabled setting, or a missing
    capability. Only a log line can tell them apart, and it must be present
    even when there is nothing to complain about."""
    broker = _Broker([], [])
    with caplog.at_level(logging.INFO):
        assert await oms_factory(broker).check_resting_orders() == []
    assert "RESTING ORDER SCAN:" in caplog.text
    assert "nothing unjustified" in caplog.text


@pytest.mark.asyncio
async def test_the_heartbeat_is_also_present_when_there_are_divergences(oms_factory, caplog):
    broker = _Broker([_order(1), _order(2)], [])
    with caplog.at_level(logging.INFO):
        await oms_factory(broker).check_resting_orders()
    assert "RESTING ORDER SCAN:" in caplog.text


# --- I5: the per-divergence ERROR is throttled ------------------------------


@pytest.mark.asyncio
async def test_an_unchanged_divergence_logs_the_error_once_across_three_scans(oms_factory, caplog):
    """With cancelling off (the default) an unresolved divergence is detected
    again on every poll. Logging the ERROR every time turned one incident into
    ~78 identical blocks across a trading day."""
    broker = _Broker([_order(1), _order(2)], [])
    oms = oms_factory(broker)
    with caplog.at_level(logging.ERROR):
        await oms.check_resting_orders()
        await oms.check_resting_orders()
        await oms.check_resting_orders()
    assert caplog.text.count("RESTING ORDER ORPHAN") == 1


@pytest.mark.asyncio
async def test_a_changed_excess_logs_again(oms_factory, caplog):
    broker = _Broker([_order(1)], [])
    oms = oms_factory(broker)
    with caplog.at_level(logging.ERROR):
        await oms.check_resting_orders()
        broker._orders.append(_order(2))
        await oms.check_resting_orders()
    assert caplog.text.count("RESTING ORDER ORPHAN") == 2


# --- Task 7a: settings=None is a real construction --------------------------


@pytest.mark.asyncio
async def test_settings_none_never_cancels_a_flat_orphan():
    """`OMS(settings=None)` is a real construction in this codebase -
    `test_oms.py`'s `_oms` helper builds every OMS in that file exactly this
    way. The cancel guard's `self.settings is None` clause was, until this
    test, verified only by inspection."""
    broker = _Broker([_order(1), _order(2)], [])
    bus = EventBus()
    switch = KillSwitch()
    settings = Settings(_env_file=None)
    engine = RiskEngine(bus, switch, settings=settings)
    oms = OMS(broker, engine, switch, settings=None)

    await oms.check_resting_orders()

    assert broker.cancelled == []


# --- Task 7b: TOCTOU between the flatness check and each cancel -------------


class _FlipBroker(_Broker):
    """Reports one set of positions on the first call, a different set on
    every call after - the scan's own snapshot, then the TOCTOU re-read."""

    def __init__(self, orders, first_positions, later_positions):
        super().__init__(orders, first_positions)
        self._later_positions = later_positions
        self.position_calls = 0

    async def positions(self):
        self.position_calls += 1
        if self.position_calls == 1:
            return self._positions
        return self._later_positions


@pytest.mark.asyncio
async def test_toctou_abandons_the_cancel_if_the_broker_is_no_longer_flat_at_the_reread(
    oms_factory, caplog
):
    """The scenario in the review doc: eight orphan legs on a flat symbol,
    cancelling enabled, one leg's stop-sell fills mid-loop. A broker that
    reports flat on the scan and non-flat on the immediate re-read must cancel
    nothing."""
    broker = _FlipBroker(
        [_order(1), _order(2)],
        [Position(symbol="TNE.AX", quantity=0.0, avg_price=0.0)],
        [Position(symbol="TNE.AX", quantity=-3051.0, avg_price=30.69)],
    )
    oms = oms_factory(broker, cancel_enabled=True)
    with caplog.at_level(logging.ERROR):
        await oms.check_resting_orders()
    assert broker.cancelled == []
    assert "abandoned" in caplog.text.lower()


@pytest.mark.asyncio
async def test_toctou_also_checks_this_apps_own_tracked_quantity(oms_factory, caplog):
    """The second, independent signal (Task 7b): even a broker that still
    reports flat at the re-read is not trusted alone - this app's own tracked
    fill count for the symbol must agree too."""
    broker = _Broker([_order(1), _order(2)], [])
    oms = oms_factory(broker, cancel_enabled=True)
    oms._filled_quantities["TNE.AX"] = -3051.0  # this app believes it just filled

    with caplog.at_level(logging.ERROR):
        await oms.check_resting_orders()

    assert broker.cancelled == []
    assert "abandoned" in caplog.text.lower()

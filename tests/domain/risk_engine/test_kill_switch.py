from __future__ import annotations

import pytest

from qat.domain.bus import EventBus
from qat.domain.events import DataStaleEvent, KillSwitchEvent
from qat.domain.risk_engine.kill_switch import KillSwitch, KillSwitchEngine


def test_starts_untripped():
    switch = KillSwitch()
    assert switch.tripped is False
    assert switch.reason is None


def test_daily_loss_trips_at_limit():
    switch = KillSwitch()
    switch.check_daily_loss(day_start_equity=100_000.0, current_equity=96_000.0, limit_pct=0.03)
    assert switch.tripped is True
    assert "Daily loss" in switch.reason


def test_daily_loss_does_not_trip_below_limit():
    switch = KillSwitch()
    switch.check_daily_loss(day_start_equity=100_000.0, current_equity=99_000.0, limit_pct=0.03)
    assert switch.tripped is False


def test_drawdown_trips_at_limit():
    switch = KillSwitch()
    switch.check_drawdown(high_water_mark=100_000.0, current_equity=79_000.0, limit_pct=0.20)
    assert switch.tripped is True
    assert "Drawdown" in switch.reason


def test_drawdown_does_not_trip_below_limit():
    switch = KillSwitch()
    switch.check_drawdown(high_water_mark=100_000.0, current_equity=85_000.0, limit_pct=0.20)
    assert switch.tripped is False


def test_a_stale_quote_is_no_longer_a_halt_condition():
    """M28a. Every trip this rail produced was a false positive - with a 60s
    poll against a 60s threshold, a trade arriving 40s old was already past
    the line. The switch has no staleness path left to call."""
    assert not hasattr(KillSwitch(), "check_staleness")


def test_reconciliation_mismatch_trips():
    switch = KillSwitch()
    switch.check_reconciliation()
    assert switch.tripped is True
    assert "reconciliation" in switch.reason.lower()


def test_manual_trigger_trips_with_operator_attribution():
    switch = KillSwitch()
    switch.trigger_manual("alice")
    assert switch.tripped is True
    assert "alice" in switch.reason


def test_reset_clears_tripped_state():
    switch = KillSwitch()
    switch.trigger_manual("alice")
    switch.reset("bob")
    assert switch.tripped is False
    assert switch.reason is None


def test_once_tripped_stays_tripped_until_reset():
    switch = KillSwitch()
    switch.trigger_manual("alice")
    switch.check_daily_loss(day_start_equity=100_000.0, current_equity=99_900.0, limit_pct=0.03)
    assert switch.tripped is True


@pytest.mark.asyncio
async def test_a_stale_quote_does_not_halt_the_account():
    """The M28a inversion. Halting the whole account because Berkshire had not
    printed on IEX by 09:30:15 is a rail doing more damage than the hazard it
    guards against. The symbol is excluded from signals instead."""
    bus = EventBus()
    switch = KillSwitch()
    engine = KillSwitchEngine(bus, switch)
    await engine.start()

    await bus.publish(DataStaleEvent(symbol="BRK.B", seconds_since_update=63_017.0))

    assert switch.tripped is False
    await engine.stop()


@pytest.mark.asyncio
async def test_engine_trips_on_kill_switch_event():
    bus = EventBus()
    switch = KillSwitch()
    engine = KillSwitchEngine(bus, switch)
    await engine.start()

    await bus.publish(KillSwitchEvent(reason="manual halt", triggered_by="operator1"))

    assert switch.tripped is True
    assert "operator1" in switch.reason
    await engine.stop()


@pytest.mark.asyncio
async def test_engine_stop_unsubscribes():
    bus = EventBus()
    switch = KillSwitch()
    engine = KillSwitchEngine(bus, switch)
    await engine.start()
    await engine.stop()

    await bus.publish(DataStaleEvent(symbol="AAPL", seconds_since_update=120.0))

    assert switch.tripped is False

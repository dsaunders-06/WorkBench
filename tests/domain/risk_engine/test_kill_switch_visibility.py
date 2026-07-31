"""A halt nobody can see is worse than no halt at all (spec §H/§18.2).

The kill-switch worked correctly and told no one. Three paths tripped it
without publishing anything - the staleness detector, the Risk Console's
button, and every direct trip() call - so the main window's banner went on
reading AUTO-TRADE ACTIVE while order flow was in fact stopped. The state was
right and every view of it was wrong, which is the failure mode an operator
cannot recover from: they believe the system is running.

These tests pin the notification, not the halting. The halting was never
broken.
"""

from __future__ import annotations

import logging

import pytest

from qat.domain.bus import EventBus
from qat.domain.events import KillSwitchEvent
from qat.domain.risk_engine.kill_switch import KillSwitch, KillSwitchEngine


def test_listener_fires_on_every_trip_path() -> None:
    """Structural, not per-path: a listener registered once sees them all.

    The original defect was that each new trip site had to remember to
    announce itself. Anything that only tested the two sites that were fixed
    would let the third be added just as silent.
    """
    switch = KillSwitch()
    seen: list[str | None] = []
    switch.add_listener(lambda: seen.append(switch.reason))

    switch.trigger_manual("alice")
    assert seen == ["Manual trigger by alice"]

    switch.reset("test")
    assert seen[-1] is None

    switch.trigger_manual("operator")
    switch.reset("test")
    switch.check_reconciliation()
    switch.reset("test")
    switch.check_daily_loss(day_start_equity=100.0, current_equity=90.0, limit_pct=0.05)
    switch.reset("test")
    switch.check_drawdown(high_water_mark=100.0, current_equity=80.0, limit_pct=0.10)

    assert len(seen) == 9


def test_a_failing_listener_cannot_block_a_halt() -> None:
    """The switch stops trading whatever the UI does with the news."""
    switch = KillSwitch()
    switch.add_listener(lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    reached: list[str] = []
    switch.add_listener(lambda: reached.append("second listener"))

    switch.trigger_manual("operator")

    assert switch.tripped
    assert reached == ["second listener"]


def test_a_trip_is_logged_once_and_keeps_the_first_reason(caplog) -> None:
    """The staleness detector fires every few seconds.

    Without the idempotence guard that floods the log and, worse, overwrites
    the original cause: "data staleness" replacing "daily loss limit" loses
    the fact that actually mattered.
    """
    switch = KillSwitch()
    with caplog.at_level(logging.WARNING, logger="qat.domain.risk_engine.kill_switch"):
        switch.check_daily_loss(day_start_equity=100.0, current_equity=90.0, limit_pct=0.05)
        switch.trigger_manual("alice")
        switch.trigger_manual("alice")

    assert switch.reason is not None
    assert switch.reason.startswith("Daily loss")
    tripped_lines = [r for r in caplog.records if "KILL-SWITCH TRIPPED" in r.message]
    assert len(tripped_lines) == 1
    assert "Daily loss" in tripped_lines[0].getMessage()


def test_reset_is_logged_with_the_operator_and_the_reason(caplog) -> None:
    switch = KillSwitch()
    switch.trigger_manual("operator (risk console)")
    with caplog.at_level(logging.WARNING, logger="qat.domain.risk_engine.kill_switch"):
        switch.reset("operator (risk console)")

    assert not switch.tripped
    message = caplog.records[-1].getMessage()
    assert "reset by operator (risk console)" in message
    assert "Manual trigger" in message


@pytest.mark.asyncio
async def test_a_reconciliation_trip_is_announced_on_the_bus() -> None:
    """Staleness no longer halts (M28a), so reconciliation stands in as the
    path that trips without publishing anything of its own."""
    bus = EventBus()
    switch = KillSwitch()
    seen: list[KillSwitchEvent] = []

    async def handler(event: KillSwitchEvent) -> None:
        seen.append(event)

    bus.subscribe(KillSwitchEvent, handler)
    engine = KillSwitchEngine(bus, switch)
    await engine.start()

    switch.check_reconciliation()
    await bus.publish(
        KillSwitchEvent(reason=switch.reason or "", triggered_by="reconciliation monitor")
    )

    assert seen and "reconciliation" in seen[0].reason.lower()
    await engine.stop()

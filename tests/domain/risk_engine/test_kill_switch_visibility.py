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
from qat.domain.events import DataStaleEvent, KillSwitchEvent
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

    switch.check_staleness()
    assert seen == ["Data staleness detected"]

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
        switch.check_staleness()
        switch.check_staleness()

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
async def test_a_staleness_trip_is_announced_on_the_bus() -> None:
    """The path that halted the most silently, and the likeliest to fire.

    A stale feed is the one trip an unattended session actually hits, and it
    published nothing at all.
    """
    bus = EventBus()
    switch = KillSwitch()
    engine = KillSwitchEngine(bus, switch)
    await engine.start()

    announced: list[KillSwitchEvent] = []

    async def record(event: KillSwitchEvent) -> None:
        announced.append(event)

    bus.subscribe(KillSwitchEvent, record)

    await engine._on_stale(DataStaleEvent(symbol="AAPL", seconds_since_update=90.0))

    assert switch.tripped
    assert len(announced) == 1
    assert "AAPL" in announced[0].reason
    assert "90s" in announced[0].reason
    assert announced[0].triggered_by == "staleness detector"

    # Repeats stay quiet: the detector fires on a timer, and one halt is one
    # halt however many times the feed reports itself stale.
    await engine._on_stale(DataStaleEvent(symbol="AAPL", seconds_since_update=95.0))
    assert len(announced) == 1

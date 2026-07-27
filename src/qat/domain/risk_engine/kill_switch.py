"""Kill-switch (spec §H/§18.2): trips on daily-loss, drawdown-from-HWM,
data-staleness, broker-reconciliation-mismatch, or a manual trigger. Halts
new orders and overrides every strategy and the AI layer - always visible
in the UI, never silently suppressed.

KillSwitch is a plain, framework-free state machine so it's trivially
testable in isolation; KillSwitchEngine is a thin bus-wired wrapper that
subscribes to the existing DataStaleEvent/KillSwitchEvent (both declared in
events.py since M1) and trips the shared KillSwitch instance.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from qat.domain.bus import EventBus
from qat.domain.events import DataStaleEvent, KillSwitchEvent

logger = logging.getLogger(__name__)


class KillSwitch:
    def __init__(self) -> None:
        self._tripped = False
        self._reason: str | None = None
        self._listeners: list[Callable[[], None]] = []

    def add_listener(self, listener: Callable[[], None]) -> None:
        """Called synchronously whenever the switch trips or is reset.

        A plain callback rather than a bus event, for two reasons. It fires on
        EVERY path structurally - the direct trip() calls from staleness and
        the Risk Console previously published nothing, so views of the switch
        silently disagreed with it, and patching each call site would leave the
        next one to be added just as silent. And it needs no running event
        loop, where an async publish from a Qt slot depends on one existing.
        """
        self._listeners.append(listener)

    def _notify(self) -> None:
        for listener in self._listeners:
            try:
                listener()
            except Exception:  # noqa: BLE001 - a bad listener must not block a halt
                logger.exception("A kill-switch listener failed")

    @property
    def tripped(self) -> bool:
        return self._tripped

    @property
    def reason(self) -> str | None:
        return self._reason

    def trip(self, reason: str) -> None:
        """Halt new order flow, and say so.

        Logged, because a halt is the single most important state change the
        application can undergo and it previously wrote nothing at all - a
        session could stop trading and the log would show only the silence
        that followed.

        Ignoring a repeat trip is deliberate on both counts. The staleness
        detector fires every few seconds, so without this the log would be
        flooded and, worse, the ORIGINAL cause would be overwritten - "data
        staleness" replacing "daily loss limit" loses the fact that actually
        mattered.
        """
        if self._tripped:
            return
        self._tripped = True
        self._reason = reason
        logger.warning("KILL-SWITCH TRIPPED: %s. All new order flow is halted.", reason)
        self._notify()

    def check_daily_loss(
        self, day_start_equity: float, current_equity: float, limit_pct: float
    ) -> None:
        if day_start_equity <= 0:
            return
        loss_pct = (day_start_equity - current_equity) / day_start_equity
        if loss_pct >= limit_pct:
            self.trip(f"Daily loss {loss_pct:.2%} >= limit {limit_pct:.2%}")

    def check_drawdown(
        self, high_water_mark: float, current_equity: float, limit_pct: float
    ) -> None:
        if high_water_mark <= 0:
            return
        drawdown_pct = (high_water_mark - current_equity) / high_water_mark
        if drawdown_pct >= limit_pct:
            self.trip(f"Drawdown {drawdown_pct:.2%} >= limit {limit_pct:.2%}")

    def check_staleness(self) -> None:
        self.trip("Data staleness detected")

    def check_reconciliation(self) -> None:
        self.trip("Broker reconciliation mismatch")

    def trigger_manual(self, operator: str) -> None:
        self.trip(f"Manual trigger by {operator}")

    def reset(self, operator: str) -> None:
        """Explicit human-attributed action required to clear a tripped switch."""
        if self._tripped:
            logger.warning(
                "Kill-switch reset by %s - order flow resumes (was: %s)", operator, self._reason
            )
        self._tripped = False
        self._reason = None
        self._notify()


class KillSwitchEngine:
    """Engine (per domain.orchestrator.Engine protocol)."""

    name = "kill-switch-engine"

    def __init__(self, bus: EventBus, kill_switch: KillSwitch) -> None:
        self.bus = bus
        self.kill_switch = kill_switch

    async def start(self) -> None:
        self.bus.subscribe(DataStaleEvent, self._on_stale)
        self.bus.subscribe(KillSwitchEvent, self._on_kill_switch_event)

    async def stop(self) -> None:
        self.bus.unsubscribe(DataStaleEvent, self._on_stale)
        self.bus.unsubscribe(KillSwitchEvent, self._on_kill_switch_event)

    async def _on_stale(self, event: DataStaleEvent) -> None:
        """Trip, then announce it.

        check_staleness() only mutates state. Nothing was published, so the
        main window's banner - which listens for KillSwitchEvent - kept
        reading AUTO-TRADE ACTIVE while trading was in fact halted. A halt
        nobody can see is worse than no halt at all, because the operator
        believes the system is working.
        """
        was_tripped = self.kill_switch.tripped
        self.kill_switch.check_staleness()
        if not was_tripped:
            await self.bus.publish(
                KillSwitchEvent(
                    reason=(
                        f"data staleness on {event.symbol} "
                        f"({event.seconds_since_update:.0f}s without an update)"
                    ),
                    triggered_by="staleness detector",
                )
            )

    async def _on_kill_switch_event(self, event: KillSwitchEvent) -> None:
        self.kill_switch.trip(f"{event.reason} (triggered by {event.triggered_by})")

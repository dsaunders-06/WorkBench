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

from qat.domain.bus import EventBus
from qat.domain.events import DataStaleEvent, KillSwitchEvent


class KillSwitch:
    def __init__(self) -> None:
        self._tripped = False
        self._reason: str | None = None

    @property
    def tripped(self) -> bool:
        return self._tripped

    @property
    def reason(self) -> str | None:
        return self._reason

    def trip(self, reason: str) -> None:
        self._tripped = True
        self._reason = reason

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
        self._tripped = False
        self._reason = None


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
        self.kill_switch.check_staleness()

    async def _on_kill_switch_event(self, event: KillSwitchEvent) -> None:
        self.kill_switch.trip(f"{event.reason} (triggered by {event.triggered_by})")

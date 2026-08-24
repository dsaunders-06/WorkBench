"""Broker reconciliation, actually running (spec M15).

`OMS.check_reconciliation` has existed since M6 and, like the daily-loss and
drawdown rails before M13, was called from nowhere in `src/` - it was a
reconciliation capability rather than a reconciliation check. This engine is
what makes it run.

It also solves the ordering problem that made it unusable against a real
account: an OMS that has filled nothing, compared against an Alpaca paper
account carrying positions from a previous session or another application,
reports a mismatch on the first call and trips the kill-switch at startup,
every time. Adopting the existing holdings as an explicit, logged baseline
first is what makes every *subsequent* mismatch meaningful.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging

from qat.config import Settings
from qat.domain.bus import EventBus
from qat.domain.events import KillSwitchEvent
from qat.domain.oms.oms import OMS

logger = logging.getLogger(__name__)


class ReconciliationMonitor:
    """Engine (per domain.orchestrator.Engine protocol)."""

    name = "reconciliation-monitor"

    def __init__(
        self,
        oms: OMS,
        settings: Settings | None = None,
        bus: EventBus | None = None,
        poll_seconds: float | None = None,
    ) -> None:
        self.oms = oms
        self.settings = settings or Settings()
        self.bus = bus
        self.poll_seconds = poll_seconds or self.settings.reconciliation_poll_seconds
        self.adopted: dict[str, float] = {}
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        # Adoption happens before the first check, and before any strategy can
        # have produced an order, so the baseline is genuinely "what was here
        # when we arrived".
        try:
            self.adopted = await self.oms.adopt_broker_positions()
        except Exception:  # noqa: BLE001 - a broker blip must not block startup
            logger.warning(
                "Could not adopt broker positions at startup - reconciliation is "
                "suppressed until the first successful poll",
                exc_info=True,
            )
            self.adopted = {}

        # After adoption and before the first poll, because the orphans this
        # looks for are INHERITED across a restart - the 24 August case exactly
        # - and a poll-only rail finds them one interval late.
        if self.settings.resting_order_reconcile_enabled:
            try:
                await self.oms.check_resting_orders()
            except Exception:  # noqa: BLE001 - a broker blip must not block startup
                logger.warning(
                    "Could not scan resting orders at startup - the first poll will retry",
                    exc_info=True,
                )
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(self.poll_seconds)
            try:
                await self.poll()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - one bad poll must not end the rail
                logger.exception("Reconciliation poll failed; continuing")

    async def poll(self) -> bool:
        """One reconciliation check. Returns True if a mismatch was found.

        Public so a test or the Risk Console can force a check without waiting
        on the interval.
        """
        was_tripped = self.oms.kill_switch.tripped
        mismatch = await self.oms.check_reconciliation()

        if self.settings.resting_order_reconcile_enabled:
            await self.oms.check_resting_orders()

        # KillSwitch.trip() publishes nothing, so without this a reconciliation
        # halt would be real but invisible to every screen - the same gap the
        # equity rails had before M13.
        if self.bus is not None and mismatch and not was_tripped:
            await self.bus.publish(
                KillSwitchEvent(
                    reason=self.oms.kill_switch.reason or "broker reconciliation mismatch",
                    triggered_by=self.name,
                )
            )
        return mismatch

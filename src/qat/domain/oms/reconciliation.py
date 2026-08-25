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

# Consecutive timed-out polls before the log escalates from ERROR to
# CRITICAL. Three at the default interval is a quarter of an hour with
# every reconciliation rail off, which is no longer a blip.
_TIMEOUTS_BEFORE_CRITICAL = 3


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
        self._consecutive_timeouts = 0
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
        """One reconciliation check, under a DEADLINE. True if a mismatch was
        found; False if the poll did not complete in time.

        Public so a test or a caller can force a check without waiting on the
        interval. (The Risk Console cannot yet - see item 36; this docstring
        used to claim it could, and that claim was believed.)

        **The deadline is item 34.** On 25 August this poll wedged at 09:09:52
        and completed none of the ~20 due in the following 6h50m, while the app
        traded normally. Nothing raised, so `_run`'s handler never fired and
        not one line was written: a dead reconciliation loop and a healthy one
        produced identical logs.

        A timeout does NOT trip the kill-switch. Deliberately: a false timeout
        would halt a live account, and this guard has no field history. It logs
        ERROR, and CRITICAL once the rails have been off for several intervals
        running - whether that should escalate to a halt is the operator's call
        and is recorded as an open question on item 34.
        """
        timeout = self.settings.reconciliation_poll_timeout_seconds
        try:
            result = await asyncio.wait_for(self._poll_once(), timeout=timeout)
        except TimeoutError:
            self._consecutive_timeouts += 1
            logger.error(
                "Reconciliation poll DID NOT COMPLETE within %.0fs (%d in a row). Every rail "
                "behind it is off while this persists: nothing compares the book to the "
                "broker, nothing verifies a stop still rests, the resting-order scan does not "
                "run, and broker-side fills are NOT absorbed - so a stop firing now would go "
                "unrecorded and the app would keep believing it holds the position.",
                timeout,
                self._consecutive_timeouts,
            )
            if self._consecutive_timeouts >= _TIMEOUTS_BEFORE_CRITICAL:
                logger.critical(
                    "Reconciliation has not completed a poll in %d consecutive attempts. The "
                    "account is trading with its reconciliation rails DOWN. Investigate or "
                    "halt.",
                    self._consecutive_timeouts,
                )
            return False
        if self._consecutive_timeouts:
            logger.warning(
                "Reconciliation poll completed again after %d timed-out attempt(s).",
                self._consecutive_timeouts,
            )
            self._consecutive_timeouts = 0
        return result

    async def _poll_once(self) -> bool:
        """The check itself. Wrapped by `poll` so the deadline cannot be
        bypassed by a caller that forgets it."""
        was_tripped = self.oms.kill_switch.tripped
        mismatch = await self.oms.check_reconciliation()

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

        # AFTER the publish above, and in its own try/except - both deliberate
        # (C1, final review). This used to run BEFORE the publish: a poll that
        # found a real mismatch tripped the switch, and if THIS scan then raised
        # (a broker blip on open_orders(), a gateway disconnect, positions()
        # timing out) poll() aborted before the event was ever sent. Every later
        # poll's `was_tripped` is already True at that point, so `not was_tripped`
        # above is False forever after - the halt is real and PERMANENTLY
        # invisible to every screen, which is the precise gap the comment on the
        # publish block says it exists to close. Do not move this back above the
        # publish.
        if self.settings.resting_order_reconcile_enabled:
            try:
                await self.oms.check_resting_orders()
            except Exception:  # noqa: BLE001 - must not swallow the mismatch just published
                logger.exception(
                    "Resting-order scan failed during poll; the broker reconciliation "
                    "result above is unaffected and already published"
                )
        return mismatch

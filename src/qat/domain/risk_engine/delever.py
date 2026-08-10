"""De-levering sweep (spec M15).

The governor blocks *new* risk once aggregate risk-at-stop is over cap. That
alone only unwinds a breach passively - as stops hit and positions close on
their own. The reference implementation measured that passive unwind at
roughly 6 points a week against readings of 36.8% and 30.4% versus a 5% cap,
which is not remotely fast enough to matter.

This sweep is the active half: when over cap, trim every position by the same
proportion until the portfolio is back under. Proportional rather than a
judgement about which position is "worst", because aggregate risk-at-stop is a
linear sum of each position's (quantity x per-share risk) - scaling every
quantity by one fraction scales the whole sum by that fraction, hitting the
target exactly without ranking anything.

**Off by default.** This engine SELLS, and a rail that sells without being
asked is a materially larger delegation than one that merely declines to buy.
With it disabled a breach is still detected, logged and surfaced, and new risk
is still blocked by the governor - the portfolio just unwinds passively.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import math

from qat.config import Settings
from qat.domain.bus import EventBus
from qat.domain.oms.oms import OMS
from qat.domain.risk_engine.governor import PortfolioGovernor

logger = logging.getLogger(__name__)

# Consecutive failures before a blip is treated as a broken rail (M56b).
# The broker closing a connection mid-request is ordinary and the next sweep
# five minutes later fixes it; the sweep still stopping an hour later is not.
# Logging both at ERROR made them indistinguishable to anything counting
# errors, and the noisy case is by far the common one.
_FAILURES_BEFORE_ERROR = 3


class DeleverSweep:
    """Engine (per domain.orchestrator.Engine protocol)."""

    name = "delever-sweep"

    def __init__(
        self,
        oms: OMS,
        governor: PortfolioGovernor,
        settings: Settings | None = None,
        bus: EventBus | None = None,
        poll_seconds: float = 300.0,
    ) -> None:
        self.oms = oms
        self.governor = governor
        self.settings = settings or Settings()
        self.bus = bus
        self.poll_seconds = poll_seconds
        self.last_fraction = 0.0
        self._consecutive_failures = 0
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
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
            await self._attempt_sweep()

    async def _attempt_sweep(self) -> None:
        """One attempt, plus the bookkeeping that decides how loudly a failure
        is reported.

        Split out from `_run` so that the streak logic can be driven directly
        rather than through a sleep loop. Testing the two `_note_*` calls in
        isolation would leave the wiring between them - which resets the streak
        and when - unexercised, and that wiring is where this kind of defect
        actually lives.
        """
        try:
            await self.poll()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - one bad sweep must not end the rail
            self._note_failed_sweep(exc)
        else:
            self._consecutive_failures = 0

    def _note_failed_sweep(self, exc: BaseException) -> None:
        """One failed sweep, logged at a level that reflects what it means.

        The cause is named either way - a warning that does not say what broke
        is no better than silence. Only the traceback waits for the escalation,
        because that is the point at which someone has to read it.
        """
        self._consecutive_failures += 1
        if self._consecutive_failures < _FAILURES_BEFORE_ERROR:
            logger.warning(
                "Delever sweep failed (%d in a row); the next sweep retries: %r",
                self._consecutive_failures,
                exc,
            )
        elif self._consecutive_failures == _FAILURES_BEFORE_ERROR:
            # Once, at the crossing. Escalating on every subsequent failure
            # would turn a persistent outage back into the flood this exists
            # to stop.
            logger.error(
                "Delever sweep has failed %d times in a row - the rail is not running",
                self._consecutive_failures,
                exc_info=exc,
            )

    async def poll(self) -> list[str]:
        """One sweep. Returns the symbols an exit order was raised for.

        Reports the breach whether or not trimming is enabled, so "we are over
        cap and doing nothing about it" is a visible state rather than silence.
        """
        positions = await self.oms.broker.positions()
        if not positions:
            return []

        account = await self.oms.broker.account()
        equity = float(account.net_liquidation)
        fraction = self.governor.delever_fraction(positions, self.oms.position_stops(), equity)
        self.last_fraction = fraction

        if fraction <= 0:
            return []

        snap = self.governor.snapshot(positions, self.oms.position_stops(), equity)
        logger.warning(
            "Aggregate risk-at-stop %.2f%% is over the %.2f%% cap - %s",
            snap.risk_at_stop_pct * 100,
            self.settings.max_aggregate_risk_at_stop_pct * 100,
            (
                f"trimming every position by {fraction:.1%}"
                if self.settings.delever_sweep_enabled
                # "will only unwind as positions close" was false, and
                # measurably so (M82). The figure is risk / EQUITY, so it moves
                # whenever either does: overnight on 10 August it changed ten
                # times across 5.11-5.14% while every one of eleven positions
                # stayed open and closed_trades.csv was untouched. It also
                # moved the WRONG way - 5.12% to 5.14% as equity fell from
                # $102,161 to $101,798 - so the old wording implied a figure
                # that sits still until you act, when it drifts against you as
                # the book loses value.
                else (
                    "sweep is disabled, so nothing will be sold to correct it. It falls as "
                    "positions close or as equity rises, and rises as equity falls"
                )
            ),
        )
        if not self.settings.delever_sweep_enabled:
            return []

        trimmed: list[str] = []
        for pos in positions:
            held = abs(pos.quantity)
            # Floor, not round: trimming slightly less than the target is a
            # smaller error than selling more of a position than intended.
            quantity = math.floor(held * fraction)
            if quantity <= 0:
                continue
            try:
                # Through submit_exit_order, so the trim is an ordinary order
                # subject to the same sign-off gate as everything else. In
                # recommend mode a human still approves it; the sweep decides
                # what to trim, never whether it transmits.
                await self.oms.submit_exit_order(
                    pos.symbol,
                    quantity=float(quantity),
                    price=pos.avg_price,
                    reason="delever",
                )
                trimmed.append(pos.symbol)
            except Exception:  # noqa: BLE001 - one symbol must not abort the sweep
                logger.exception("Could not raise a delever trim for %s", pos.symbol)
        return trimmed

"""Ties the trading session to market hours (spec M19).

Up to M18 the market data feed and the strategy engine ran around the clock.
On synthetic prices that was harmless. Once M14-M18 made the prices real it
became two concrete faults:

  * The feed kept polling a rate-limited vendor all night for a price that
    stopped moving at the close, and the strategy engine kept building
    snapshots and emitting signals from it. Signals produced at 3am on the
    previous day's closing price are not analysis.
  * Worse, the staleness detector fires when a symbol stops updating for
    longer than data_staleness_seconds - sixty seconds by default. A closed
    market means every symbol goes stale within a minute of the close, so the
    kill-switch tripped every single night, and the operator arrived to a
    tripped rail with nothing wrong.

The controller decides only WHEN THE APPLICATION IS AWAKE. It never decides
who approves an order: execution mode, the risk engine, the cash rule and the
sign-off gate are untouched and behave exactly as configured. Standing the
session up does not place a trade.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable
from datetime import datetime
from typing import Protocol

from qat.domain import market_calendar as mc

logger = logging.getLogger(__name__)

DEFAULT_POLL_SECONDS = 20.0


class FeedLike(Protocol):
    """The slice of MarketDataFeed the controller drives."""

    async def start(self) -> None: ...
    async def stop(self) -> None: ...


class EmitterLike(Protocol):
    """The slice of StrategyEngine the controller gates.

    A plain flag rather than start/stop: the engine must keep ingesting ticks
    into its bar history even while suspended, or the first signal after an
    open would be computed against an empty buffer.
    """

    emitting: bool


class SessionController:
    """Engine (per domain.orchestrator.Engine protocol)."""

    name = "session-controller"

    def __init__(
        self,
        feed: FeedLike,
        strategy_engine: EmitterLike,
        market: mc.Market = "US",
        *,
        enabled: bool = True,
        poll_seconds: float = DEFAULT_POLL_SECONDS,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.feed = feed
        self.strategy_engine = strategy_engine
        self.market = market
        self.enabled = enabled
        self.poll_seconds = poll_seconds
        self.clock = clock
        # The orchestrator starts the feed before this engine runs, so the
        # session begins life active and the first check stands it down if the
        # market is shut.
        self.active = True
        self.override_until_close = False
        self._task: asyncio.Task[None] | None = None
        # Whether the last `apply_once` changed the session state.
        self._transitioned = False

    # --- lifecycle ----------------------------------------------------------

    async def start(self) -> None:
        if not self.enabled:
            logger.info(
                "Session control is off: the feed and strategy engine run continuously. "
                "This is the default on simulated prices, which have no trading hours."
            )
            return
        await self.apply_once()
        if not self._transitioned and self.active:
            # Constructed `active = True` because the orchestrator starts the
            # feed before this engine runs. So on an OPEN market the first
            # check finds `desired == self.active`, changes nothing, and used
            # to log NOTHING - a session in the healthy state said nothing at
            # all (M108).
            #
            # Every tool that anchors on "Trading session started" then fell
            # back to the PREVIOUS run. On 20 August `session_check` reported
            # the 09:49 session's start time, its 1,056 errors and its adopted
            # Alpaca positions against a session that had begun at 11:12 -
            # three wrong answers from one missing line, in the instrument an
            # operator relies on overnight.
            #
            # Silence is not a state. A session announces itself whether it
            # transitioned into that state or was born in it.
            self._announce_active(self.session())
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
                await self.apply_once()
            except Exception:  # noqa: BLE001 - a bad check must not end the loop
                logger.exception("Session check failed; the session is left as it is")

    # --- decision -----------------------------------------------------------

    def session(self) -> mc.MarketSession:
        return mc.session_for(self.market, self.clock() if self.clock else None)

    def should_be_active(self) -> bool:
        if not self.enabled:
            return True
        session = self.session()
        if session.is_open:
            return True
        # A manual override lasts until the next close and no longer. It exists
        # so a closed market never leaves the operator unable to work, not as a
        # way to run unattended around the clock by accident.
        return self.override_until_close

    async def apply_once(self) -> bool:
        """Bring the session into line with the calendar. Returns is-active."""
        session = self.session()
        if self.override_until_close and session.is_open:
            # The market it was overriding for has opened; the override has
            # done its job and is retired rather than left latent.
            self.override_until_close = False

        desired = self.should_be_active()
        # Recorded rather than returned: the return value is documented as
        # is-active and callers rely on it, so "did this pass change anything"
        # gets its own attribute instead of quietly redefining the contract.
        self._transitioned = desired != self.active
        if self._transitioned:
            await self._set_active(desired, session)
        return self.active

    def _announce_active(self, session: mc.MarketSession) -> None:
        """Say HOW the session is running. Shared by the transition and by a
        session that was born active, so both produce the same line and no
        reader has to know which happened."""
        if self.override_until_close:
            logger.warning(
                "Trading session started by OPERATOR OVERRIDE - %s is NOT open. Signals "
                "are being generated against whatever last traded, and the staleness rail "
                "is now live on a closed market, so symbols will be excluded until they "
                "print again. The override lapses at the close.",
                self.market,
            )
        else:
            logger.info("Trading session started - %s is open", self.market)

    async def _set_active(self, active: bool, session: mc.MarketSession) -> None:
        if active:
            await self.feed.start()
            self.strategy_engine.emitting = True
            # Says HOW the session started rather than asserting the market is
            # open (M52). On 6 August these two lines were logged in the same
            # second: "force-started by operator (dashboard) while US is closed"
            # and "Trading session started - US is open". The second contradicted
            # the first, and the watcher surfaced only the second, so the
            # operator was told the market was open eight minutes before it was.
            #
            # A forced start also disarms something the stood-down message
            # promises - "the staleness rail cannot trip on a market that is
            # simply shut" - and it produced 94 exclusions in six seconds
            # against a market that had been closed for seventeen hours. Whoever
            # forces it should be told what they have just turned on.
            self._announce_active(session)
        else:
            await self.feed.stop()
            self.strategy_engine.emitting = False
            logger.info(
                "Trading session stood down - %s is %s. The feed is idle, no signals are "
                "emitted, and the staleness rail cannot trip on a market that is simply shut.",
                self.market,
                session.closed_reason or "closed",
            )
        self.active = active

    # --- manual override ----------------------------------------------------

    async def force_start(self, operator: str = "operator") -> None:
        """Run the session against a closed market, until the next close.

        Deliberately not permanent. The operator gets to work now; the app does
        not quietly acquire a standing exemption from its own schedule.
        """
        self.override_until_close = True
        logger.info("Trading session force-started by %s while %s is closed", operator, self.market)
        await self.apply_once()

    async def clear_override(self) -> None:
        self.override_until_close = False
        await self.apply_once()

    # --- display ------------------------------------------------------------

    def status_line(self) -> str:
        if not self.enabled:
            return "Session: always on (simulated prices have no trading hours)"
        if self.active and self.override_until_close:
            return f"Session: ACTIVE (manually started while {self.market} is closed)"
        if self.active:
            return f"Session: ACTIVE - {self.market} is open"
        return f"Session: standing by - {self.market} is {self.session().closed_reason or 'closed'}"

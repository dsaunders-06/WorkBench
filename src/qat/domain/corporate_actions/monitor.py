"""The corporate-action monitor: query, detect, assess, and sometimes place (M39).

The public face of this subsystem and the only part that touches the broker.
`pending_action` is the single source of truth every screen and the decision
path read, which is what makes the state impossible to lose on one screen while
another shows it (R1) and available to autonomous sizing (R2).

Shadow is the default mode. In shadow everything runs and the adjustment is
logged rather than placed, so the detector's judgement can be watched against
real announcements - including the CRWD false positive already in the book -
without spending a position slot or any risk budget.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta

from qat.config import Settings
from qat.data.broker.adapter import RestingStopOrder
from qat.domain import market_calendar as mc
from qat.domain.corporate_actions.adjuster import StopAdjuster
from qat.domain.corporate_actions.announcements import AnnouncementStore
from qat.domain.corporate_actions.detector import PendingAction, SplitDetector
from qat.domain.oms.anomaly import PositionAnomalyStore

logger = logging.getLogger(__name__)

DECLARED_BY = "corporate-action-monitor"

# How far either side of today to ask about. Backwards a little because an
# ex-date that has just passed still leaves a stale stop needing adjustment;
# forwards far enough that a split is known about well before it lands.
_LOOKBACK_DAYS = 5
_LOOKAHEAD_DAYS = 45


class CorporateActionMonitor:
    def __init__(
        self,
        oms: object,
        settings: Settings,
        entries_source: Callable[[], dict[str, datetime]],
        anomalies: PositionAnomalyStore | None = None,
        store: AnnouncementStore | None = None,
        next_session: Callable[[], date | None] | None = None,
    ) -> None:
        self.oms = oms
        self.settings = settings
        # A callable rather than a reference to the bridge, so this subsystem
        # does not reach into another one's private state to learn open dates.
        self.entries_source = entries_source
        self.anomalies = anomalies or getattr(oms, "anomalies", None) or PositionAnomalyStore(None)
        self.store = store or AnnouncementStore(settings.data_dir)
        self.detector = SplitDetector(self.store)
        self.adjuster = StopAdjuster(settings.corporate_action_mode)
        # Injectable so a test pins the session rather than passing or failing
        # by the date the suite happens to run.
        self.next_session = next_session or self._next_session_date
        self._pending: dict[str, PendingAction] = {}
        self._task: asyncio.Task[None] | None = None

    # --- the public face ------------------------------------------------------

    def pending_action(self, symbol: str) -> PendingAction | None:
        """The single source of truth. Every screen and the decision path read
        this rather than keeping their own copy."""
        return self._pending.get(symbol)

    def pending_actions(self) -> list[PendingAction]:
        return sorted(self._pending.values(), key=lambda a: (a.ex_date, a.symbol))

    # --- the engine -----------------------------------------------------------

    async def start(self) -> None:
        await self.refresh()
        self._task = asyncio.create_task(self._sweep())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None

    async def _sweep(self) -> None:
        """Same cadence as the protection sweep, for the same reason: a split
        landing at 14:00 is not less urgent than one found at launch."""
        while True:
            await asyncio.sleep(self.settings.protection_sweep_seconds)
            try:
                await self.refresh()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - one bad sweep must not end the rail
                logger.exception("Corporate-action sweep failed; continuing")

    async def refresh(self) -> list[PendingAction]:
        """One full pass. Safe to call repeatedly."""
        broker = self.oms.broker  # type: ignore[attr-defined]
        try:
            positions = await broker.positions()
            stops = await broker.resting_stop_orders()
        except Exception:
            logger.exception("Could not read the book to check for corporate actions")
            return []

        held = [p for p in positions if abs(float(p.quantity)) > 0]
        await self._fetch(broker, [str(p.symbol) for p in held])

        session = self.next_session()
        if session is None:
            # `next_open` finds no trading day within its search window. Guessing
            # a session date would move a stop on the wrong day.
            logger.warning(
                "Cannot determine the next trading session, so no corporate action is acted "
                "on this pass. Any pending split stays pending."
            )
            self._pending = {}
            return []

        found = self.detector.pending(
            positions=held,
            stops={symbol: order.stop_price for symbol, order in stops.items()},
            opened_at=self.entries_source(),
            next_session=session,
        )

        assessed: dict[str, PendingAction] = {}
        for action in found:
            price = await self._price(broker, action.symbol)
            basis = next(
                (float(p.avg_price) for p in held if p.symbol == action.symbol),
                0.0,
            )
            judged = self.adjuster.assess(action, price=price, pre_action_price=basis)
            if judged.state == "refused":
                self._quarantine(judged, held)
            elif judged.state == "applied":
                await self._place(broker, judged, stops)
            else:
                logger.warning(
                    "SHADOW: %s would have its resting stop moved from %.2f to %.2f. Nothing "
                    "was placed - set QAT_CORPORATE_ACTION_MODE=act to let this happen.",
                    judged.describe(),
                    judged.current_stop or 0.0,
                    judged.adjusted_stop or 0.0,
                )
            assessed[judged.symbol] = judged

        self._pending = assessed
        return self.pending_actions()

    # --- the pieces -----------------------------------------------------------

    async def _fetch(self, broker: object, symbols: list[str]) -> None:
        """Ask per symbol, and let the persisted store cover a failure.

        The morning the endpoint fails is the morning it matters, so an
        exception here is logged and swallowed rather than allowed to end the
        pass - whatever was remembered on an earlier pass still applies.
        """
        today = datetime.now(UTC).date()
        since = today - timedelta(days=_LOOKBACK_DAYS)
        until = today + timedelta(days=_LOOKAHEAD_DAYS)
        for symbol in symbols:
            try:
                found = await broker.announcements(symbol, since, until)  # type: ignore[attr-defined]
            except Exception as exc:  # noqa: BLE001 - the store is the fallback
                logger.warning(
                    "Could not read corporate announcements for %s (%s: %s) - falling back to "
                    "what was persisted, which may be nothing at all",
                    symbol,
                    type(exc).__name__,
                    exc,
                )
                continue
            for announcement in self.store.remember(found):
                logger.warning(
                    "CORPORATE ACTION first seen: %s ratio %g. A held position's resting stop "
                    "is priced for the pre-action share count.",
                    f"{announcement.symbol} ex-date {announcement.ex_date}",
                    announcement.ratio,
                )

    async def _price(self, broker: object, symbol: str) -> float:
        try:
            quote = await broker.get_market_data(symbol)  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001 - a missing price refuses, it does not crash
            logger.warning("No price for %s, so its adjustment cannot be judged", symbol)
            return 0.0
        for key in ("last", "close", "price", "bid"):
            value = quote.get(key) if isinstance(quote, dict) else None
            if value:
                return float(value)
        return 0.0

    def _quarantine(self, action: PendingAction, held: list[object]) -> None:
        """A refused adjustment leaves a stop that is itself dangerous, so the
        position stops being treated as ordinary."""
        if self.anomalies.is_quarantined(action.symbol):
            return
        quantity = next(
            (float(p.quantity) for p in held if p.symbol == action.symbol),  # type: ignore[attr-defined]
            0.0,
        )
        self.anomalies.declare(
            symbol=action.symbol,
            reason=f"{action.describe()} - adjustment refused: {action.refusal}",
            declared_by=DECLARED_BY,
            tracked_quantity=quantity,
            broker_quantity=quantity,
        )

    async def _place(
        self, broker: object, action: PendingAction, stops: dict[str, RestingStopOrder]
    ) -> None:
        resting = stops.get(action.symbol)
        if resting is None or action.adjusted_stop is None:
            return
        try:
            await broker.modify_order(  # type: ignore[attr-defined]
                resting.order_id, stop_price=action.adjusted_stop
            )
        except Exception:
            logger.exception(
                "Could not re-price the resting stop on %s. It is still at %.2f, which is the "
                "level that liquidated MNST - this needs a human.",
                action.symbol,
                action.current_stop or 0.0,
            )
            return
        logger.warning(
            "ADJUSTED: %s resting stop moved from %.2f to %.2f ahead of the action.",
            action.describe(),
            action.current_stop or 0.0,
            action.adjusted_stop,
        )

    def _next_session_date(self) -> date | None:
        opens = mc.next_open(self.settings.market)
        return opens.date() if opens is not None else None

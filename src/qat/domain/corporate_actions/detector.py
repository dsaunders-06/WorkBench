"""Which held positions have a split coming, and which do not (M39).

Four gates. The first is the whole reason M60 deferred automatic detection:

**CRWD split 4-for-1 with ex-date 2 July, and we bought 16 on 31 July.** The
position is already sized post-split and its resting OCO is correct. A detector
matching on symbol and ratio over a recent window flags it, divides a correct
stop by four, and liquidates the position at the next open. That false positive
is in the live book.

So every candidate must have an `ex_date` strictly after the position was
opened, and a position whose open date is unknown is skipped rather than guessed
at - applying no gate is exactly how CRWD gets adjusted wrongly.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime

from qat.data.broker.adapter import Position
from qat.domain.corporate_actions.announcements import Announcement, AnnouncementStore

logger = logging.getLogger(__name__)

# Wide on purpose. A real 1-for-1000 reverse split is ratio 0.001, and the
# ROADMAP records `old_rate=1000.0, new_rate=1.0` as an observed shape - an
# earlier draft of this bounded the ratio at 0.01 and would have refused it.
MIN_RATIO = 1e-4
MAX_RATIO = 1e4


@dataclass(frozen=True, slots=True)
class PendingAction:
    """A corporate action bearing on a position this account holds.

    Carries the position's open date because that is what the CRWD gate was
    decided on, and a reader asking "why is this flagged" needs to see it.
    """

    announcement: Announcement
    position_opened_at: datetime
    current_stop: float | None
    adjusted_stop: float | None = None
    state: str = "pending"
    refusal: str | None = None

    @property
    def symbol(self) -> str:
        return self.announcement.symbol

    @property
    def ratio(self) -> float:
        return self.announcement.ratio

    @property
    def ex_date(self) -> date:
        return self.announcement.ex_date

    def describe(self) -> str:
        """One line an operator can read on any screen (R1).

        Lives here rather than in a widget so every reader says the same thing -
        the same reason `refusals.rail_of` exists.
        """
        shape = f"{self.ratio:g}-for-1" if self.ratio >= 1 else f"1-for-{1 / self.ratio:g}"
        return f"{self.symbol} {shape} split, ex-date {self.ex_date}"


class SplitDetector:
    def __init__(self, store: AnnouncementStore) -> None:
        self.store = store

    def pending(
        self,
        positions: list[Position],
        stops: dict[str, float],
        opened_at: dict[str, datetime],
        next_session: date,
    ) -> list[PendingAction]:
        """Actions worth adjusting for, given what is held right now.

        `next_session` is the date of the next market open, from
        `market_calendar.next_open`. Passed in rather than computed here so this
        stays a pure function of its inputs and can be tested without a clock.
        """
        found: list[PendingAction] = []
        for position in positions:
            if abs(position.quantity) <= 0:
                continue
            symbol = position.symbol
            stop = stops.get(symbol)
            if stop is None:
                continue  # nothing resting, so nothing to adjust
            opened = opened_at.get(symbol)
            if opened is None:
                logger.debug(
                    "No recorded open date for %s, so the ex-date gate cannot be applied - "
                    "skipped rather than guessed at",
                    symbol,
                )
                continue
            for announcement in self.store.for_symbol(symbol):
                if not self._is_actionable(announcement, opened, next_session):
                    continue
                found.append(
                    PendingAction(
                        announcement=announcement,
                        position_opened_at=opened,
                        current_stop=stop,
                    )
                )
        return found

    def _is_actionable(
        self, announcement: Announcement, opened: datetime, next_session: date
    ) -> bool:
        if announcement.ex_date <= opened.date():
            # The CRWD gate. Strict, not inclusive: a position bought ON the
            # ex-date is already post-split.
            return False
        if announcement.ex_date > next_session:
            return False  # not yet - a split in October does not move a stop in August
        ratio = announcement.ratio
        if ratio == 1.0 or not (MIN_RATIO < ratio < MAX_RATIO):
            logger.warning(
                "Ignoring the %s announcement for %s: ratio %g is outside the plausible range "
                "%g to %g, so it is bad data rather than a split. Nothing is adjusted.",
                announcement.ex_date,
                announcement.symbol,
                ratio,
                MIN_RATIO,
                MAX_RATIO,
            )
            return False
        return True

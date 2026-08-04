"""Market session panel for the Dashboard (spec M19).

Answers three questions the app could not previously answer at a glance: which
market is in play, how long until it opens or closes, and whether the trading
session is actually running.

The countdown is pure presentation - it reads the calendar and formats it. The
decision to stand a session up or down belongs to SessionController, so the
panel can never disagree with the engine about whether trading is live: it
reports the controller's own state rather than re-deriving it.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from qat.domain import market_calendar as mc
from qat.domain.session_controller import SessionController
from qat.presentation import theme

logger = logging.getLogger(__name__)

# The alert window you asked for: inside this many seconds of an open or a
# close, the countdown turns amber.
ALERT_SECONDS = 30 * 60

_OPEN_COLOUR = theme.SUCCESS
_CLOSED_COLOUR = theme.MUTED
_ALERT_COLOUR = theme.WARNING

# An open market is the single most consequential fact on the Dashboard, so it
# is a filled banner rather than coloured text (M20). Closed stays deliberately
# flat: making every state shout is the same as making none of them.
_BANNER_STYLE = (
    "background-color: {fill}; color: white; padding: 8px; "
    "border-radius: 4px; font-size: 18px; font-weight: bold;"
)
_QUIET_STYLE = "color: {fill}; padding: 8px; font-size: 15px; font-weight: bold;"


@dataclass(frozen=True, slots=True)
class Countdown:
    """What the panel needs to render one market, already decided."""

    market: str
    is_open: bool
    headline: str
    detail: str
    seconds_remaining: float | None
    alerting: bool

    @property
    def colour(self) -> str:
        if self.alerting:
            return _ALERT_COLOUR
        return _OPEN_COLOUR if self.is_open else _CLOSED_COLOUR

    @property
    def banner_style(self) -> str:
        """Filled while the market is open or an open/close is imminent;
        plain text otherwise."""
        if self.is_open or self.alerting:
            return _BANNER_STYLE.format(fill=self.colour)
        return _QUIET_STYLE.format(fill=self.colour)


def format_duration(seconds: float) -> str:
    """HH:MM:SS, clamped at zero.

    Never negative: a countdown that has just passed its target reads as
    00:00:00 while the next poll catches up, rather than flashing a negative
    time that looks like a fault.
    """
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def countdown_for(market: mc.Market, now: datetime | None = None) -> Countdown:
    session = mc.session_for(market, now)
    local = session.local_time

    if session.is_open and session.closes_at is not None:
        remaining = (session.closes_at - local).total_seconds()
        early = " (early close)" if session.is_early_close else ""
        return Countdown(
            market=market,
            is_open=True,
            headline=f"{market} OPEN",
            detail=f"closes in {format_duration(remaining)}{early}",
            seconds_remaining=remaining,
            alerting=remaining <= ALERT_SECONDS,
        )

    opens_at = session.opens_at if session.opens_at and session.opens_at > local else None
    if opens_at is None:
        opens_at = mc.next_open(market, local)

    if opens_at is None:
        # The calendar found no trading day within its search window. Saying so
        # is better than rendering a countdown to a time nobody computed.
        return Countdown(
            market=market,
            is_open=False,
            headline=f"{market} closed",
            detail=session.closed_reason or "no scheduled open found",
            seconds_remaining=None,
            alerting=False,
        )

    remaining = (opens_at - local).total_seconds()
    reason = session.closed_reason or "closed"
    # "before open" and "after close" are mechanics, not news; a holiday is.
    note = "" if reason in ("before open", "after close") else f" - {reason}"
    return Countdown(
        market=market,
        is_open=False,
        headline=f"{market} closed{note}",
        detail=f"opens in {format_duration(remaining)} ({opens_at:%a %H:%M})",
        seconds_remaining=remaining,
        alerting=remaining <= ALERT_SECONDS,
    )


class SessionPanel(QFrame):
    """Session state and countdowns for the configured market, plus any other
    market currently trading."""

    def __init__(
        self,
        controller: SessionController,
        market: mc.Market = "US",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.controller = controller
        self.market = market

        self.setFrameShape(QFrame.Shape.StyledPanel)
        # Scoped by object name: an unscoped "QFrame { border... }" is inherited
        # by every child, which drew a box around each individual label.
        self.setObjectName("sessionPanel")
        self.setStyleSheet(
            "QFrame#sessionPanel { border: 1px solid #444; border-radius: 4px; padding: 6px; }"
        )

        layout = QVBoxLayout(self)
        grid = QGridLayout()

        self.headline = QLabel("-")
        self.headline.setStyleSheet("font-size: 15px; font-weight: bold;")
        self.detail = QLabel("-")
        self.detail.setStyleSheet("font-size: 13px;")
        grid.addWidget(self.headline, 0, 0)
        grid.addWidget(self.detail, 0, 1)

        # The other market only earns a line when it is actually trading -
        # a permanent "ASX closed" row is noise to a US-configured operator.
        self.other_market = QLabel("")
        self.other_market.setStyleSheet(
            f"color: {_OPEN_COLOUR}; font-size: 13px; font-weight: bold;"
        )
        grid.addWidget(self.other_market, 1, 0, 1, 2)
        layout.addLayout(grid)

        status_row = QHBoxLayout()
        self.session_status = QLabel("-")
        self.session_status.setWordWrap(True)
        self.start_button = QPushButton("Start session now")
        self.start_button.setToolTip(
            "Run the session against a closed market, until the next close.\n"
            "This starts the data feed and lets strategies emit signals. It does not "
            "place any order, and does not change who signs orders off."
        )
        self.start_button.clicked.connect(self._on_start_clicked)
        status_row.addWidget(self.session_status, stretch=1)
        status_row.addWidget(self.start_button)
        layout.addLayout(status_row)

        self.refresh()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(1000)  # a countdown that ticks in seconds must tick

    def _on_start_clicked(self) -> None:
        asyncio.ensure_future(self._force_start())

    async def _force_start(self) -> None:
        try:
            await self.controller.force_start("operator (dashboard)")
        except Exception as exc:  # noqa: BLE001 - surfaced rather than swallowed
            logger.exception("Could not force-start the trading session")
            self.session_status.setText(f"Could not start the session: {exc}")
            return
        self.refresh()

    def refresh(self, now: datetime | None = None) -> None:
        countdown = countdown_for(self.market, now)
        self.headline.setText(countdown.headline)
        self.headline.setStyleSheet(countdown.banner_style)
        self.detail.setText(countdown.detail)
        self.detail.setStyleSheet(
            f"font-size: 15px; font-weight: bold; color: {countdown.colour};"
            if countdown.is_open or countdown.alerting
            else f"font-size: 13px; color: {countdown.colour};"
        )

        other: mc.Market = "ASX" if self.market == "US" else "US"
        other_countdown = countdown_for(other, now)
        self.other_market.setText(
            f"{other_countdown.headline} - {other_countdown.detail}"
            if other_countdown.is_open
            else ""
        )
        self.other_market.setVisible(other_countdown.is_open)

        self.session_status.setText(self.controller.status_line())
        # Only offer the override when it would do something.
        self.start_button.setVisible(
            self.controller.enabled and not self.controller.active and not countdown.is_open
        )

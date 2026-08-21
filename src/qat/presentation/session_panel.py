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

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
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
    "background-color: {fill}; color: " + theme.WHITE + "; padding: 8px; "
    "border-radius: 4px; " + theme.text(size=theme.TITLE, bold=True)
)
_QUIET_STYLE = "color: {fill}; padding: 8px; " + theme.text(size=theme.SUBHEAD, bold=True)


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


# The button is only ever VISIBLE when the market is CLOSED (see `refresh`),
# so its only possible action is `force_start` - which arms an override until
# the next close and disarms the promise that the staleness rail cannot trip on
# a market that is simply shut.
#
# It read "Start session now". On 20 August the operator clicked it eleven
# minutes before the ASX open, reasonably, and later said they had not
# overridden anything - and both were true, because the log recorded an
# override and the label had never mentioned one. The tooltip did, and a
# tooltip is only read by somebody already suspicious. A control names what it
# DOES (M106).
START_BUTTON_LABEL = "Force-start (market closed)"

# NoFocus, because `QPushButton.clicked` fires on SPACE or ENTER when the button
# has keyboard focus - not only on a mouse click. With the default policy this
# is the only focusable widget in the panel, so a freshly-shown window can hand
# it focus at launch and a stray keystroke arms a session override.
#
# On 20 August the log recorded "force-started by operator (dashboard)" eleven
# minutes before the ASX open and the operator said, correctly, that they had
# not clicked it. Both are consistent: the handler ran, and "operator
# (dashboard)" is the only string that path can log - so the application
# attributed to a PERSON an action a keypress could have caused.
#
# A control that runs the session against a closed market, and disarms the
# promise that the staleness rail cannot trip on a market that is simply shut,
# should require a deliberate pointer action (M107).
START_BUTTON_FOCUS_POLICY = Qt.FocusPolicy.NoFocus

# What gets logged as the SOURCE of a force-start. It used to be
# "operator (dashboard)", which asserts that a PERSON acted - and this code
# path cannot know that: `clicked` fires from a mouse click or from a keypress,
# and the string is a constant passed either way. On 20 August that assertion
# was read back to the operator as evidence of what they had done, and it was
# wrong. Name the control, because the control is what is actually known.
FORCE_START_SOURCE = "the dashboard force-start control"

# M124. M107 removed the ACCIDENTAL path - the button is NoFocus, so a keystroke
# cannot reach it - but a deliberate click was still instant, and on 20 August a
# force-start produced six signals against stale closing prices on a shut
# market. This puts a second deliberate act between the click and the override.
#
# THE DEFAULT IS THE WHOLE POINT. Escape, Enter, and closing the dialog must all
# mean NO. A confirmation that defaults to yes is one keystroke away from no
# confirmation at all, which is precisely what M107 just took away - it would
# reintroduce the defect through the control added to prevent it.
FORCE_START_CONFIRM_TITLE = "Force-start the session?"
FORCE_START_CONFIRM_TEXT = "Run the trading session against a CLOSED market?"
FORCE_START_CONFIRM_DETAIL = (
    "The feed will start and strategies will emit signals against the last "
    "prices seen, which on a shut market are stale closing prices. On "
    "20 August this produced six signals in that state.\n\n"
    "The override lasts until the next close. It places no order by itself and "
    "does not change who signs orders off."
)
FORCE_START_CONFIRM_ACCEPT = "Force-start"
FORCE_START_CONFIRM_REJECT = "Cancel"


def build_force_start_dialog(parent: QWidget | None = None) -> tuple[QMessageBox, QPushButton]:
    """The confirmation, and the one button that means yes.

    Split from `confirm_force_start` so the DEFAULTING can be asserted without
    running a modal loop. The safe-default behaviour is the requirement here;
    testing only the yes/no outcome would leave it uncovered.
    """
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Warning)
    box.setWindowTitle(FORCE_START_CONFIRM_TITLE)
    box.setText(FORCE_START_CONFIRM_TEXT)
    box.setInformativeText(FORCE_START_CONFIRM_DETAIL)
    reject = box.addButton(FORCE_START_CONFIRM_REJECT, QMessageBox.ButtonRole.RejectRole)
    accept = box.addButton(FORCE_START_CONFIRM_ACCEPT, QMessageBox.ButtonRole.AcceptRole)
    box.setDefaultButton(reject)
    box.setEscapeButton(reject)
    return box, accept


def confirm_force_start(parent: QWidget | None = None) -> bool:
    """True only on an explicit affirmative.

    Anything else - Cancel, Escape, Enter, or closing the window - is a no.
    `clickedButton()` is None when the dialog is dismissed without a button,
    and `None is accept` is False, so that path is safe by construction rather
    than by a branch someone has to remember.
    """
    box, accept = build_force_start_dialog(parent)
    box.exec()
    return box.clickedButton() is accept


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
        self.setStyleSheet(theme.panel("sessionPanel"))

        layout = QVBoxLayout(self)
        grid = QGridLayout()

        self.headline = QLabel("-")
        self.headline.setStyleSheet(theme.text(size=theme.SUBHEAD, bold=True))
        self.detail = QLabel("-")
        self.detail.setStyleSheet(theme.text(size=theme.BODY))
        grid.addWidget(self.headline, 0, 0)
        grid.addWidget(self.detail, 0, 1)

        # The other market only earns a line when it is actually trading -
        # a permanent "ASX closed" row is noise to a US-configured operator.
        self.other_market = QLabel("")
        self.other_market.setStyleSheet(theme.text(_OPEN_COLOUR, size=theme.BODY, bold=True))
        grid.addWidget(self.other_market, 1, 0, 1, 2)
        layout.addLayout(grid)

        status_row = QHBoxLayout()
        self.session_status = QLabel("-")
        self.session_status.setWordWrap(True)
        self.start_button = QPushButton(START_BUTTON_LABEL)
        self.start_button.setToolTip(
            "Run the session against a closed market, until the next close.\n"
            "This starts the data feed and lets strategies emit signals. It does not "
            "place any order, and does not change who signs orders off."
        )
        self.start_button.setFocusPolicy(START_BUTTON_FOCUS_POLICY)
        # An attribute rather than a bare call, so a test can answer the dialog
        # without running a modal loop (M124).
        self.confirm_force_start = confirm_force_start
        self.start_button.clicked.connect(self._on_start_clicked)
        status_row.addWidget(self.session_status, stretch=1)
        status_row.addWidget(self.start_button)
        layout.addLayout(status_row)

        self.refresh()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(1000)  # a countdown that ticks in seconds must tick

    def _on_start_clicked(self) -> None:
        # M124. The decline is logged as well as the accept. A log that only
        # records overrides that happened cannot answer "was this offered and
        # refused", and on 20 August the question asked afterwards was exactly
        # what the operator had and had not done.
        if not self.confirm_force_start(self):
            logger.info(
                "Force-start was offered and DECLINED - the session remains stood "
                "down and no override is armed"
            )
            return
        logger.info("Force-start CONFIRMED at the dialog - arming the override")
        asyncio.ensure_future(self._force_start())

    async def _force_start(self) -> None:
        try:
            await self.controller.force_start(FORCE_START_SOURCE)
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
        loud = countdown.is_open or countdown.alerting
        self.detail.setStyleSheet(
            theme.text(countdown.colour, size=theme.SUBHEAD, bold=True)
            if loud
            else theme.text(countdown.colour, size=theme.BODY)
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

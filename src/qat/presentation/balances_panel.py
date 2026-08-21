"""Account balances on the Dashboard, laid out like the broker's own page
(spec M21).

Two rules govern what this shows.

Nothing is recomputed that the broker already reports. The day's profit is
Alpaca's equity against its own last_equity, not a figure derived here - when
two screens disagree about money the operator has to work out which one is
lying, and that is a worse position than having one number with a caveat.

A figure the broker did not report renders as a dash, never as zero — "0 day
trades" is a different claim from "not reported".

That rule is right and it is not a licence to show a field no broker will ever
fill. On 21 August the day-trade count, both margin figures and short market
value were removed from the panel, because on IBKR all four rendered a dash
every session and two of them would be meaningless even filled: this
application is long-only, and the day-trade count belongs to a US rule that
does not reach an ASX account. A permanent dash teaches an operator to stop
reading the row, which costs the rule its force where it genuinely applies.

The one figure here that is NOT the broker's is spendable cash, and it is the
most important one on the panel. Alpaca will offer four times your cash as
buying power; this application refuses anything above cash less the reserve.
Seeing $365,162 of buying power next to an order rejected for insufficient
cash is the single most confusing thing about running the two side by side.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QLabel,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from qat.data.broker.account_poller import AccountSnapshot
from qat.data.broker.adapter import AccountBalances
from qat.presentation import theme
from qat.presentation.ui_level import UiLevel

logger = logging.getLogger(__name__)

NOT_REPORTED = "—"
_POSITIVE = theme.SUCCESS
_NEGATIVE = theme.DANGER
_MUTED = theme.MUTED
_WARNING = theme.WARNING


def money(value: float | None, currency: str | None = None) -> str:
    if value is None:
        return NOT_REPORTED
    symbol = "$" if currency in (None, "USD") else f"{currency} "
    return f"{symbol}{value:,.2f}"


def flag(value: bool | None, true_text: str, false_text: str) -> str:
    if value is None:
        return NOT_REPORTED
    return true_text if value else false_text


class _ElidingLabel(QLabel):
    """A label that shortens with an ellipsis rather than being cut off (M87).

    The deployed M86 build rendered "Day trades (5d)" as **"Da"** on the
    Dashboard - hard-cut at the right edge of the card, mid-word, with no
    indication that anything was missing. "Da" does not read as an abbreviation;
    it reads as a different label.

    Elision is the difference between a label the operator can see is
    abbreviated and one that silently means something else. The full text stays
    in the tooltip and in `full_text`, so nothing is actually lost - and the
    widget stops demanding the width of its longest label, which is what let one
    cell push another off the edge in the first place.
    """

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.full_text = text
        # Or the label's own minimum keeps the column as wide as the text, and
        # eliding would never be reached.
        self.setMinimumWidth(0)

    def setText(self, text: str) -> None:  # noqa: N802 - Qt's spelling
        self.full_text = text
        self._apply_elision()

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 - Qt's spelling
        super().resizeEvent(event)
        self._apply_elision()

    def _apply_elision(self) -> None:
        elided = self.fontMetrics().elidedText(
            self.full_text, Qt.TextElideMode.ElideRight, self.width()
        )
        QLabel.setText(self, elided)
        # Set unconditionally, not only when elided: a tooltip that appears and
        # disappears with the window width is a worse contract than one that is
        # always there.
        if not self.toolTip():
            self.setToolTip(self.full_text)


class _Cell(QFrame):
    """One label/value pair, so the grid reads as a balance sheet.

    `caption` is the plain-English line beneath the figure, shown only at the
    levels that explain. It is SET regardless of level and merely hidden (M58c),
    so anything reading the panel programmatically still sees the whole story.
    """

    def __init__(
        self,
        label: str,
        tooltip: str = "",
        caption: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(0)
        self.label_text = label
        self._label = _ElidingLabel(label)
        self._label.setStyleSheet(theme.text(_MUTED, size=theme.CAPTION))
        self._value = QLabel(NOT_REPORTED)
        self._value.setStyleSheet(theme.text(size=theme.SUBHEAD, bold=True))
        if tooltip:
            self.setToolTip(tooltip)
            # The label's own tooltip leads with the full label, because the
            # label is the part that may be elided (M87) - an operator reading
            # "Day tra…" needs to know the word before the explanation of it.
            self._label.setToolTip(f"{label} - {tooltip}")
        layout.addWidget(self._label)
        layout.addWidget(self._value)
        self.caption = QLabel(caption)
        self.caption.setWordWrap(True)
        # theme.CAPTION rather than a smaller size of its own: the scale is
        # closed, and a caption is exactly what the smallest step is for.
        self.caption.setStyleSheet(theme.text(_MUTED, size=theme.CAPTION))
        layout.addWidget(self.caption)

    def set(self, text: str, colour: str | None = None) -> None:
        self._value.setText(text)
        self._value.setStyleSheet(theme.text(colour, size=theme.SUBHEAD, bold=True))

    def rendered_label(self) -> str:
        """What the label ACTUALLY shows at the current width, elision included.

        Separate from `label_text`, which is the full text and never elides.
        Anything asking what the operator can read has to ask this one - the
        distinction is the whole point of M87.
        """
        return self._label.text()

    def label_tooltip(self) -> str:
        return self._label.toolTip()


class BalancesPanel(QFrame):
    """Two groups, not one grid.

    Ten of the eleven cells carry a real figure on this account, so the problem
    was never unavailable data - it is INAPPLICABLE data at equal weight. Margin
    and buying power are real, prominent, and describe broker capabilities this
    application structurally refuses to use: a buy's notional can never exceed
    available cash, and that is not configurable. Buying power reads seven times
    spendable cash, which the docstring above already calls the single most
    confusing thing about running the two side by side - and until now only a
    tooltip said so.

    The level chooses between three states, not two. `explains()` alone is true
    at both Guided and Standard, so a scheme keyed on it renders those two
    identically - three settings producing two outcomes, which is the M58a
    failure in miniature.
    """

    def __init__(
        self,
        min_cash_reserve: float,
        parent: QWidget | None = None,
        level: UiLevel = UiLevel.STANDARD,
    ) -> None:
        super().__init__(parent)
        self.min_cash_reserve = min_cash_reserve
        # Standard by default, matching AdoptedPositionsPanel: it is the
        # documented default and it explains, which is the safer of the two.
        self.level = level

        self.setObjectName("balancesPanel")
        self.setStyleSheet(theme.panel("balancesPanel"))

        outer = QVBoxLayout(self)
        header = QLabel("Balances")
        header.setStyleSheet(theme.text(size=theme.BODY, bold=True))
        outer.addWidget(header)

        # --- Primary: what this system acts on ---------------------------
        self.portfolio_value = _Cell(
            "Portfolio value",
            "Equity: cash plus market value.",
            "Everything the account is worth: cash plus what the positions are " "currently worth.",
        )
        self.day_pnl = _Cell(
            "Today's P/L",
            "Equity against the previous close, per the broker.",
            "Change since the previous close, as the broker reports it.",
        )
        self.cash = _Cell(
            "Cash",
            "Settled cash held at the broker.",
            "Settled cash at the broker, not yet committed to a position.",
        )
        self.spendable = _Cell(
            "Spendable here",
            "Cash less your minimum reserve - what this application's no-leverage "
            "rule will actually allow a buy to spend. Deliberately far below the "
            "broker's buying power on a margin account.",
            # At Guided the buying-power CELL is absent, so this line is the
            # only thing standing between the operator and the $336k they can
            # see on Alpaca's own page.
            "What a buy may actually use. The broker will offer several times "
            "this on margin; this system never uses margin.",
        )
        self.long_value = _Cell(
            "Long market value",
            "Market value of long positions.",
            "What the held positions are currently worth.",
        )
        self.account_status = _Cell(
            "Account",
            "Broker account status and any blocks.",
            "The broker's own status for the account. Anything but ACTIVE stops trading.",
        )

        primary = (
            self.portfolio_value,
            self.day_pnl,
            self.cash,
            self.spendable,
            self.long_value,
            self.account_status,
        )
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        for index, cell in enumerate(primary):
            grid.addWidget(cell, index // 4, index % 4)
        # Divided evenly rather than sized by whichever cell demands most (M87).
        # Without this the columns take their content's width and the rightmost
        # one - "Spendable here", by this panel's own docstring the most
        # important figure on it - is the one that runs out of room.
        for column in range(4):
            grid.setColumnStretch(column, 1)
        outer.addLayout(grid)

        self.captions = [cell.caption for cell in primary]
        for caption in self.captions:
            caption.setVisible(self.level.explains())
        self._cells_by_label = {cell.label_text: cell for cell in primary}

        # --- Demoted: real figures this system will never act on ----------
        self.buying_power = _Cell(
            "Broker buying power",
            "What the broker would allow, including margin. This application does "
            "not use margin.",
        )
        # REMOVED 21 August 2026: Short market value, Initial margin,
        # Maintenance margin, Day trades (5d).
        #
        # All four were Alpaca-shaped and none of them can be filled on IBKR.
        # `ib_adapter.balances` says so itself - "the IB translation layer does
        # not map margin or day-trade fields, so those stay None rather than
        # being guessed at" - and `_ACCOUNT_TAGS` requests four tags, none of
        # them a margin tag. So all four rendered a dash, every session, for
        # ever.
        #
        # Two of them would stay meaningless even if IBKR did fill them. This
        # application is long-only (`QAT_ALLOW_SHORT_SELLING` defaults false and
        # a sell in an unheld symbol is dropped rather than opening a short), so
        # short market value is structurally zero; and "day trades (5d)" counts
        # against a US pattern-day-trader rule that does not apply to an ASX
        # account at all.
        #
        # The two margin figures COULD be sourced - IBKR publishes InitMarginReq
        # and MaintMarginReq - and were deliberately not, because the
        # no-leverage rail means the account never borrows and the numbers would
        # be reported at rather than acted on. `AccountBalances` keeps all four
        # fields: the Alpaca adapter still populates them, and this was a
        # decision about what the Dashboard SHOWS, not about the data model.

        self.broker_group: QWidget | None = None
        self.broker_body: QWidget | None = None
        self.broker_toggle: QToolButton | None = None
        if self.level.shows_advanced():
            self._build_broker_group(outer)

        self.freshness = QLabel("")
        self.freshness.setStyleSheet(theme.text(_MUTED, size=theme.CAPTION))
        outer.addWidget(self.freshness)

    def _build_broker_group(self, outer: QVBoxLayout) -> None:
        """The figures the broker reports and this application ignores.

        Absent entirely at Guided - heading included, because a heading over
        nothing is worse than no heading. `ui_level` sanctions the absence: a
        control that is absent is one level away, and the level selector says
        so.
        """
        self.broker_group = QWidget()
        group_layout = QVBoxLayout(self.broker_group)
        group_layout.setContentsMargins(0, 6, 0, 0)
        group_layout.setSpacing(2)

        self.broker_toggle = QToolButton()
        self.broker_toggle.setText("At the broker - not used by this system")
        self.broker_toggle.setCheckable(True)
        self.broker_toggle.setChecked(self.level.prefers_density())
        # Scoped to QToolButton so the flat look does not leak to siblings.
        # "border: none" is structure rather than a design token, so it is
        # written here; the colour and the size come from the scale.
        self.broker_toggle.setStyleSheet(
            f"QToolButton {{ border: none; {theme.text(_MUTED, size=theme.CAPTION)} }}"
        )
        self.broker_toggle.toggled.connect(self._on_broker_toggled)
        group_layout.addWidget(self.broker_toggle)

        self.broker_body = QWidget()
        body_grid = QGridLayout(self.broker_body)
        body_grid.setContentsMargins(0, 0, 0, 0)
        body_grid.setHorizontalSpacing(14)
        demoted = (self.buying_power,)
        # One row, not the primary grid's four columns - a compact single row is
        # itself part of saying "secondary".
        #
        # It was five cells until 21 August, and the width reasoning M87 added
        # here is kept deliberately even though one cell cannot overflow: sized
        # by content, five columns demanded ~3775px of a 3086px window on a
        # 125%-scaled display, and "Day trades (5d)" rendered as "Da" against
        # the card's right edge. Even division plus an eliding label is what
        # makes that harmless at any width and any dpi, and it must survive the
        # next cell added here rather than being rediscovered by screenshot.
        for index, cell in enumerate(demoted):
            body_grid.addWidget(cell, 0, index)
            body_grid.setColumnStretch(index, 1)
        # The level sets the STARTING state only; the toggle is never locked.
        self.broker_body.setVisible(self.level.prefers_density())
        group_layout.addWidget(self.broker_body)
        outer.addWidget(self.broker_group)

    def _on_broker_toggled(self, checked: bool) -> None:
        if self.broker_body is not None:
            self.broker_body.setVisible(checked)

    def caption_for(self, label: str) -> QLabel:
        """The caption beneath a named primary cell, for tests and for anything
        reading the panel rather than looking at it."""
        return self._cells_by_label[label].caption

    def update_from(self, snapshot: AccountSnapshot) -> None:
        balances = snapshot.balances
        currency = balances.currency

        self.portfolio_value.set(money(balances.equity, currency))
        self._render_day_pnl(balances)
        self.cash.set(money(balances.cash, currency))
        self._render_spendable(balances, currency)
        self._render_buying_power(balances, currency)
        self.long_value.set(money(balances.long_market_value, currency))
        self._render_status(balances)

        self.freshness.setText(snapshot.age_line())
        stale = snapshot.error or snapshot.is_stale
        self.freshness.setStyleSheet(theme.text(_NEGATIVE if stale else _MUTED, size=theme.CAPTION))

    def _render_day_pnl(self, balances: AccountBalances) -> None:
        change = balances.day_pnl
        if change is None:
            self.day_pnl.set(NOT_REPORTED)
            return
        pct = balances.day_pnl_pct
        suffix = f" ({pct:+.2%})" if pct is not None else ""
        colour = _POSITIVE if change >= 0 else _NEGATIVE
        self.day_pnl.set(f"{change:+,.2f}{suffix}", colour)

    def _render_spendable(self, balances: AccountBalances, currency: str | None) -> None:
        spendable = balances.spendable_cash(self.min_cash_reserve)
        # Amber rather than green: this is a constraint, and it reads as one.
        self.spendable.set(money(spendable, currency), _WARNING if spendable is not None else None)

    def _render_buying_power(self, balances: AccountBalances, currency: str | None) -> None:
        text = money(balances.buying_power, currency)
        if balances.multiplier and balances.multiplier > 1:
            text += f"  ({balances.multiplier:g}x)"
        self.buying_power.set(text)

    def _render_status(self, balances: AccountBalances) -> None:
        blocked = balances.trading_blocked or balances.account_blocked
        if blocked:
            self.account_status.set("BLOCKED", _NEGATIVE)
            return
        self.account_status.set(balances.status or NOT_REPORTED)

"""Account balances on the Dashboard, laid out like the broker's own page
(spec M21).

Two rules govern what this shows.

Nothing is recomputed that the broker already reports. The day's profit is
Alpaca's equity against its own last_equity, not a figure derived here - when
two screens disagree about money the operator has to work out which one is
lying, and that is a worse position than having one number with a caveat.

A figure the broker did not report renders as a dash, never as zero. An Alpaca
paper account returns nothing for the day-trade count or the pattern-day-trader
flag, and "0 day trades" is a different claim from "not reported".

The one figure here that is NOT the broker's is spendable cash, and it is the
most important one on the panel. Alpaca will offer four times your cash as
buying power; this application refuses anything above cash less the reserve.
Seeing $365,162 of buying power next to an order rejected for insufficient
cash is the single most confusing thing about running the two side by side.
"""

from __future__ import annotations

import logging

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


def count(value: int | None) -> str:
    return NOT_REPORTED if value is None else str(value)


def flag(value: bool | None, true_text: str, false_text: str) -> str:
    if value is None:
        return NOT_REPORTED
    return true_text if value else false_text


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
        self._label = QLabel(label)
        self._label.setStyleSheet(f"color: {_MUTED}; font-size: 11px;")
        self._value = QLabel(NOT_REPORTED)
        self._value.setStyleSheet("font-size: 15px; font-weight: bold;")
        if tooltip:
            self.setToolTip(tooltip)
            self._label.setToolTip(tooltip)
        layout.addWidget(self._label)
        layout.addWidget(self._value)
        self.caption = QLabel(caption)
        self.caption.setWordWrap(True)
        # theme.CAPTION rather than a smaller size of its own: the scale is
        # closed, and a caption is exactly what the smallest step is for.
        self.caption.setStyleSheet(f"color: {_MUTED}; font-size: {theme.CAPTION}px;")
        layout.addWidget(self.caption)

    def set(self, text: str, colour: str | None = None) -> None:
        self._value.setText(text)
        style = "font-size: 15px; font-weight: bold;"
        if colour:
            style += f" color: {colour};"
        self._value.setStyleSheet(style)


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
        self.setStyleSheet(
            f"QFrame#balancesPanel {{ border: 1px solid {theme.BORDER}; "
            "border-radius: 4px; padding: 6px; }}"
        )

        outer = QVBoxLayout(self)
        header = QLabel("Balances")
        header.setStyleSheet("font-size: 13px; font-weight: bold;")
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
        self.short_value = _Cell("Short market value", "Market value of short positions.")
        self.initial_margin = _Cell("Initial margin", "Margin required to open current positions.")
        self.maintenance_margin = _Cell(
            "Maintenance margin", "Margin required to keep current positions."
        )
        self.day_trades = _Cell(
            "Day trades (5d)", "Day-trade count. A dash means the broker did not report it."
        )

        self.broker_group: QWidget | None = None
        self.broker_body: QWidget | None = None
        self.broker_toggle: QToolButton | None = None
        if self.level.shows_advanced():
            self._build_broker_group(outer)

        self.freshness = QLabel("")
        self.freshness.setStyleSheet(f"color: {_MUTED}; font-size: 11px;")
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
        self.broker_toggle.setStyleSheet(
            f"QToolButton {{ border: none; color: {_MUTED}; font-size: 11px; }}"
        )
        self.broker_toggle.toggled.connect(self._on_broker_toggled)
        group_layout.addWidget(self.broker_toggle)

        self.broker_body = QWidget()
        body_grid = QGridLayout(self.broker_body)
        body_grid.setContentsMargins(0, 0, 0, 0)
        body_grid.setHorizontalSpacing(14)
        demoted = (
            self.buying_power,
            self.short_value,
            self.initial_margin,
            self.maintenance_margin,
            self.day_trades,
        )
        # One row, not the primary grid's four columns. Five cells wrapped at
        # four orphan the last one onto a row of its own, which reads as a new
        # section rather than the tail of this one - and a compact single row
        # is itself part of saying "secondary".
        for index, cell in enumerate(demoted):
            body_grid.addWidget(cell, 0, index)
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
        self.short_value.set(money(balances.short_market_value, currency))
        self.initial_margin.set(money(balances.initial_margin, currency))
        self.maintenance_margin.set(money(balances.maintenance_margin, currency))
        self._render_day_trades(balances)
        self._render_status(balances)

        self.freshness.setText(snapshot.age_line())
        self.freshness.setStyleSheet(
            f"color: {_NEGATIVE if snapshot.error or snapshot.is_stale else _MUTED}; "
            "font-size: 11px;"
        )

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

    def _render_day_trades(self, balances: AccountBalances) -> None:
        text = count(balances.daytrade_count)
        if balances.pattern_day_trader:
            text += "  PDT"
        self.day_trades.set(text, _WARNING if balances.pattern_day_trader else None)

    def _render_status(self, balances: AccountBalances) -> None:
        blocked = balances.trading_blocked or balances.account_blocked
        if blocked:
            self.account_status.set("BLOCKED", _NEGATIVE)
            return
        self.account_status.set(balances.status or NOT_REPORTED)

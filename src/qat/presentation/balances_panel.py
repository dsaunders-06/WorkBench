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
    QVBoxLayout,
    QWidget,
)

from qat.data.broker.account_poller import AccountSnapshot
from qat.data.broker.adapter import AccountBalances

logger = logging.getLogger(__name__)

NOT_REPORTED = "—"
_POSITIVE = "#1b5e20"
_NEGATIVE = "#b71c1c"
_MUTED = "#5b6572"
_WARNING = "#b45309"


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
    """One label/value pair, so the grid reads as a balance sheet."""

    def __init__(self, label: str, tooltip: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(0)
        self._label = QLabel(label)
        self._label.setStyleSheet(f"color: {_MUTED}; font-size: 11px;")
        self._value = QLabel(NOT_REPORTED)
        self._value.setStyleSheet("font-size: 15px; font-weight: bold;")
        if tooltip:
            self.setToolTip(tooltip)
            self._label.setToolTip(tooltip)
        layout.addWidget(self._label)
        layout.addWidget(self._value)

    def set(self, text: str, colour: str | None = None) -> None:
        self._value.setText(text)
        style = "font-size: 15px; font-weight: bold;"
        if colour:
            style += f" color: {colour};"
        self._value.setStyleSheet(style)


class BalancesPanel(QFrame):
    def __init__(self, min_cash_reserve: float, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.min_cash_reserve = min_cash_reserve

        self.setObjectName("balancesPanel")
        self.setStyleSheet(
            "QFrame#balancesPanel { border: 1px solid #444; border-radius: 4px; padding: 6px; }"
        )

        outer = QVBoxLayout(self)
        header = QLabel("Balances")
        header.setStyleSheet("font-size: 13px; font-weight: bold;")
        outer.addWidget(header)

        grid = QGridLayout()
        grid.setHorizontalSpacing(14)

        self.portfolio_value = _Cell("Portfolio value", "Equity: cash plus market value.")
        self.day_pnl = _Cell("Today's P/L", "Equity against the previous close, per the broker.")
        self.cash = _Cell("Cash", "Settled cash held at the broker.")
        self.spendable = _Cell(
            "Spendable here",
            "Cash less your minimum reserve - what this application's no-leverage "
            "rule will actually allow a buy to spend. Deliberately far below the "
            "broker's buying power on a margin account.",
        )
        self.buying_power = _Cell(
            "Broker buying power",
            "What the broker would allow, including margin. This application does "
            "not use margin.",
        )
        self.long_value = _Cell("Long market value", "Market value of long positions.")
        self.short_value = _Cell("Short market value", "Market value of short positions.")
        self.initial_margin = _Cell("Initial margin", "Margin required to open current positions.")
        self.maintenance_margin = _Cell(
            "Maintenance margin", "Margin required to keep current positions."
        )
        self.day_trades = _Cell(
            "Day trades (5d)", "Day-trade count. A dash means the broker did not report it."
        )
        self.account_status = _Cell("Account", "Broker account status and any blocks.")

        cells = (
            (self.portfolio_value, 0, 0),
            (self.day_pnl, 0, 1),
            (self.cash, 0, 2),
            (self.spendable, 0, 3),
            (self.buying_power, 1, 0),
            (self.long_value, 1, 1),
            (self.short_value, 1, 2),
            (self.day_trades, 1, 3),
            (self.initial_margin, 2, 0),
            (self.maintenance_margin, 2, 1),
            (self.account_status, 2, 2),
        )
        for cell, row, column in cells:
            grid.addWidget(cell, row, column)
        outer.addLayout(grid)

        self.freshness = QLabel("")
        self.freshness.setStyleSheet(f"color: {_MUTED}; font-size: 11px;")
        outer.addWidget(self.freshness)

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

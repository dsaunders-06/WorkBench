"""Performance screen (spec M16): realised results and promotion status.

Every other screen shows what the system is doing or intends to do. This is
the only one that shows whether any of it worked, which is the question the
promotion decision actually turns on.

The promotion table leads because its most important row is the easiest to
miss: a strategy trading unattended on a record that no longer supports it.
That state is colour-coded rather than left as one line among many.
"""

from __future__ import annotations

import asyncio
import logging

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from qat.data import instruments
from qat.domain.performance import compute_stats, max_drawdown, sharpe_ratio
from qat.domain.performance.reports import (
    DAILY_REPORT_FILENAME,
    WEEKLY_REPORT_FILENAME,
    ReportWriter,
)
from qat.domain.performance.scorecard import build_all_scorecards
from qat.presentation.runtime import Runtime

logger = logging.getLogger(__name__)

_MAX_TRADE_ROWS = 200
_STATUS_COLOURS = {
    "promoted": QColor("#1b5e20"),
    "promoted-below-bar": QColor("#b71c1c"),
    "eligible": QColor("#1e3a5f"),
    "not-eligible": QColor("#5b6572"),
}
_PROMOTION_COLUMNS = ("Strategy", "Status", "Trades", "Net P&L", "Win rate", "Avg R", "Blocking")
_TRADE_COLUMNS = ("Closed", "Symbol", "Name", "Strategy", "Qty", "Entry", "Exit", "P&L", "R")


class PerformanceScreen(QWidget):
    def __init__(self, runtime: Runtime, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.runtime = runtime

        layout = QVBoxLayout(self)

        header = QHBoxLayout()
        self.headline = QLabel("Performance: (not yet loaded)")
        self.headline.setStyleSheet("font-size: 15px; font-weight: bold;")
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(self._on_refresh_clicked)
        header.addWidget(self.headline, stretch=1)
        header.addWidget(self.refresh_button)
        layout.addLayout(header)

        promotion_box = QGroupBox("Promotion status")
        promotion_layout = QVBoxLayout(promotion_box)
        promotion_note = QLabel(
            "The gate advises. You can promote a strategy it has not cleared in Settings - "
            "this table shows you doing it. Enable "
            "<code>QAT_ENFORCE_PROMOTION_EVIDENCE</code> to make the bar binding."
        )
        promotion_note.setStyleSheet("color: gray;")
        promotion_note.setWordWrap(True)
        promotion_layout.addWidget(promotion_note)
        self.promotion_table = QTableWidget(0, len(_PROMOTION_COLUMNS))
        self.promotion_table.setHorizontalHeaderLabels(list(_PROMOTION_COLUMNS))
        promotion_layout.addWidget(self.promotion_table)
        layout.addWidget(promotion_box)

        tabs = QTabWidget()
        self.trades_table = QTableWidget(0, len(_TRADE_COLUMNS))
        self.trades_table.setHorizontalHeaderLabels(list(_TRADE_COLUMNS))
        tabs.addTab(self.trades_table, "Closed trades")

        self.daily_view = QTextEdit()
        self.daily_view.setReadOnly(True)
        tabs.addTab(self.daily_view, "Daily reports")

        self.weekly_view = QTextEdit()
        self.weekly_view.setReadOnly(True)
        tabs.addTab(self.weekly_view, "Weekly reports")
        layout.addWidget(tabs, stretch=1)

        self.refresh()

    def _on_refresh_clicked(self) -> None:
        asyncio.ensure_future(self._refresh_async())

    async def _refresh_async(self) -> None:
        self.refresh()

    def refresh(self) -> None:
        try:
            self._render_headline()
            self._render_promotion()
            self._render_trades()
            self._render_reports()
        except Exception as exc:  # noqa: BLE001 - surfaced rather than crashing the tab
            logger.exception("Performance refresh failed")
            self.headline.setText(f"Performance unavailable: {exc}")

    def _render_headline(self) -> None:
        trades = self.runtime.trade_ledger.closed_trades()
        points = self.runtime.equity_curve.points()
        stats = compute_stats(trades)

        parts = [stats.summary_line()]
        if points:
            parts.append(f"Max drawdown {max_drawdown(points):.2%}")
            sharpe = sharpe_ratio(points)
            parts.append(
                f"Sharpe {sharpe:.2f}" if sharpe is not None else "Sharpe not yet measurable"
            )
        self.headline.setText("  |  ".join(parts))

    def _render_promotion(self) -> None:
        ledger = self.runtime.trade_ledger
        cards = build_all_scorecards(
            {name: ledger.closed_trades(name) for name in ledger.strategies()},
            self.runtime.settings,
        )
        self.promotion_table.setRowCount(len(cards))
        for row, card in enumerate(cards):
            stats = card.stats
            blocking = "; ".join(c.name for c in card.failing) or "-"
            values = (
                card.strategy,
                card.status,
                str(stats.trade_count),
                f"${stats.total_pnl:,.2f}",
                f"{stats.win_rate:.0%}" if stats.win_rate is not None else "-",
                f"{stats.average_r:+.2f}" if stats.average_r is not None else "-",
                blocking,
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 1:
                    item.setForeground(_STATUS_COLOURS.get(card.status, QColor("#5b6572")))
                    item.setToolTip(card.summary_line())
                self.promotion_table.setItem(row, column, item)
        self.promotion_table.resizeColumnsToContents()

    def _render_trades(self) -> None:
        # Newest first: a review starts from what just happened.
        trades = list(reversed(self.runtime.trade_ledger.closed_trades()))[:_MAX_TRADE_ROWS]
        self.trades_table.setRowCount(len(trades))
        for row, trade in enumerate(trades):
            values = (
                f"{trade.closed_at:%Y-%m-%d %H:%M}",
                trade.symbol,
                instruments.name_for(trade.symbol),
                trade.strategy or "-",
                f"{trade.quantity:g}",
                f"{trade.entry_price:.2f}",
                f"{trade.exit_price:.2f}",
                f"{trade.pnl:+,.2f}",
                f"{trade.r_multiple:+.2f}" if trade.r_multiple is not None else "-",
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 7:
                    item.setForeground(QColor("#1b5e20") if trade.pnl > 0 else QColor("#b71c1c"))
                self.trades_table.setItem(row, column, item)
        self.trades_table.resizeColumnsToContents()

    def _render_reports(self) -> None:
        data_dir = self.runtime.settings.data_dir
        daily = ReportWriter(data_dir, DAILY_REPORT_FILENAME).read()
        weekly = ReportWriter(data_dir, WEEKLY_REPORT_FILENAME).read()
        self.daily_view.setPlainText(
            daily or "No daily reports yet. One is written after each market close."
        )
        self.weekly_view.setPlainText(
            weekly or "No weekly reports yet. One is written after the week's last close."
        )

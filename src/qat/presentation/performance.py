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
from datetime import date, timedelta

from PySide6.QtCore import QDate, QTimer
from PySide6.QtGui import QColor, QHideEvent, QShowEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QDateEdit,
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
from qat.domain.display_dates import format_display_date, format_session_time
from qat.domain.performance.report_index import (
    days_available,
    for_day,
    parse_reports,
    week_of,
)
from qat.domain.performance.reports import (
    DAILY_REPORT_FILENAME,
    WEEKLY_REPORT_FILENAME,
    ReportWriter,
)
from qat.domain.performance.scorecard import StrategyScorecard, build_all_scorecards
from qat.domain.performance.session_export import export_session
from qat.domain.performance.summary import PerformanceSummary, build_summary
from qat.domain.performance.trades import ClosedTrade
from qat.presentation import theme
from qat.presentation.runtime import Runtime
from qat.presentation.ui_level import UiLevel

logger = logging.getLogger(__name__)

NOT_AVAILABLE = "—"  # em dash: absent, never a measured zero
_MAX_TRADE_ROWS = 200
# Matches the market-data poll: nothing here changes faster than the prices.
_REFRESH_MS = 60_000
_STATUS_COLOURS = {
    "promoted": QColor(theme.SUCCESS),
    "promoted-below-bar": QColor(theme.DANGER),
    "eligible": QColor(theme.ACCENT),
    "not-eligible": QColor(theme.MUTED),
}
_PROMOTION_COLUMNS = (
    "Strategy",
    "Status",
    "Trades",
    "Net P&L",
    "Costs",
    "Win rate",
    "Avg R",
    "Blocking",
)
# Gross and net side by side: the gap between them is the whole point of M28,
# and a single "P&L" column hides whichever one you are not looking at.
_TRADE_COLUMNS = (
    "Closed",
    "Symbol",
    "Name",
    "Strategy",
    "Qty",
    "Entry",
    "Exit",
    "Gross",
    "Costs",
    "Net P&L",
    "R",
)
_METRIC_COLUMNS = ("Metric", "Value", "What it tells you")
_NET_PNL_COLUMN = _TRADE_COLUMNS.index("Net P&L")
# §4.4: "for analysis, not monitoring. Professional only." Appended rather than
# interleaved so the column a reader looks for does not move with the level -
# a table whose "Net P&L" is in a different place at each level is worse than
# one that is merely longer.
_DIAGNOSTIC_COLUMNS = (
    "Regime at entry",
    "Exit reason",
    "MAE (R)",
    "MFE (R)",
    "Slippage",
)


def _diagnostics(trade: ClosedTrade) -> tuple[str, ...]:
    """The M37 columns, for one trade.

    Every one of these is `None` on a trade that predates the milestone that
    started recording it, and an em dash says so rather than printing a zero -
    the rule `_percent` follows on the Screener and `available_figures` follows
    for the model.

    **Slippage is the one to read carefully.** It is `entry_price -
    reference_price`, and until M70 both came from the same transmit-time
    announcement, so it was zero BY CONSTRUCTION on every entry this app had
    ever opened. A run of exact zeroes here is that defect's fingerprint, not a
    frictionless fill, and it will persist for every trade opened before M70
    reaches the account.
    """
    return (
        trade.regime_at_entry or NOT_AVAILABLE,
        trade.exit_reason or NOT_AVAILABLE,
        f"{trade.mae_r:+.2f}" if trade.mae_r is not None else NOT_AVAILABLE,
        f"{trade.mfe_r:+.2f}" if trade.mfe_r is not None else NOT_AVAILABLE,
        f"{trade.entry_slippage:+.4f}" if trade.entry_slippage is not None else NOT_AVAILABLE,
    )


def _verdict(card: StrategyScorecard) -> str:
    """One strategy's promotion status, in a sentence (M79).

    §4.4's Guided column: "one verdict per strategy in words, plus what is
    blocking it". The table says `not-eligible` in a Status column beside a
    semicolon-joined `Blocking` list, which is precise and assumes the reader
    knows there is a bar, what it is, and that failing it is normal this early.

    Leads with the trade count when there is not enough evidence to say
    anything, because "not eligible" reads as a verdict on the strategy and at
    this stage it is a verdict on the sample.
    """
    stats = card.stats
    failing = card.failing
    if stats.trade_count == 0:
        return f"<b>{card.strategy}</b>: no closed trades yet - nothing to judge it on."
    blocking = ", ".join(c.name for c in failing)
    if card.status == "promoted":
        return (
            f"<b>{card.strategy}</b>: live, and clearing the promotion bar on "
            f"{stats.trade_count} closed trade(s)."
        )
    if card.status == "promoted-below-bar":
        return (
            f"<b>{card.strategy}</b>: live, but NOT clearing the bar - {blocking}. "
            "It was promoted anyway, which the gate allows and records."
        )
    if card.status == "eligible":
        return (
            f"<b>{card.strategy}</b>: clears the bar on {stats.trade_count} closed "
            "trade(s), and is not live. Deploy it in the Strategy Workbench."
        )
    return (
        f"<b>{card.strategy}</b>: not yet clearing the bar on {stats.trade_count} "
        f"closed trade(s). Waiting on: {blocking}."
    )


class PerformanceScreen(QWidget):
    def __init__(self, runtime: Runtime, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.runtime = runtime
        self.level = UiLevel.from_settings(runtime.settings)

        layout = QVBoxLayout(self)

        header = QHBoxLayout()
        self.headline = QLabel("Performance: (not yet loaded)")
        self.headline.setStyleSheet(theme.text(theme.ACCENT, size=theme.SUBHEAD, bold=True))
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(self._on_refresh_clicked)
        self.export_button = QPushButton("Export Session")
        self.export_button.setToolTip(
            "Copy this session's trades, equity curve, decision journal, risk decisions, "
            "reports and logs into a single zip for a post-mortem.\n"
            "Nothing is moved or deleted - the running session keeps writing."
        )
        self.export_button.clicked.connect(self._on_export_clicked)
        header.addWidget(self.headline, stretch=1)
        header.addWidget(self.export_button)
        header.addWidget(self.refresh_button)
        layout.addLayout(header)

        self.export_status = QLabel("")
        self.export_status.setWordWrap(True)
        self.export_status.setStyleSheet(theme.text(theme.MUTED))
        layout.addWidget(self.export_status)

        promotion_box = QGroupBox("Promotion status")
        promotion_layout = QVBoxLayout(promotion_box)
        promotion_note = QLabel(
            "The gate advises. You can promote a strategy it has not cleared in Settings - "
            "this table shows you doing it. Enable "
            "<code>QAT_ENFORCE_PROMOTION_EVIDENCE</code> to make the bar binding."
        )
        promotion_note.setStyleSheet(theme.text(theme.MUTED))
        promotion_note.setWordWrap(True)
        promotion_layout.addWidget(promotion_note)

        # Guided reads sentences; everyone else reads the table (§4.4). Both
        # are built from the same scorecards, so they cannot disagree.
        self.verdicts = QLabel("")
        self.verdicts.setWordWrap(True)
        self.verdicts.setStyleSheet(theme.text(theme.ACCENT, size=theme.BODY))
        promotion_layout.addWidget(self.verdicts)

        self.promotion_table = QTableWidget(0, len(_PROMOTION_COLUMNS))
        self.promotion_table.setHorizontalHeaderLabels(list(_PROMOTION_COLUMNS))
        promotion_layout.addWidget(self.promotion_table)

        # Why this table's trade count can be lower than the one in Metrics.
        # Hidden when they agree - a note that is always on screen stops being
        # read, which is the M69 rule.
        self.unattributed_note = QLabel("")
        self.unattributed_note.setWordWrap(True)
        self.unattributed_note.setStyleSheet(theme.callout("warning"))
        self.unattributed_note.setVisible(False)
        promotion_layout.addWidget(self.unattributed_note)
        layout.addWidget(promotion_box)

        self.tabs = tabs = QTabWidget()

        # Leads the tab strip: these are the figures that say what the system
        # is, where the trade list only says what it did.
        self.metrics_table = QTableWidget(0, len(_METRIC_COLUMNS))
        self.metrics_table.setHorizontalHeaderLabels(list(_METRIC_COLUMNS))
        self.metrics_table.verticalHeader().setVisible(False)
        tabs.addTab(self.metrics_table, "Metrics")

        self.trade_columns = (
            _TRADE_COLUMNS + _DIAGNOSTIC_COLUMNS if self.level.prefers_density() else _TRADE_COLUMNS
        )
        self.trades_table = QTableWidget(0, len(self.trade_columns))
        self.trades_table.setHorizontalHeaderLabels(list(self.trade_columns))
        # Sortable only where the diagnostics are, per §4.4 - sorting is what
        # makes "which regime did the losers happen in" answerable, and that is
        # an analysis question rather than a monitoring one.
        self.trades_table.setSortingEnabled(self.level.prefers_density())
        tabs.addTab(self.trades_table, "Closed trades")

        # ⚠️ THE CURRENT WEEK, NEWEST FIRST - not the whole file.
        #
        # `ReportWriter.append` writes newest LAST, so rendering the file as one
        # blob put the report you want at the BOTTOM of an ever-growing scroll.
        # Operator design, 10 September 2026: show this week, reach earlier days
        # with the picker.
        daily_tab = QWidget()
        daily_layout = QVBoxLayout(daily_tab)
        controls = QHBoxLayout()
        controls.addWidget(QLabel("Day:"))
        self.report_day = QDateEdit()
        self.report_day.setCalendarPopup(True)
        self.report_day.setDisplayFormat("ddd d MMM yyyy")
        self.report_day.dateChanged.connect(self._render_reports)
        controls.addWidget(self.report_day)
        self.report_this_week = QCheckBox("This week")
        self.report_this_week.setChecked(True)
        self.report_this_week.toggled.connect(self._render_reports)
        controls.addWidget(self.report_this_week)
        # ⚠️ OFF by default. A day can carry several reports because
        # `regenerate_daily` APPENDS - the original stays as the record of what
        # was reported at the time. The newest is what you want to read; the
        # superseded ones are evidence and stay one click away rather than in
        # the way.
        # Set the picker to the newest available day ONCE, then leave the
        # operator's choice alone - re-setting it on every refresh would
        # yank the selection back while they were reading an older day.
        self._first_report_render = True
        self.report_show_superseded = QCheckBox("Include superseded")
        self.report_show_superseded.toggled.connect(self._render_reports)
        controls.addWidget(self.report_show_superseded)
        controls.addStretch(1)
        daily_layout.addLayout(controls)
        self.daily_view = QTextEdit()
        self.daily_view.setReadOnly(True)
        daily_layout.addWidget(self.daily_view, stretch=1)
        tabs.addTab(daily_tab, "Daily reports")

        self.weekly_view = QTextEdit()
        self.weekly_view.setReadOnly(True)
        tabs.addTab(self.weekly_view, "Weekly reports")
        layout.addWidget(tabs, stretch=1)

        # Keeps the tab current while it is the one on screen. Stopped in
        # hideEvent, so a session spends nothing on a tab nobody is watching.
        self._live_timer = QTimer(self)
        self._live_timer.setInterval(_REFRESH_MS)
        self._live_timer.timeout.connect(self.refresh)

        self._apply_level()
        self.refresh()

    def _apply_level(self) -> None:
        """Three levels, three outcomes (§4.4).

        Guided gets one sentence per strategy and nothing else: the promotion
        table's four statuses and semicolon-joined blocking list are precise and
        assume the reader knows there is a bar and that failing it is normal at
        this stage.

        Standard gets the table and the tabs. Professional additionally gets the
        M37 diagnostic columns and sorting - "for analysis, not monitoring",
        which is the brief's own distinction and a good one: regime-at-entry and
        MAE/MFE answer questions you ask of a finished record, not of a running
        session.

        The headline stays at every level. It is the one line that says whether
        the account made money, and that is not a matter of expertise.
        """
        detailed = self.level.shows_advanced()
        self.verdicts.setVisible(not detailed)
        self.promotion_table.setVisible(detailed)
        self.tabs.setVisible(detailed)

    def _on_export_clicked(self) -> None:
        """Runs on the UI thread: zipping a handful of small text files is far
        faster than the round trip a background task would cost, and the button
        is disabled for the duration either way."""
        self.export_button.setEnabled(False)
        self.export_status.setText("Exporting...")
        try:
            result = export_session(self.runtime.settings.data_dir)
        except Exception as exc:  # noqa: BLE001 - surfaced rather than swallowed
            logger.exception("Session export failed")
            self.export_status.setText(f"Export failed: {exc}")
        else:
            self.export_status.setText(f"{result.summary_line()}  ({result.path})")
        finally:
            self.export_button.setEnabled(True)

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802 - Qt's name
        """Re-read on every switch to this tab (M31b).

        refresh() ran at construction and on the button, and nowhere else - so
        the tab showed whatever was true when the window opened and never
        changed. A session started at 00:18 still displayed 00:18's figures at
        06:04, with Friday's daily report written to disk and absent from the
        screen. Every panel here is a file read, and a review screen that shows
        a twelve-hour-old snapshot without saying so is worse than one that is
        obviously empty.
        """
        super().showEvent(event)
        self.refresh()
        self._live_timer.start()

    def hideEvent(self, event: QHideEvent) -> None:  # noqa: N802 - Qt's name
        """Stop polling the moment the tab is not being looked at."""
        super().hideEvent(event)
        self._live_timer.stop()

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
        summary = build_summary(
            self.runtime.trade_ledger.closed_trades(), self.runtime.equity_curve.points()
        )
        self._render_metrics(summary)

        stats = summary.stats
        parts = [stats.summary_line()]
        if stats.expectancy is not None:
            # Promoted into the headline: it is the one figure that says whether
            # the system makes money per decision, and it was being computed and
            # discarded.
            parts.append(f"expectancy ${stats.expectancy:,.2f}/trade")
        parts.append(f"Max drawdown {summary.max_drawdown_pct:.2%}")
        parts.append(
            f"Sharpe {summary.sharpe:.2f}"
            if summary.sharpe is not None
            else "Sharpe not yet measurable"
        )
        self.headline.setText("  |  ".join(parts))

    def _render_metrics(self, summary: PerformanceSummary) -> None:
        rows = summary.rows()
        self.metrics_table.setRowCount(len(rows))
        for row, (label, value, why) in enumerate(rows):
            label_item = QTableWidgetItem(label)
            value_item = QTableWidgetItem(value)
            value_item.setForeground(QColor(theme.MUTED) if value == "-" else QColor(theme.SUCCESS))
            why_item = QTableWidgetItem(why)
            why_item.setForeground(QColor(theme.MUTED))
            for column, item in enumerate((label_item, value_item, why_item)):
                self.metrics_table.setItem(row, column, item)
        self.metrics_table.resizeColumnsToContents()

    def _render_promotion(self) -> None:
        ledger = self.runtime.trade_ledger
        cards = build_all_scorecards(
            {name: ledger.closed_trades(name) for name in ledger.strategies()},
            self.runtime.settings,
        )
        # The Metrics tab counts every closed trade; this table counts only the
        # ones a strategy owns, because `strategies()` drops a falsy one. Both
        # are right and they disagree, and nothing said so (M83).
        #
        # Not hypothetical: a position opened AT THE BROKER rather than by this
        # app gets a lot with no strategy (M81), so its trade lands in Metrics
        # and never in this table. An operator reading "2 trades" above a table
        # summing to 1 has no way to tell that from a miscount.
        attributed = sum(card.stats.trade_count for card in cards)
        unattributed = len(ledger.closed_trades()) - attributed
        self.unattributed_note.setText(
            ""
            if unattributed <= 0
            else (
                f"{unattributed} closed trade(s) belong to no strategy and are counted in "
                "Metrics and Closed trades but NOT in this table - a position opened at the "
                "broker rather than by this app carries no strategy, so its outcome is real "
                "P&L that no promotion gate can read."
            )
        )
        self.unattributed_note.setVisible(bool(unattributed > 0))
        self.verdicts.setText(
            "<br><br>".join(_verdict(card) for card in cards)
            or "No strategy has produced a closed trade yet."
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
                f"${stats.total_costs:,.2f}",
                f"{stats.win_rate:.0%}" if stats.win_rate is not None else "-",
                f"{stats.average_r:+.2f}" if stats.average_r is not None else "-",
                blocking,
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 1:
                    item.setForeground(_STATUS_COLOURS.get(card.status, QColor(theme.MUTED)))
                    item.setToolTip(card.summary_line())
                self.promotion_table.setItem(row, column, item)
        self.promotion_table.resizeColumnsToContents()

    def _render_trades(self) -> None:
        # Newest first: a review starts from what just happened.
        trades = list(reversed(self.runtime.trade_ledger.closed_trades()))[:_MAX_TRADE_ROWS]
        # Sorting is disabled while the rows are written and restored after.
        # A sorted QTableWidget re-orders on every setItem, so filling it row by
        # row scatters each trade's cells across whatever rows the partial sort
        # had reached.
        sorting = self.trades_table.isSortingEnabled()
        self.trades_table.setSortingEnabled(False)
        self.trades_table.setRowCount(len(trades))
        for row, trade in enumerate(trades):
            values: tuple[str, ...] = (
                f"{format_display_date(trade.closed_at)} "
                f"{format_session_time(trade.closed_at, self.runtime.settings.market)}",
                trade.symbol,
                instruments.name_for(trade.symbol),
                trade.strategy or "-",
                f"{trade.quantity:g}",
                f"{trade.entry_price:.2f}",
                f"{trade.exit_price:.2f}",
                f"{trade.gross_pnl:+,.2f}",
                f"{trade.costs:,.2f}",
                f"{trade.net_pnl:+,.2f}",
                f"{trade.r_multiple:+.2f}" if trade.r_multiple is not None else "-",
            )
            if self.level.prefers_density():
                values += _diagnostics(trade)
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                # Looked up by name, not by a literal index. Adding the gross
                # and cost columns silently moved P&L one place along and left
                # the colour on the wrong number.
                if column == _NET_PNL_COLUMN:
                    item.setForeground(
                        QColor(theme.SUCCESS) if trade.net_pnl > 0 else QColor(theme.DANGER)
                    )
                self.trades_table.setItem(row, column, item)
        self.trades_table.setSortingEnabled(sorting)
        self.trades_table.resizeColumnsToContents()

    def _render_reports(self) -> None:
        data_dir = self.runtime.settings.data_dir
        daily = ReportWriter(data_dir, DAILY_REPORT_FILENAME).read()
        weekly = ReportWriter(data_dir, WEEKLY_REPORT_FILENAME).read()
        self.daily_view.setPlainText(self._daily_text(daily))
        self.weekly_view.setPlainText(
            weekly or "No weekly reports yet. One is written after the week's last close."
        )

    def _daily_text(self, raw: str) -> str:
        """This week newest-first, or one chosen day. Pure enough to test.

        ⚠️ An UNPARSEABLE file falls back to the raw text rather than showing
        nothing. A reports screen that goes blank because a heading changed
        would hide the reports instead of reporting - and the operator would
        have no way to tell "no reports" from "could not read them".
        """
        entries = parse_reports(raw)
        if not entries:
            return raw or "No daily reports yet. One is written after each market close."

        available = days_available(entries)
        if available:
            # Bound the picker to days that exist, so an empty pick is not
            # reachable by accident.
            self.report_day.blockSignals(True)
            self.report_day.setDateRange(
                QDate(available[-1].year, available[-1].month, available[-1].day),
                QDate(available[0].year, available[0].month, available[0].day),
            )
            if not self.report_day.date().isValid() or self._first_report_render:
                newest = available[0]
                self.report_day.setDate(QDate(newest.year, newest.month, newest.day))
                self._first_report_render = False
            self.report_day.blockSignals(False)

        if self.report_this_week.isChecked():
            anchor = available[0] if available else date.today()
            chosen = week_of(entries, anchor)
            heading = f"THIS WEEK - week of {anchor - timedelta(days=anchor.weekday()):%d %b %Y}"
        else:
            # Built explicitly rather than through `toPython()`, which is typed
            # as `object` and would make the day a runtime surprise.
            chosen_qdate = self.report_day.date()
            picked = date(chosen_qdate.year(), chosen_qdate.month(), chosen_qdate.day())
            chosen = for_day(entries, picked)
            heading = f"{picked:%A %d %B %Y}"

        visible = [e for e in chosen if not e.superseded or self.report_show_superseded.isChecked()]
        if not visible:
            return f"{heading}\n\nNo report for this selection."

        hidden = len(chosen) - len(visible)
        parts = [heading, ""]
        for entry in visible:
            if entry.superseded:
                parts.append("[SUPERSEDED - a later report for this day replaces it]")
            parts.append(entry.body)
            parts.append("")
        if hidden:
            parts.append(
                f"({hidden} superseded report(s) hidden - tick 'Include superseded' to read "
                f"what was reported at the time.)"
            )
        return "\n".join(parts)

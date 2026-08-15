"""Dashboard (spec §K): KPI tiles, equity curve, positions table, and an
AI regime-note panel with an explicit Review & Apply action - the AI
proposes, the human disposes; nothing here auto-applies anything.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

import pandas as pd
import pyqtgraph as pg
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from qat.domain.events import RegimeEvent
from qat.domain.oms.adopted import assess_adopted_positions
from qat.domain.oms.position_view import PositionView, build_position_views
from qat.presentation import theme
from qat.presentation.adopted_panel import AdoptedPositionsPanel
from qat.presentation.balances_panel import BalancesPanel
from qat.presentation.runtime import Runtime
from qat.presentation.session_panel import SessionPanel
from qat.presentation.ui_level import UiLevel
from qat.presentation.widgets import KpiTile

logger = logging.getLogger(__name__)

_REFRESH_INTERVAL_MS = 2000
_MAX_EQUITY_POINTS = 500
_MIN_POINTS_FOR_SHARPE = 10

# --- Positions table (positions panel brief) ----------------------------------
#
# Nine columns replacing the old Symbol/Quantity/Avg Price. `None` renders as
# an em dash everywhere on this table, never as a number or a blank cell that
# could be misread as zero (M81, M82: a display that states something false
# is the defect class this project has been bitten by most).
_EM_DASH = "—"
_POSITIONS_COLUMNS = (
    "Symbol",
    "Qty",
    "Entry",
    "Last",
    "P&L",
    "To exit",
    "To stop",
    "Risk",
    "Status",
)
_POSITIONS_PNL_COLUMN = 4
_POSITIONS_STATUS_COLUMN = 8
# Every column except Symbol (text) and Status (a joined sentence) carries a
# number, and reads better right-aligned against its neighbours.
_POSITIONS_NUMERIC_COLUMNS = frozenset(range(1, _POSITIONS_STATUS_COLUMN))

# Cells already carry tooltips (M87); the headers did not, and "To exit" and
# "To stop" are the two most likely to be misread as each other or elided
# first (positions panel brief review, M7).
_POSITIONS_COLUMN_TOOLTIPS = {
    "Symbol": "The traded symbol",
    "Qty": "Quantity currently held",
    "Entry": "This app's own entry price - not the broker's average cost",
    "Last": "The broker's last reported mark; em dash when it reports none",
    "P&L": "Unrealised P&L, as a percentage and in R (risk multiples) when the lot has a stop",
    "To exit": "Distance from the strategy's signal-exit condition, as a fraction of its slow EMA",
    "To stop": "Distance from the last price down to the resting stop",
    "Risk": "This position's share of the aggregate risk-at-stop budget",
    "Status": "What is true about a sell right now - not all of this is a reason one won't fire",
}


def _format_price(value: float | None) -> str:
    return f"{value:,.2f}" if value is not None else _EM_DASH


def _format_pct(value: float | None, decimals: int = 2) -> str:
    return f"{value:.{decimals}%}" if value is not None else _EM_DASH


def _format_pnl(pnl_pct: float | None, pnl_r: float | None) -> str:
    """ "-6.2% (0.35R)", or just the percentage when there is no R (no stop on
    the lot to measure one against).

    The R figure is shown unsigned: the percentage already carries the
    direction, and an operator reading this says "down 0.35R", not
    "-0.35R" - restating the sign a second time would only invite the two to
    disagree if one were ever rounded differently from the other.
    """
    if pnl_pct is None:
        return _EM_DASH
    text = f"{pnl_pct:.1%}"
    if pnl_r is None:
        return text
    return f"{text} ({abs(pnl_r):.2f}R)"


class DashboardScreen(QWidget):
    def __init__(self, runtime: Runtime, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.runtime = runtime
        self._equity_history: list[float] = []
        # Parallel to it, and trimmed with it (M56). Kept as epoch seconds
        # because that is what DateAxisItem reads.
        self._equity_times: list[float] = []

        layout = QVBoxLayout(self)

        # Above the regime header on purpose: whether the market is even open
        # is the first thing that makes the rest of this screen meaningful.
        self.session_panel = SessionPanel(
            runtime.session_controller, market=runtime.settings.market
        )
        layout.addWidget(self.session_panel)

        # Directly under the session panel, because when this fires it is the
        # answer to "the market is open and nothing is happening".
        # The expertise level, finally consumed by a screen (M58c). Read once
        # at construction like every other setting - the level takes effect at
        # the next restart, which is what Settings promises.
        self.adopted_panel = AdoptedPositionsPanel(level=UiLevel.from_settings(runtime.settings))
        layout.addWidget(self.adopted_panel)

        # Directly under the adoption banner, because a pending corporate action
        # is the same class of fact: something is true about a held position that
        # the ordinary figures on this screen do not show (M39, R1). Hidden when
        # there is nothing pending - a permanent empty notice is what M74 was
        # partly for.
        self.corporate_action_banner = QLabel("")
        self.corporate_action_banner.setWordWrap(True)
        self.corporate_action_banner.setStyleSheet(
            f"background-color: {theme.WARNING}; color: white; font-weight: bold; padding: 6px;"
        )
        self.corporate_action_banner.setVisible(False)
        layout.addWidget(self.corporate_action_banner)

        self.regime_header = QLabel("Regime: (waiting for data...)")
        self.regime_header.setStyleSheet("font-size: 15px; font-weight: bold;")
        layout.addWidget(self.regime_header)

        # The balances panel replaces the old NAV tile (M21). Showing both
        # would put two numbers for the same money on one screen and invite the
        # question of why they differ - they do not.
        self.balances_panel = BalancesPanel(
            runtime.settings.min_cash_reserve,
            level=UiLevel.from_settings(runtime.settings),
        )
        layout.addWidget(self.balances_panel)

        # The three risk figures survive as a compact line rather than tiles:
        # they matter, but they are not what this screen is now led by.
        risk_row = QHBoxLayout()
        self.var_tile = KpiTile("Portfolio VaR (95%)")
        self.sharpe_tile = KpiTile("Realised Sharpe (naive)")
        self.drawdown_tile = KpiTile("Drawdown vs limit")
        for tile in (self.var_tile, self.sharpe_tile, self.drawdown_tile):
            risk_row.addWidget(tile)
        layout.addLayout(risk_row)

        # Real clock time, not a sample count (M56).
        #
        # This plotted `_equity_history` as a bare list, so the x-axis counted
        # account polls. Two problems, and the second is the serious one: an
        # overnight close and a busy minute occupied the same width, and a poll
        # that failed silently shortened the axis rather than leaving a gap.
        # Equity at 14:03 is a fact an operator can act on; equity at "sample
        # 412" is not.
        #
        # DateAxisItem also solves the spacing question on its own - it chooses
        # ticks appropriate to the visible span, so a session shows times of day
        # and a fortnight shows dates, without this screen deciding which.
        self.equity_plot = pg.PlotWidget(
            title="Equity Curve", axisItems={"bottom": pg.DateAxisItem()}
        )
        theme.label_axes(self.equity_plot, bottom="Time", left="NAV ($)")
        self.equity_curve = self.equity_plot.plot(pen=theme.SERIES_PRIMARY)
        layout.addWidget(self.equity_plot)

        # After the curve exists, and the position is load-bearing (M56a).
        # This ran at the top of __init__ beside the two lists it fills, which
        # read naturally and was wrong: the seed also DRAWS, and the thing it
        # draws onto is created here. Against an empty data directory the draw
        # sits behind a falsy `if` and never runs, so every test passed while
        # the app could not start on any machine with recorded history.
        self._seed_equity_history()

        layout.addWidget(QLabel("Positions"))
        self.positions_table = QTableWidget(0, len(_POSITIONS_COLUMNS))
        self.positions_table.setHorizontalHeaderLabels(list(_POSITIONS_COLUMNS))
        # Cells get a tooltip below; the headers need one too (M87 originally
        # fixed only the cells) - "To exit" and "To stop" are the two most in
        # need of disambiguating, and the first to elide.
        for col, label in enumerate(_POSITIONS_COLUMNS):
            header_item = self.positions_table.horizontalHeaderItem(col)
            if header_item is not None:
                header_item.setToolTip(_POSITIONS_COLUMN_TOOLTIPS[label])
        # Status carries the most variable-length text on the row - the notes
        # joined into a sentence - so it gets the Stretch treatment the
        # Blotter's Reason column already has (M87): every other column keeps
        # a sensible fixed width and Status takes whatever the window has
        # left, rather than every column's minimum width summing past the
        # panel and clipping the last one off the edge.
        self.positions_table.horizontalHeader().setSectionResizeMode(
            _POSITIONS_STATUS_COLUMN, QHeaderView.ResizeMode.Stretch
        )
        layout.addWidget(self.positions_table)

        layout.addWidget(QLabel("AI Regime Note"))
        self.ai_note_label = QLabel("(no note yet)")
        self.ai_note_label.setWordWrap(True)
        layout.addWidget(self.ai_note_label)
        self.review_button = QPushButton("Review && Apply")
        self.review_button.clicked.connect(self._on_review_clicked)
        layout.addWidget(self.review_button)

        self.runtime.bus.subscribe(RegimeEvent, self._on_regime)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._schedule_refresh)
        self._timer.start(_REFRESH_INTERVAL_MS)

    def _schedule_refresh(self) -> None:
        """Qt's timer can fire whenever the widget is alive, including before
        the qasync loop is running or after it has stopped. asyncio.ensure_future
        raises in that window, and because this is a Qt slot the exception
        escapes into Qt's handler rather than anywhere useful - so the loop is
        checked for rather than assumed.

        Skipping a tick is the right response: the timer will come round again
        once the loop exists, and the tiles are refreshed from scratch each
        time, so nothing is lost by missing one.
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.debug("Dashboard refresh skipped - no running event loop")
            return
        loop.create_task(self._refresh_guarded())

    async def _refresh_guarded(self) -> None:
        """Timer-driven, so an exception here would otherwise vanish into an
        un-awaited Task and leave the tiles silently frozen at stale values."""
        try:
            await self._refresh()
        except Exception as exc:  # noqa: BLE001 - surfaced to the user below
            logger.exception("Dashboard refresh failed")
            self.regime_header.setText(f"Dashboard refresh failed: {exc}")

    def _refresh_corporate_actions(self) -> None:
        """The pending-action banner (M39, R1).

        Says the MODE as well as the action, because "detected" and "adjusted"
        are different facts and shadow mode does only the first. An operator
        reading "split pending" and assuming the stop has been moved is the
        failure this wording exists to prevent - the same shape as M60's
        "declared" being read as "fixed".
        """
        monitor = getattr(self.runtime, "corporate_action_monitor", None)
        if monitor is None:
            self.corporate_action_banner.setVisible(False)
            return
        blind = monitor.unreadable_symbols()
        if blind:
            # The banner has to appear for this too. A silent Dashboard while the
            # detector cannot see is indistinguishable from a quiet book.
            self.corporate_action_banner.setText(
                f"CORPORATE ACTIONS COULD NOT BE READ for {', '.join(blind)}. The split "
                f"detector is blind on these - that is not the same as nothing being pending. "
                f"Check the log."
            )
            self.corporate_action_banner.setVisible(True)
            return
        pending = monitor.pending_actions()
        if not pending:
            self.corporate_action_banner.setVisible(False)
            return
        acting = self.runtime.settings.corporate_action_mode == "act"
        verb = (
            "the resting stop has been adjusted"
            if acting
            else "SHADOW MODE - nothing has been adjusted"
        )
        self.corporate_action_banner.setText(
            f"CORPORATE ACTION PENDING: {'; '.join(a.describe() for a in pending)} - {verb}. "
            f"New entries in these symbols are refused until it has passed."
        )
        self.corporate_action_banner.setVisible(True)

    def _seed_equity_history(self) -> None:
        """Start from what was already recorded, not from an empty axis (M56).

        `equity_curve.csv` has been written every poll since 26 July and read
        back since M31c, so the history exists - the chart simply never asked
        for it and began blank at every launch. On a time axis that matters
        more than it did on a sample count: an axis whose range is "the last
        four minutes" cannot show that the market was shut overnight.

        Failure here is not worth a broken screen. The live path appends to
        these lists regardless, so an unreadable curve costs the historical
        span and nothing else.
        """
        try:
            points = self.runtime.equity_curve.points()[-_MAX_EQUITY_POINTS:]
        except Exception:  # noqa: BLE001 - a dashboard must still open
            logger.warning("Could not seed the equity chart from the recorded curve", exc_info=True)
            return
        self._equity_times = [point.ts.timestamp() for point in points]
        self._equity_history = [point.equity for point in points]
        if self._equity_history:
            self.equity_curve.setData(self._equity_times, self._equity_history)

    async def _refresh(self) -> None:
        # One shared, throttled read rather than two broker calls per tick.
        # This screen's two-second timer was spending sixty requests a minute
        # of a two-hundred-per-minute budget on repainting.
        snapshot = await self.runtime.account_poller.snapshot()
        self.balances_panel.update_from(snapshot)
        self._refresh_corporate_actions()

        positions = list(snapshot.positions)
        equity = snapshot.balances.equity
        if equity is None:
            return
        self._equity_history.append(equity)
        self._equity_times.append(datetime.now(UTC).timestamp())
        if len(self._equity_history) > _MAX_EQUITY_POINTS:
            trim = len(self._equity_history) - _MAX_EQUITY_POINTS
            del self._equity_history[:trim]
            del self._equity_times[:trim]
        self.equity_curve.setData(self._equity_times, self._equity_history)

        if len(self._equity_history) >= 2:
            peak = max(self._equity_history)
            current = self._equity_history[-1]
            drawdown_pct = (peak - current) / peak if peak > 0 else 0.0
            limit_pct = self.runtime.settings.max_drawdown_limit_pct
            self.drawdown_tile.set_value(
                f"{drawdown_pct:.2%} / {limit_pct:.0%}",
                color=theme.DANGER if drawdown_pct >= limit_pct else theme.SUCCESS,
            )

        if len(self._equity_history) >= _MIN_POINTS_FOR_SHARPE:
            returns = pd.Series(self._equity_history).pct_change().dropna()
            if returns.std() > 0:
                sharpe = (returns.mean() / returns.std()) * (252**0.5)
                self.sharpe_tile.set_value(f"{sharpe:.2f}")

        latest_decisions = self.runtime.risk_engine.audit_log.entries()
        if latest_decisions:
            portfolio_check = latest_decisions[-1].inputs.get("portfolio_check")
            if portfolio_check and "var_95" in portfolio_check:
                self.var_tile.set_value(f"{portfolio_check['var_95']:.2%}")

        self.adopted_panel.update_from(
            assess_adopted_positions(
                adopted_baseline=self.runtime.oms.adopted_baseline,
                positions=positions,
                stops=self.runtime.oms.position_stops(),
                equity=equity,
                settings=self.runtime.settings,
                # The app's own record of what it opened, so a restart reads
                # as a restart rather than as an unexplained holding (M33e).
                opened_by_this_app=self.runtime.opened_position_symbols(),
            )
        )

        # A second `position_stops()` read, not a shared one - the adopted
        # panel above already read one a few lines up (positions panel brief
        # review, M1: an earlier version of this comment claimed otherwise).
        # Harmless duplication: `position_stops()` is a synchronous local
        # dict copy, never a broker call, so it is not the M21 pattern this
        # screen otherwise follows for the actual broker round trip - the
        # account snapshot at the top of `_refresh` is the one that matters.
        resting_stops = self.runtime.oms.position_stops()
        views = build_position_views(
            positions=positions,
            entries=(
                self.runtime.signal_bridge.position_entries()
                if self.runtime.signal_bridge is not None
                else {}
            ),
            resting_stops=resting_stops,
            # The SAME derivation the aggregate cap is gated on (piece 1 of
            # the brief) - never recomputed here, or this panel could show a
            # per-position risk figure that has quietly drifted from the one
            # that refuses entries.
            snapshot=self.runtime.risk_engine.governor.snapshot(positions, resting_stops, equity),
            settings=self.runtime.settings,
            bars_for=self._bars_for,
            strategies=self.runtime.available_strategies,
            # The true edge of the system: everything downstream of here
            # (position_view.py) takes an injected clock, and this is where
            # the wall clock actually gets read - the same boundary
            # SignalToOrderBridge._now draws for the churn rails.
            clock=lambda: datetime.now(UTC),
        )
        self._populate_positions_table(views)

    def _bars_for(self, symbol: str) -> pd.DataFrame | None:
        """The bars `PositionView.exit_distance` is computed from.

        Not literally the aggregator the exit condition is judged against
        (positions panel brief review, M2: an earlier version of this
        docstring claimed that). `exit_distance` is a STRATEGY accessor, and
        the signal that would actually fire comes from `on_features`
        evaluating `StrategyEngine.bars` - a separate `MultiSymbolAggregator`
        instance from this bridge's own `bars`. The two stay in step because
        `runtime.py`'s `WarmStart` seeds both of them (and `FeatureEngine.bars`)
        from one shared warm-start pass and then feeds all three the same
        live event stream - not because reading this one is reading "the
        same aggregator" the strategy engine does.

        Read-only (M6): `frame_if_present` never creates an aggregator entry
        for a symbol this bridge has not already seen the way `frame()`
        would, so opening the dashboard cannot mutate `SignalToOrderBridge`
        state - the same principle `position_entries()` already applies to
        the entry record.
        """
        bridge = self.runtime.signal_bridge
        if bridge is None:
            return None
        return bridge.bars.frame_if_present(symbol)

    def _populate_positions_table(self, views: tuple[PositionView, ...]) -> None:
        table = self.positions_table
        table.setRowCount(len(views))
        for row, view in enumerate(views):
            cells = (
                view.symbol,
                f"{view.quantity:g}",
                _format_price(view.entry_price),
                _format_price(view.last_price),
                _format_pnl(view.pnl_pct, view.pnl_r),
                _format_pct(view.exit_distance),
                _format_pct(view.stop_distance),
                _format_pct(view.risk_share, decimals=0),
                ", ".join(view.notes),
            )
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                # Every cell, not only Status: the M87 fix is "elide with an
                # ellipsis and keep the full text one hover away", and a
                # narrow Entry or Risk column truncates exactly as easily as
                # a narrow Reason column does.
                item.setToolTip(text)
                if col in _POSITIONS_NUMERIC_COLUMNS:
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                    )
                if col == _POSITIONS_PNL_COLUMN and view.pnl_pct is not None:
                    colour = theme.SUCCESS if view.pnl_pct >= 0 else theme.DANGER
                    item.setForeground(QColor(colour))
                if col == _POSITIONS_STATUS_COLUMN and "no stop resting" in view.notes:
                    # The alarming blocker, coloured the same as the adopted
                    # panel's own DANGER state - both say the same thing:
                    # unknown protection is treated as none.
                    item.setForeground(QColor(theme.DANGER))
                table.setItem(row, col, item)

    async def _on_regime(self, event: RegimeEvent) -> None:
        self.regime_header.setText(f"Regime: {event.label} (scalar={event.exposure_scalar:.2f})")
        top_probs = sorted(event.probs.items(), key=lambda kv: kv[1], reverse=True)[:3]
        summary = ", ".join(f"{label}={prob:.0%}" for label, prob in top_probs)
        self.ai_note_label.setText(
            f"Current regime is '{event.label}' (top probabilities: {summary}). "
            "Review the Regime Monitor for full detail before adjusting exposure."
        )
        self.review_button.setText("Review && Apply")

    def _on_review_clicked(self) -> None:
        # Explicit human action; never triggers a trade - just acknowledges
        # the note has been reviewed (spec §K: "Review & Apply, never auto-apply").
        self.review_button.setText("Reviewed ✓")

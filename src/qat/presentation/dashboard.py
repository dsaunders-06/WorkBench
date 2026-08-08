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
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from qat.domain.events import RegimeEvent
from qat.domain.oms.adopted import assess_adopted_positions
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
        self.equity_curve = self.equity_plot.plot(pen="y")
        layout.addWidget(self.equity_plot)

        # After the curve exists, and the position is load-bearing (M56a).
        # This ran at the top of __init__ beside the two lists it fills, which
        # read naturally and was wrong: the seed also DRAWS, and the thing it
        # draws onto is created here. Against an empty data directory the draw
        # sits behind a falsy `if` and never runs, so every test passed while
        # the app could not start on any machine with recorded history.
        self._seed_equity_history()

        layout.addWidget(QLabel("Positions"))
        self.positions_table = QTableWidget(0, 3)
        self.positions_table.setHorizontalHeaderLabels(["Symbol", "Quantity", "Avg Price"])
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

        self.positions_table.setRowCount(len(positions))
        for row, position in enumerate(positions):
            self.positions_table.setItem(row, 0, QTableWidgetItem(position.symbol))
            self.positions_table.setItem(row, 1, QTableWidgetItem(f"{position.quantity:g}"))
            self.positions_table.setItem(row, 2, QTableWidgetItem(f"{position.avg_price:.2f}"))

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

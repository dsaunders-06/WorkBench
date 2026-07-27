"""Dashboard (spec §K): KPI tiles, equity curve, positions table, and an
AI regime-note panel with an explicit Review & Apply action - the AI
proposes, the human disposes; nothing here auto-applies anything.
"""

from __future__ import annotations

import asyncio
import logging

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
from qat.presentation.balances_panel import BalancesPanel
from qat.presentation.runtime import Runtime
from qat.presentation.session_panel import SessionPanel
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

        layout = QVBoxLayout(self)

        # Above the regime header on purpose: whether the market is even open
        # is the first thing that makes the rest of this screen meaningful.
        self.session_panel = SessionPanel(
            runtime.session_controller, market=runtime.settings.market
        )
        layout.addWidget(self.session_panel)

        self.regime_header = QLabel("Regime: (waiting for data...)")
        self.regime_header.setStyleSheet("font-size: 14px; font-weight: bold;")
        layout.addWidget(self.regime_header)

        # The balances panel replaces the old NAV tile (M21). Showing both
        # would put two numbers for the same money on one screen and invite the
        # question of why they differ - they do not.
        self.balances_panel = BalancesPanel(runtime.settings.min_cash_reserve)
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

        self.equity_plot = pg.PlotWidget(title="Equity Curve")
        self.equity_plot.setLabel("left", "NAV")
        self.equity_curve = self.equity_plot.plot(pen="y")
        layout.addWidget(self.equity_plot)

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
        if len(self._equity_history) > _MAX_EQUITY_POINTS:
            del self._equity_history[: len(self._equity_history) - _MAX_EQUITY_POINTS]
        self.equity_curve.setData(self._equity_history)

        if len(self._equity_history) >= 2:
            peak = max(self._equity_history)
            current = self._equity_history[-1]
            drawdown_pct = (peak - current) / peak if peak > 0 else 0.0
            limit_pct = self.runtime.settings.max_drawdown_limit_pct
            self.drawdown_tile.set_value(
                f"{drawdown_pct:.2%} / {limit_pct:.0%}",
                color="#d9534f" if drawdown_pct >= limit_pct else "#5cb85c",
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

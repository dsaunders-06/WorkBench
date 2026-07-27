"""Risk Console (spec §K): live VaR/ES/exposure/limit-utilisation tiles, a
simple correlation table, and the kill-switch - always visible, one click
to trip or reset (spec §H/§18.2). It overrides every strategy and the AI
layer and cannot be hidden.
"""

from __future__ import annotations

import pandas as pd
from PySide6.QtCore import QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from qat.domain.events import MarketDataEvent
from qat.presentation.runtime import Runtime
from qat.presentation.widgets import KpiTile

_REFRESH_INTERVAL_MS = 2000
_CORRELATION_WINDOW = 60
_MIN_POINTS_FOR_CORRELATION = 5

_TRIPPED_STYLE = "background-color: #b71c1c; color: white; font-weight: bold; padding: 10px;"
_ACTIVE_STYLE = "background-color: #1b5e20; color: white; font-weight: bold; padding: 10px;"


class RiskConsoleScreen(QWidget):
    def __init__(self, runtime: Runtime, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.runtime = runtime
        self._price_history: dict[str, list[float]] = {symbol: [] for symbol in runtime.watchlist}

        layout = QVBoxLayout(self)

        self.kill_switch_button = QPushButton()
        self.kill_switch_button.clicked.connect(self._on_kill_switch_clicked)
        layout.addWidget(self.kill_switch_button)
        self._refresh_kill_switch_button()

        kpi_row = QHBoxLayout()
        self.var95_tile = KpiTile("Portfolio VaR (95%)")
        self.var99_tile = KpiTile("Portfolio VaR (99%)")
        self.es_tile = KpiTile("Expected Shortfall (97.5%)")
        self.concentration_tile = KpiTile("Single-name concentration")
        for tile in (self.var95_tile, self.var99_tile, self.es_tile, self.concentration_tile):
            kpi_row.addWidget(tile)
        layout.addLayout(kpi_row)

        layout.addWidget(QLabel("Correlation (trailing window)"))
        self.correlation_table = QTableWidget(len(runtime.watchlist), len(runtime.watchlist))
        self.correlation_table.setHorizontalHeaderLabels(list(runtime.watchlist))
        self.correlation_table.setVerticalHeaderLabels(list(runtime.watchlist))
        layout.addWidget(self.correlation_table)

        self.runtime.bus.subscribe(MarketDataEvent, self._on_market_data)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_timer_tick)
        self._timer.start(_REFRESH_INTERVAL_MS)

    def _on_timer_tick(self) -> None:
        self._refresh_from_audit_log()
        self._refresh_correlation_table()

    async def _on_market_data(self, event: MarketDataEvent) -> None:
        """Only buffers the price - recomputing correlations here would run
        an O(n^2) pandas pass on every tick of every symbol (i.e. O(n^3) work
        per second), which saturated the event loop at larger watchlist sizes.
        The 2s timer does the actual refresh instead."""
        history = self._price_history.get(event.symbol)
        if history is None:
            return
        history.append(event.price)
        if len(history) > _CORRELATION_WINDOW:
            del history[: len(history) - _CORRELATION_WINDOW]

    def _refresh_correlation_table(self) -> None:
        symbols = [
            symbol
            for symbol in self.runtime.watchlist
            if len(self._price_history[symbol]) > _MIN_POINTS_FOR_CORRELATION
        ]
        if len(symbols) < 2:
            return

        # Truncate to the shortest history so rows line up positionally, then
        # let pandas compute the whole matrix in one vectorised pass rather
        # than doing an individual concat+corr per symbol pair.
        length = min(len(self._price_history[symbol]) for symbol in symbols)
        frame = pd.DataFrame({symbol: self._price_history[symbol][-length:] for symbol in symbols})
        # .to_numpy() once, then index positionally: pandas' .at[] scalar
        # lookup costs ~40us, which dominated everything else at n^2 cells.
        matrix = frame.pct_change().corr().to_numpy()

        index_by_symbol = {symbol: i for i, symbol in enumerate(self.runtime.watchlist)}
        for matrix_row, row_symbol in enumerate(symbols):
            row = index_by_symbol[row_symbol]
            for matrix_col, col_symbol in enumerate(symbols):
                corr = matrix[matrix_row, matrix_col]
                if pd.isna(corr):
                    continue
                # Reuse the existing cell widget: allocating a fresh
                # QTableWidgetItem per cell on every refresh dominated the
                # cost on large watchlists (n^2 allocations each tick).
                col = index_by_symbol[col_symbol]
                item = self.correlation_table.item(row, col)
                if item is None:
                    item = QTableWidgetItem()
                    self.correlation_table.setItem(row, col, item)
                item.setText(f"{corr:.2f}")
                intensity = int(abs(corr) * 200)
                item.setBackground(
                    QColor(255, 255 - intensity, 255 - intensity)
                    if corr >= 0
                    else QColor(255 - intensity, 255 - intensity, 255)
                )

    def _refresh_from_audit_log(self) -> None:
        entries = self.runtime.risk_engine.audit_log.entries()
        if not entries:
            return
        portfolio_check = entries[-1].inputs.get("portfolio_check")
        if not portfolio_check:
            return
        self.var95_tile.set_value(f"{portfolio_check['var_95']:.2%}")
        self.var99_tile.set_value(f"{portfolio_check['var_99']:.2%}")
        es_limit = self.runtime.settings.portfolio_es_limit_pct
        es_value = portfolio_check["es_975"]
        self.es_tile.set_value(
            f"{es_value:.2%} / {es_limit:.0%}",
            color="#d9534f" if es_value >= es_limit else "#5cb85c",
        )
        self.concentration_tile.set_value(f"{portfolio_check['single_name_pct']:.2%}")

    def _refresh_kill_switch_button(self) -> None:
        if self.runtime.kill_switch.tripped:
            self.kill_switch_button.setText(
                f"KILL-SWITCH TRIPPED ({self.runtime.kill_switch.reason}) - click to reset"
            )
            self.kill_switch_button.setStyleSheet(_TRIPPED_STYLE)
        else:
            self.kill_switch_button.setText("KILL-SWITCH: inactive - click to halt trading")
            self.kill_switch_button.setStyleSheet(_ACTIVE_STYLE)

    def _on_kill_switch_clicked(self) -> None:
        """Toggle the switch AND announce it.

        This screen used to mutate the shared KillSwitch and repaint only its
        own button, so halting from here left the main window's banner reading
        AUTO-TRADE ACTIVE and resetting left it reading HALTED. The state was
        right and every other view of it was wrong.
        """
        operator = "operator (risk console)"
        if self.runtime.kill_switch.tripped:
            self.runtime.kill_switch.reset(operator)
        else:
            self.runtime.kill_switch.trigger_manual(operator)
        # Every other view of the switch now updates through its listeners, so
        # this screen no longer has to remember to announce what it did.
        self._refresh_kill_switch_button()

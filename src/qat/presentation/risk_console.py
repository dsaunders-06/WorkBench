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
        self._price_history: dict[str, list[float]] = dict.fromkeys(runtime.watchlist, [])
        self._price_history = {symbol: [] for symbol in runtime.watchlist}

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
        self._timer.timeout.connect(self._refresh_from_audit_log)
        self._timer.start(_REFRESH_INTERVAL_MS)

    async def _on_market_data(self, event: MarketDataEvent) -> None:
        if event.symbol not in self._price_history:
            return
        history = self._price_history[event.symbol]
        history.append(event.price)
        if len(history) > _CORRELATION_WINDOW:
            del history[: len(history) - _CORRELATION_WINDOW]
        self._refresh_correlation_table()

    def _refresh_correlation_table(self) -> None:
        symbols = list(self.runtime.watchlist)
        series = {
            symbol: pd.Series(self._price_history[symbol]).pct_change().dropna()
            for symbol in symbols
            if len(self._price_history[symbol]) > _MIN_POINTS_FOR_CORRELATION
        }
        for row, row_symbol in enumerate(symbols):
            for col, col_symbol in enumerate(symbols):
                if row_symbol not in series or col_symbol not in series:
                    continue
                aligned = pd.concat([series[row_symbol], series[col_symbol]], axis=1).dropna()
                if len(aligned) < _MIN_POINTS_FOR_CORRELATION:
                    continue
                corr = aligned.iloc[:, 0].corr(aligned.iloc[:, 1])
                if pd.isna(corr):
                    continue
                item = QTableWidgetItem(f"{corr:.2f}")
                intensity = int(abs(corr) * 200)
                color = (
                    QColor(255, 255 - intensity, 255 - intensity)
                    if corr >= 0
                    else QColor(255 - intensity, 255 - intensity, 255)
                )
                item.setBackground(color)
                self.correlation_table.setItem(row, col, item)

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
        if self.runtime.kill_switch.tripped:
            self.runtime.kill_switch.reset("operator (risk console)")
        else:
            self.runtime.kill_switch.trigger_manual("operator (risk console)")
        self._refresh_kill_switch_button()

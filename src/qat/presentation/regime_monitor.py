"""Regime Monitor (spec §E/§K): current regime + probability bars, a
feature-driver table (benchmark price and the macro series feeding the
fusion model), and a scrolling transition history.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QLabel,
    QListWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from qat.domain.events import MacroEvent, MarketDataEvent, RegimeEvent
from qat.domain.regime import ALL_REGIMES
from qat.presentation.runtime import Runtime
from qat.presentation.widgets import ProbabilityBar

_MAX_HISTORY_ROWS = 200


class RegimeMonitorScreen(QWidget):
    def __init__(self, runtime: Runtime, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.runtime = runtime
        self._current_label: str | None = None
        self._driver_values: dict[str, float] = {}

        layout = QVBoxLayout(self)

        self.regime_label = QLabel("Regime: (waiting for data...)")
        self.regime_label.setStyleSheet("font-size: 16px; font-weight: bold;")
        layout.addWidget(self.regime_label)

        self.probability_bars: dict[str, ProbabilityBar] = {}
        for regime in sorted(r.value for r in ALL_REGIMES):
            bar = ProbabilityBar(regime)
            self.probability_bars[regime] = bar
            layout.addWidget(bar)

        layout.addWidget(QLabel("Feature drivers"))
        self.driver_table = QTableWidget(0, 2)
        self.driver_table.setHorizontalHeaderLabels(["Driver", "Value"])
        layout.addWidget(self.driver_table)

        layout.addWidget(QLabel("Transition history"))
        self.history_list = QListWidget()
        layout.addWidget(self.history_list)

        self.runtime.bus.subscribe(RegimeEvent, self._on_regime)
        self.runtime.bus.subscribe(MacroEvent, self._on_macro)
        self.runtime.bus.subscribe(MarketDataEvent, self._on_market_data)

    async def _on_regime(self, event: RegimeEvent) -> None:
        self.regime_label.setText(
            f"Regime: {event.label} (exposure scalar={event.exposure_scalar:.2f})"
        )
        for label, prob in event.probs.items():
            bar = self.probability_bars.get(label)
            if bar is not None:
                bar.set_probability(prob)

        if event.label != self._current_label:
            self._current_label = event.label
            self.history_list.insertItem(0, f"{event.ts:%Y-%m-%d %H:%M:%S} UTC  ->  {event.label}")
            while self.history_list.count() > _MAX_HISTORY_ROWS:
                self.history_list.takeItem(self.history_list.count() - 1)

    async def _on_macro(self, event: MacroEvent) -> None:
        self._driver_values[event.series] = event.value
        self._refresh_driver_table()

    async def _on_market_data(self, event: MarketDataEvent) -> None:
        if event.symbol != self.runtime.benchmark_symbol:
            return
        self._driver_values[f"{event.symbol} (benchmark) price"] = event.price
        self._refresh_driver_table()

    def _refresh_driver_table(self) -> None:
        rows = sorted(self._driver_values.items())
        self.driver_table.setRowCount(len(rows))
        for row, (name, value) in enumerate(rows):
            self.driver_table.setItem(row, 0, QTableWidgetItem(name))
            self.driver_table.setItem(row, 1, QTableWidgetItem(f"{value:.4f}"))

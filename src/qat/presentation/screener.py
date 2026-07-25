"""Screener (spec §K/M10): fundamental + technical universe screening,
read-only/informational by design - it never edits the tradable watchlist
itself (that stays a restart-required Settings change, per M10's
design). Promoting a screened symbol into the watchlist is a manual step of
adding it to Settings' curated list.

Runs against the same synthetic universe used throughout the app: candidate
tickers from qat.data.universe, fundamentals from the runtime's own
MockFundamentalsSource (already used by the live StrategyEngine - no new
fundamentals plumbing needed), and a technical trend read via
synthetic_bars.generate_daily_bars + the existing compute_trend feature
(qat.data.features) rather than reinventing an SMA comparison.
"""

from __future__ import annotations

import asyncio

from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from qat.data import universe
from qat.data.features import compute_trend
from qat.data.fundamentals import SECTORS
from qat.presentation.runtime import Runtime
from qat.presentation.synthetic_bars import generate_daily_bars

_MARKETS = ("US", "ASX")
_CATEGORIES = ("curated", "etf", "megacap")
_TREND_BARS = 40
_TREND_WINDOW = 20
_TREND_FLAT_THRESHOLD = 0.005
_COLUMNS = (
    "Symbol",
    "Sector",
    "Price",
    "Avg Volume",
    "EPS Growth",
    "PEG",
    "Div Yield",
    "ROE",
    "Trend",
)


class ScreenerScreen(QWidget):
    def __init__(self, runtime: Runtime, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.runtime = runtime

        layout = QVBoxLayout(self)

        filters = QFormLayout()
        filter_row = QHBoxLayout()

        self.market_combo = QComboBox()
        for market in _MARKETS:
            self.market_combo.addItem(market)
        self.market_combo.setCurrentText(runtime.settings.market)

        self.category_combo = QComboBox()
        for category in _CATEGORIES:
            self.category_combo.addItem(category)
        self.category_combo.setCurrentText(runtime.settings.watchlist_category)

        self.sector_combo = QComboBox()
        self.sector_combo.addItem("All")
        for sector in SECTORS:
            self.sector_combo.addItem(sector)

        filter_row.addWidget(QLabel("Market:"))
        filter_row.addWidget(self.market_combo)
        filter_row.addWidget(QLabel("Category:"))
        filter_row.addWidget(self.category_combo)
        filter_row.addWidget(QLabel("Sector:"))
        filter_row.addWidget(self.sector_combo)
        filters.addRow(filter_row)

        threshold_row = QHBoxLayout()

        self.min_eps_growth_input = QDoubleSpinBox()
        self.min_eps_growth_input.setRange(-50.0, 100.0)
        self.min_eps_growth_input.setSuffix("%")
        self.min_eps_growth_input.setValue(-50.0)

        self.max_peg_input = QDoubleSpinBox()
        self.max_peg_input.setRange(0.0, 10.0)
        self.max_peg_input.setValue(10.0)

        self.min_div_yield_input = QDoubleSpinBox()
        self.min_div_yield_input.setRange(0.0, 10.0)
        self.min_div_yield_input.setSuffix("%")
        self.min_div_yield_input.setValue(0.0)

        self.min_avg_volume_input = QSpinBox()
        self.min_avg_volume_input.setRange(0, 1_000_000_000)
        self.min_avg_volume_input.setSingleStep(10_000)
        self.min_avg_volume_input.setValue(runtime.settings.watchlist_min_avg_volume)

        threshold_row.addWidget(QLabel("Min EPS growth:"))
        threshold_row.addWidget(self.min_eps_growth_input)
        threshold_row.addWidget(QLabel("Max PEG:"))
        threshold_row.addWidget(self.max_peg_input)
        threshold_row.addWidget(QLabel("Min div. yield:"))
        threshold_row.addWidget(self.min_div_yield_input)
        threshold_row.addWidget(QLabel("Min avg. volume:"))
        threshold_row.addWidget(self.min_avg_volume_input)
        filters.addRow(threshold_row)

        layout.addLayout(filters)

        self.run_button = QPushButton("Run Screen")
        self.run_button.clicked.connect(self._on_run_clicked)
        layout.addWidget(self.run_button)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.results_table = QTableWidget(0, len(_COLUMNS))
        self.results_table.setHorizontalHeaderLabels(list(_COLUMNS))
        layout.addWidget(self.results_table)

    def _on_run_clicked(self) -> None:
        asyncio.ensure_future(self._run_screen())

    def _candidate_symbols(self) -> tuple[str, ...]:
        market = self.market_combo.currentText()
        category = self.category_combo.currentText()
        if category == "curated":
            return (
                self.runtime.settings.watchlist_curated_us_tuple
                if market == "US"
                else self.runtime.settings.watchlist_curated_asx_tuple
            )
        return universe.MARKET_WATCHLISTS[market][category]  # type: ignore[index]

    async def _run_screen(self) -> None:
        self.run_button.setEnabled(False)
        self.status_label.setText("Screening...")
        try:
            symbols = self._candidate_symbols()
            sector_filter = self.sector_combo.currentText()
            min_eps_growth = self.min_eps_growth_input.value() / 100.0
            max_peg = self.max_peg_input.value()
            min_div_yield = self.min_div_yield_input.value() / 100.0
            min_avg_volume = self.min_avg_volume_input.value()

            rows: list[tuple[str, str, float, int, float, float, float, float, str]] = []
            for symbol in symbols:
                avg_volume = universe.average_daily_volume(symbol)
                if avg_volume < min_avg_volume:
                    continue

                fundamentals = (
                    await self.runtime.strategy_engine.fundamentals_source.get_fundamentals(symbol)
                )
                if sector_filter != "All" and fundamentals.sector != sector_filter:
                    continue
                if fundamentals.eps_growth_yoy < min_eps_growth:
                    continue
                if fundamentals.peg_ratio > max_peg:
                    continue
                if fundamentals.dividend_yield < min_div_yield:
                    continue

                bars = await generate_daily_bars(symbol, n_bars=_TREND_BARS)
                price = float(bars["close"].iloc[-1])
                trend_pct = compute_trend(bars["close"], window=_TREND_WINDOW).iloc[-1]
                trend = _trend_label(trend_pct)

                rows.append(
                    (
                        symbol,
                        fundamentals.sector,
                        price,
                        avg_volume,
                        fundamentals.eps_growth_yoy,
                        fundamentals.peg_ratio,
                        fundamentals.dividend_yield,
                        fundamentals.roe,
                        trend,
                    )
                )

            self._render_results(rows)
            self.status_label.setText(f"{len(rows)} of {len(symbols)} candidates matched.")
        finally:
            self.run_button.setEnabled(True)

    def _render_results(
        self, rows: list[tuple[str, str, float, int, float, float, float, float, str]]
    ) -> None:
        self.results_table.setRowCount(len(rows))
        for row_index, (symbol, sector, price, avg_volume, eps, peg, div, roe, trend) in enumerate(
            rows
        ):
            values = (
                symbol,
                sector,
                f"{price:.2f}",
                f"{avg_volume:,}",
                f"{eps:.2%}",
                f"{peg:.2f}",
                f"{div:.2%}",
                f"{roe:.2%}",
                trend,
            )
            for col_index, value in enumerate(values):
                self.results_table.setItem(row_index, col_index, QTableWidgetItem(value))


def _trend_label(trend_pct: float) -> str:
    if trend_pct != trend_pct:  # NaN - not enough history for the SMA window
        return "-"
    if trend_pct > _TREND_FLAT_THRESHOLD:
        return "Up"
    if trend_pct < -_TREND_FLAT_THRESHOLD:
        return "Down"
    return "Flat"

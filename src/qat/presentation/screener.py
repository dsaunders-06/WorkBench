"""Screener (spec §K/M10): fundamental + technical universe screening,
read-only/informational by design - it never edits the tradable watchlist
itself (that stays a restart-required Settings change, per M10's
design). Promoting a screened symbol into the watchlist is a manual step of
adding it to Settings' curated list.

Candidate tickers come from qat.data.universe, fundamentals from the runtime's
own MockFundamentalsSource (already used by the live StrategyEngine - no new
fundamentals plumbing needed), and the technical trend read from
runtime.history_source + the existing compute_trend feature (qat.data.features)
rather than reinventing an SMA comparison.

Since M14 the bars behind that trend column are real when the app is
configured for real market data, and synthetic otherwise - the screen does not
choose, it uses whatever the runtime resolved. Fundamentals remain mock in
both cases; no fundamentals vendor is wired up.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

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

from qat.data import instruments, universe
from qat.data.features import compute_trend
from qat.data.fundamentals import SECTORS
from qat.presentation.runtime import Runtime

logger = logging.getLogger(__name__)

_MARKETS = ("US", "ASX")
_CATEGORIES = ("curated", "etf", "megacap")
_TREND_BARS = 40
_TREND_WINDOW = 20
_TREND_FLAT_THRESHOLD = 0.005
NOT_AVAILABLE = "—"  # em dash: this figure does not exist, as against a measured zero
_COLUMNS = (
    "Symbol",
    "Name",
    "Sector",
    "Price",
    "Avg Volume",
    "EPS Growth",
    "PEG",
    "Div Yield",
    "ROE",
    "Trend",
)


@dataclass(frozen=True, slots=True)
class ScreenResult:
    """One screened row. A dataclass rather than a positional tuple because the
    row carries ten fields and the render step unpacks them in order - a
    mismatch between build and render would be a silent column shift."""

    symbol: str
    name: str
    sector: str
    price: float
    avg_volume: int
    # Optional since M18: a real vendor cannot answer every field for every
    # symbol, and an index ETF has no earnings growth or return on equity.
    eps_growth_yoy: float | None
    peg_ratio: float | None
    dividend_yield: float | None
    roe: float | None
    trend: str


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
            # A threshold sitting on its own widest bound is "no filter", and
            # is read off the widget rather than hard-coded so the two cannot
            # drift apart.
            eps_off = self.min_eps_growth_input.value() <= self.min_eps_growth_input.minimum()
            peg_off = self.max_peg_input.value() >= self.max_peg_input.maximum()
            yield_off = self.min_div_yield_input.value() <= self.min_div_yield_input.minimum()

            rows: list[ScreenResult] = []
            for symbol in symbols:
                avg_volume = universe.average_daily_volume(symbol)
                if avg_volume < min_avg_volume:
                    continue

                fundamentals = (
                    await self.runtime.strategy_engine.fundamentals_source.get_fundamentals(symbol)
                )
                if sector_filter != "All" and fundamentals.sector != sector_filter:
                    continue
                # A symbol that cannot answer a filter you have set does not
                # match it - an ETF with no EPS growth is not a company growing
                # at 15%. But a filter parked at its widest setting is not a
                # filter, and dropping every ETF from the default view would
                # look like a bug rather than a screen. So: unanswerable fails,
                # unless the threshold is disengaged.
                if _excluded(fundamentals.eps_growth_yoy, min_eps_growth, eps_off, above=True):
                    continue
                if _excluded(fundamentals.peg_ratio, max_peg, peg_off, above=False):
                    continue
                if _excluded(fundamentals.dividend_yield, min_div_yield, yield_off, above=True):
                    continue

                bars = await self.runtime.history_source.get_daily_bars(symbol, n_bars=_TREND_BARS)
                price = float(bars["close"].iloc[-1])
                trend_pct = compute_trend(bars["close"], window=_TREND_WINDOW).iloc[-1]
                trend = _trend_label(trend_pct)

                rows.append(
                    ScreenResult(
                        symbol=symbol,
                        name=instruments.name_for(symbol),
                        sector=fundamentals.sector,
                        price=price,
                        avg_volume=avg_volume,
                        eps_growth_yoy=fundamentals.eps_growth_yoy,
                        peg_ratio=fundamentals.peg_ratio,
                        dividend_yield=fundamentals.dividend_yield,
                        roe=fundamentals.roe,
                        trend=trend,
                    )
                )

            self._render_results(rows)
            self.status_label.setText(f"{len(rows)} of {len(symbols)} candidates matched.")
        except Exception as exc:  # noqa: BLE001 - surfaced to the user below
            logger.exception("Screener run failed")
            self.status_label.setText(f"Screen failed: {exc}")
        finally:
            self.run_button.setEnabled(True)

    def _render_results(self, rows: list[ScreenResult]) -> None:
        self.results_table.setRowCount(len(rows))
        for row_index, result in enumerate(rows):
            values = (
                result.symbol,
                result.name,
                result.sector,
                f"{result.price:.2f}",
                f"{result.avg_volume:,}",
                _percent(result.eps_growth_yoy),
                _number(result.peg_ratio),
                _percent(result.dividend_yield),
                _percent(result.roe),
                result.trend,
            )
            for col_index, value in enumerate(values):
                self.results_table.setItem(row_index, col_index, QTableWidgetItem(value))
        self.results_table.resizeColumnsToContents()


def _excluded(value: float | None, threshold: float, disengaged: bool, *, above: bool) -> bool:
    """Should this symbol be dropped for failing the threshold?

    `above=True` means the value must be at least the threshold.
    """
    if disengaged:
        return False
    if value is None:
        return True  # unanswerable is not a match
    return value < threshold if above else value > threshold


def _percent(value: float | None) -> str:
    """Missing renders as an em dash, never 0.00%.

    Zero is a measurement - a company that paid no dividend. Showing it for an
    ETF that simply has no figure would make the two indistinguishable.
    """
    return NOT_AVAILABLE if value is None else f"{value:.2%}"


def _number(value: float | None) -> str:
    return NOT_AVAILABLE if value is None else f"{value:.2f}"


def _trend_label(trend_pct: float) -> str:
    if trend_pct != trend_pct:  # NaN - not enough history for the SMA window
        return "-"
    if trend_pct > _TREND_FLAT_THRESHOLD:
        return "Up"
    if trend_pct < -_TREND_FLAT_THRESHOLD:
        return "Down"
    return "Flat"

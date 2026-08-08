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
choose, it uses whatever the runtime resolved.

Fundamentals are real when `fundamentals_source` is "yfinance" and seeded
synthetic otherwise, which is still the DEFAULT - and `resolve_fundamentals_source`
degrades to the same synthetic source when the real one cannot be built. The
screen says which it got (M72): every snapshot has carried `is_synthetic` since
M18, for exactly the reason its own docstring gives - "so anything downstream
that displays or reasons about a number can say where it came from" - and this
screen displayed nine fundamental columns without ever asking.
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
from qat.presentation.ui_level import UiLevel

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
    # Whether the four figures above were INVENTED (M72). Carried per row
    # rather than asked of the source once, because that is how the snapshot
    # carries it - a run can mix a cached real snapshot with a synthetic one
    # after the vendor is lost mid-session.
    is_synthetic: bool = False


@dataclass(frozen=True, slots=True)
class _Preset:
    """A named screen, and what it means in words (M72).

    The filters are raw factor inputs - a PEG spinbox says nothing about what a
    PEG of 1.5 implies - so every preset carries the sentence that explains the
    threshold it sets, not merely a label for it. A named preset with no
    explanation moves the problem rather than solving it.

    `None` means "park that filter at its widest bound", which the run already
    reads as disengaged.
    """

    name: str
    summary: str
    min_eps_growth: float | None = None
    max_peg: float | None = None
    min_div_yield: float | None = None


CUSTOM_PRESET = "Custom"
_PRESETS = (
    _Preset(
        name="All candidates",
        summary=(
            "Every symbol in the chosen category, with no fundamental filter applied. "
            "The volume and sector filters above still apply."
        ),
    ),
    _Preset(
        name="Steady dividend payers",
        summary=(
            "Pays a dividend of at least 2.5% of the share price a year. Says nothing "
            "about whether the dividend is affordable or growing - a high yield is "
            "sometimes a falling share price rather than a generous company."
        ),
        min_div_yield=2.5,
    ),
    _Preset(
        name="High growth",
        summary=(
            "Earnings per share at least 15% higher than a year ago. Growth is measured "
            "backwards: it says what the company has done, not what it will do, and fast "
            "growers are usually priced as though it continues."
        ),
        min_eps_growth=15.0,
    ),
    _Preset(
        name="Growth at a reasonable price",
        summary=(
            "Earnings growing at least 10% a year, at a PEG of 2.0 or less. PEG divides "
            "the price-to-earnings ratio by the growth rate, so it asks whether you are "
            "paying a fair price FOR that growth - conventionally under 1 is cheap and "
            "over 2 is dear."
        ),
        min_eps_growth=10.0,
        max_peg=2.0,
    ),
)


class ScreenerScreen(QWidget):
    def __init__(self, runtime: Runtime, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.runtime = runtime
        self.level = UiLevel.from_settings(runtime.settings)
        # Set while a preset writes the spinboxes, so their valueChanged does
        # not immediately report the result as "Custom".
        self._applying_preset = False

        layout = QVBoxLayout(self)

        preset_row = QHBoxLayout()
        self.preset_combo = QComboBox()
        for preset in _PRESETS:
            self.preset_combo.addItem(preset.name)
        self.preset_combo.addItem(CUSTOM_PRESET)
        self.preset_combo.currentTextChanged.connect(self._on_preset_changed)
        self.preset_label = QLabel("Screen:")
        preset_row.addWidget(self.preset_label)
        preset_row.addWidget(self.preset_combo)
        preset_row.addStretch(1)
        self.preset_row_widget = QWidget()
        self.preset_row_widget.setLayout(preset_row)
        layout.addWidget(self.preset_row_widget)

        self.preset_summary = QLabel("")
        self.preset_summary.setWordWrap(True)
        layout.addWidget(self.preset_summary)

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
        # A trailing stretch and its own widget, so the form layout does not
        # spread three combos across the full window with the labels stranded
        # from the controls they name. Found by rendering it, which is the only
        # way this class of defect gets found - every test passed through it.
        filter_row.addStretch(1)
        self.filter_row_widget = QWidget()
        self.filter_row_widget.setLayout(filter_row)
        filters.addRow(self.filter_row_widget)

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
        threshold_row.addStretch(1)
        self.threshold_row_widget = QWidget()
        self.threshold_row_widget.setLayout(threshold_row)
        filters.addRow(self.threshold_row_widget)

        # After the widgets exist, so editing one can report "Custom".
        for spin in (self.min_eps_growth_input, self.max_peg_input, self.min_div_yield_input):
            spin.valueChanged.connect(self._on_threshold_edited)

        layout.addLayout(filters)

        self.run_button = QPushButton("Run Screen")
        self.run_button.clicked.connect(self._on_run_clicked)
        layout.addWidget(self.run_button)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        # Where the nine fundamental columns came from. Its own label rather
        # than appended to the status line, because "12 of 40 matched" is about
        # the filters and this is about whether the figures are real - and a
        # run that matches nothing still has to answer it.
        self.provenance_label = QLabel("")
        self.provenance_label.setWordWrap(True)
        layout.addWidget(self.provenance_label)

        self.results_table = QTableWidget(0, len(_COLUMNS))
        self.results_table.setHorizontalHeaderLabels(list(_COLUMNS))
        layout.addWidget(self.results_table)

        self._apply_level()
        self._apply_preset(_PRESETS[0])

    def _apply_level(self) -> None:
        """Three levels, three outcomes.

        Guided gets the named screens and nothing else: a raw PEG bound is the
        control §4.8 calls meaningless without knowing what a PEG implies.
        Standard gets both, so a preset can be taken as a starting point and
        then adjusted. Professional gets the raw filters alone - the presets are
        a scaffold it does not need, and density is the point.

        Hidden rather than disabled, per M45: a control that is absent is one
        level away, and the level selector says so.
        """
        self.preset_row_widget.setVisible(not self.level.prefers_density())
        self.preset_label.setVisible(not self.level.prefers_density())
        # The explanation, not the preset. Professional has no preset row to
        # explain, and Standard keeps it because the whole point of a named
        # screen is the sentence under it.
        self.preset_summary.setVisible(self.level.explains())
        self.threshold_row_widget.setVisible(self.level.shows_advanced())

    def _on_preset_changed(self, name: str) -> None:
        preset = next((p for p in _PRESETS if p.name == name), None)
        if preset is None:  # "Custom" - the thresholds are whatever they are
            self.preset_summary.setText(
                "Your own thresholds. Selecting a named screen above replaces them."
            )
            return
        self._apply_preset(preset)

    def _apply_preset(self, preset: _Preset) -> None:
        self._applying_preset = True
        try:
            self.preset_combo.setCurrentText(preset.name)
            # A filter the preset does not set goes back to its widest bound,
            # which the run already reads as disengaged - so switching presets
            # cannot leave a threshold behind from the previous one.
            _set_or_widest(self.min_eps_growth_input, preset.min_eps_growth, widest="minimum")
            _set_or_widest(self.max_peg_input, preset.max_peg, widest="maximum")
            _set_or_widest(self.min_div_yield_input, preset.min_div_yield, widest="minimum")
            self.preset_summary.setText(preset.summary)
        finally:
            self._applying_preset = False

    def _on_threshold_edited(self) -> None:
        """A hand-edited threshold is no longer the named screen it came from.

        Leaving the name in place would be the worse failure: the operator
        would read "Steady dividend payers" above a result set that is no
        longer that screen.
        """
        if self._applying_preset:
            return
        self.preset_combo.setCurrentText(CUSTOM_PRESET)

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
                        is_synthetic=fundamentals.is_synthetic,
                    )
                )

            self._render_results(rows)
            self.status_label.setText(f"{len(rows)} of {len(symbols)} candidates matched.")
            self.provenance_label.setText(_provenance_caption(rows, explains=self.level.explains()))
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


def _set_or_widest(spin: QDoubleSpinBox, value: float | None, *, widest: str) -> None:
    """A preset's threshold, or the bound the run already reads as "no filter"."""
    if value is not None:
        spin.setValue(value)
    elif widest == "minimum":
        spin.setValue(spin.minimum())
    else:
        spin.setValue(spin.maximum())


def _provenance_caption(rows: list[ScreenResult], *, explains: bool) -> str:
    """Where the nine fundamental columns came from (M72).

    `is_synthetic` has ridden on every snapshot since M18, and its own
    docstring gives the reason - "so anything downstream that displays or
    reasons about a number can say where it came from". `available_figures()`
    duly passes it to the LLM, so the AI Advisor has known the provenance of
    these figures all along and the operator reading the table has not.

    Three states, and the middle one is the trap. Synthetic fundamentals are
    the DEFAULT (`fundamentals_source` is "mock" unless set), and
    `resolve_fundamentals_source` falls back to the same seeded source when the
    real one cannot be built - logging that "every fundamental figure shown or
    traded on will be INVENTED" and then rendering a table that looks exactly
    like a real one.

    Loud when invented, quiet when real: a line that reads the same either way
    is the disclaimer M69 replaced. A missing figure is a fourth thing again,
    and is already visible per cell as an em dash - counted here so a table
    that is mostly dashes says so once rather than making the reader scan.
    """
    if not rows:
        return ""
    synthetic = sum(1 for row in rows if row.is_synthetic)
    unanswered = sum(
        1
        for row in rows
        for value in (row.eps_growth_yoy, row.peg_ratio, row.dividend_yield, row.roe)
        if value is None
    )
    parts: list[str] = []

    if synthetic == len(rows):
        parts.append(
            f"⚠ EVERY fundamental figure below is INVENTED - all {len(rows)} row(s) come "
            "from the seeded synthetic source, not from a vendor."
        )
        if explains:
            parts.append(
                "They are internally consistent and repeatable, which makes them useful for "
                "trying the screen out and worthless for choosing a stock. Set the "
                "fundamentals source to a real vendor in Settings to screen on real figures."
            )
    elif synthetic:
        parts.append(
            f"⚠ MIXED provenance: {synthetic} of {len(rows)} row(s) carry INVENTED "
            "fundamentals and the rest are real. Sort by nothing below until that is "
            "resolved - the two are not comparable."
        )
    else:
        parts.append(f"Fundamentals: real vendor figures for all {len(rows)} row(s).")

    if unanswered:
        parts.append(
            f"{unanswered} figure(s) shown as {NOT_AVAILABLE} could not be answered for that "
            "symbol - an ETF has no earnings growth, and a vendor does not publish every "
            "field. That is absent, not zero."
        )
    return " ".join(parts)


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

"""Regime Monitor (spec §E/§K): current regime + probability bars, a
feature-driver table (benchmark price and the macro series feeding the
fusion model), a scrolling transition history, and the macro market-conditions
analysis (M13).

The macro panel is deliberately two-part and shows both parts separately:

* The deterministic read, computed in code by domain.macro_analysis from the
  benchmark's own bars. Always available, never depends on a model.
* The AI's synthesis on top of it, which may fail or be unavailable - in which
  case the deterministic half is still displayed rather than the whole panel
  going blank.

Anything the AI proposes here is displayed as a proposal. This screen never
applies an exposure scalar, never touches RiskEngine, and never reaches OMS.
"""

from __future__ import annotations

import asyncio
import logging

from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from qat.domain.ai_advisory.schema import MacroAssessment
from qat.domain.events import MacroEvent, MarketDataEvent, RegimeEvent
from qat.domain.macro_analysis import compute_macro_signal
from qat.domain.regime import ALL_REGIMES
from qat.presentation.runtime import Runtime
from qat.presentation.widgets import ProbabilityBar

logger = logging.getLogger(__name__)

_MAX_HISTORY_ROWS = 200
_MACRO_BARS = 300


class RegimeMonitorScreen(QWidget):
    def __init__(self, runtime: Runtime, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.runtime = runtime
        self._current_label: str | None = None
        self._regime_probs: dict[str, float] = {}
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

        layout.addWidget(self._build_macro_panel())

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

    def _build_macro_panel(self) -> QGroupBox:
        box = QGroupBox("Macro market conditions")
        box_layout = QVBoxLayout(box)

        control_row = QHBoxLayout()
        self.macro_button = QPushButton("Analyse Market Conditions")
        self.macro_button.clicked.connect(self._on_analyse_clicked)
        control_row.addWidget(self.macro_button)
        control_row.addStretch(1)
        box_layout.addLayout(control_row)

        self.macro_signal_label = QLabel("Deterministic read: (not yet run)")
        self.macro_signal_label.setWordWrap(True)
        self.macro_signal_label.setStyleSheet("font-weight: bold;")
        box_layout.addWidget(self.macro_signal_label)

        self.macro_ai_output = QTextEdit()
        self.macro_ai_output.setReadOnly(True)
        self.macro_ai_output.setMaximumHeight(160)
        self.macro_ai_output.setPlaceholderText(
            "AI synthesis appears here. Anything proposed is advisory only - "
            "this screen never applies an exposure change."
        )
        box_layout.addWidget(self.macro_ai_output)

        return box

    def _on_analyse_clicked(self) -> None:
        asyncio.ensure_future(self._analyse_macro())

    async def _analyse_macro(self) -> None:
        self.macro_button.setEnabled(False)
        self.macro_signal_label.setText("Deterministic read: computing...")
        self.macro_ai_output.clear()
        try:
            benchmark = self.runtime.benchmark_symbol
            bars = await self.runtime.history_source.get_daily_bars(benchmark, n_bars=_MACRO_BARS)
            signal = compute_macro_signal(bars, macro_series=self._macro_series())

            if signal is None:
                self.macro_signal_label.setText(
                    "Deterministic read: not enough benchmark history yet - "
                    "skipped rather than estimated from a short window."
                )
                return

            # Rendered before the AI call, so the measured half is on screen
            # even if the model call then fails or hangs.
            self.macro_signal_label.setText(
                f"Deterministic read ({benchmark}): {signal.summary_line()} "
                f"Exposure hint {signal.exposure_hint:.2f}."
            )

            assessment = await self.runtime.ai_service.get_macro_assessment(
                signal,
                regime_label=self._current_label or "unknown",
                regime_probs=self._regime_probs,
            )
            self._render_assessment(assessment, signal.suggested_regime)
        except Exception as exc:  # noqa: BLE001 - surfaced to the operator below
            logger.exception("Macro analysis failed")
            self.macro_ai_output.setHtml(
                f"<b style='color:#b71c1c'>AI synthesis unavailable:</b> {exc}<br>"
                "The deterministic read above is unaffected. Check the AI provider "
                "settings (Settings tab), then restart the application."
            )
        finally:
            self.macro_button.setEnabled(True)

    def _render_assessment(self, assessment: MacroAssessment, deterministic_regime: str) -> None:
        parts = [
            f"<b>AI read:</b> {assessment.regime.replace('_', '-').title()} "
            f"(confidence {assessment.confidence:.0%})"
        ]
        if assessment.regime != deterministic_regime:
            parts.append(
                "<b style='color:#b45309'>Differs from the deterministic read "
                f"({deterministic_regime.replace('_', '-').title()}).</b>"
            )
        parts.append(assessment.reasoning)
        if assessment.key_insights:
            insights = "".join(f"<li>{item}</li>" for item in assessment.key_insights)
            parts.append(f"<b>Key insights:</b><ul>{insights}</ul>")
        if assessment.risk_flags:
            parts.append(f"<b>Risk flags:</b> {', '.join(assessment.risk_flags)}")
        if assessment.suggested_exposure_scalar is not None:
            parts.append(
                "<b>Proposed exposure scalar:</b> "
                f"{assessment.suggested_exposure_scalar:.2f} "
                "<i>(proposal only - not applied; adjust risk settings yourself "
                "if you agree)</i>"
            )
        self.macro_ai_output.setHtml("<br>".join(parts))

    def _macro_series(self) -> dict[str, float]:
        """The FRED values seen so far, excluding the benchmark price row that
        shares the same driver table."""
        return {
            name: value
            for name, value in self._driver_values.items()
            if not name.endswith("(benchmark) price")
        }

    async def _on_regime(self, event: RegimeEvent) -> None:
        self.regime_label.setText(
            f"Regime: {event.label} (exposure scalar={event.exposure_scalar:.2f})"
        )
        self._regime_probs = event.probs
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

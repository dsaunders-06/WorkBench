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

from qat.domain.ai_advisory.schema import MacroAssessment, MacroMatrixNarrative
from qat.domain.display_dates import format_display_date, format_session_time
from qat.domain.events import MacroEvent, MarketDataEvent, RegimeEvent
from qat.domain.macro_analysis import compute_macro_signal
from qat.domain.macro_analysis.friction import RegimeFriction, compare
from qat.domain.macro_analysis.growth import GrowthRead, read_growth
from qat.domain.macro_analysis.matrix import (
    MatrixRefusal,
    RegimeDecision,
    RegimeHysteresis,
    baseline_from_risk_budget,
    decide,
)
from qat.domain.macro_analysis.signal import MacroSignal, scaling_unit_for
from qat.domain.regime import ALL_REGIMES, Regime
from qat.presentation import theme
from qat.presentation.runtime import Runtime
from qat.presentation.ui_level import UiLevel
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
        # The HMM's own exposure scalar, kept so the matrix panel can state what
        # the engine WITH monetary authority is doing beside its own advisory
        # reading. Read from the event rather than from RiskEngine, for the same
        # ordering reason `_refresh_eligibility` exists.
        self._regime_scalar: float | None = None
        # One gate per screen, held across clicks. `decide` is pure, so a value
        # resting on a boundary would flip the regime every time the button is
        # pressed - a scaled cut against halving the book, decided by noise.
        self._matrix_gate = RegimeHysteresis()

        layout = QVBoxLayout(self)

        self.level = UiLevel.from_settings(runtime.settings)

        self.regime_label = QLabel("Regime: (waiting for data...)")
        self.regime_label.setStyleSheet(theme.text(size=theme.SUBHEAD, bold=True))
        layout.addWidget(self.regime_label)

        # --- What the regime DOES, which the screen never said ------------
        #
        # The label and the bars are the INPUTS. Whether a strategy may trade
        # is the consequence, and it is not the label: since M27b eligibility
        # is probability MASS across a strategy's suitable regimes. An operator
        # reading "Regime: bull" and inferring swing is trading can be wrong in
        # either direction, and a strategy silently ineligible for a session
        # looks exactly like one that found no setup.
        self.eligibility_label = QLabel("Strategies: (waiting for a regime...)")
        self.eligibility_label.setWordWrap(True)
        self.eligibility_label.setStyleSheet(theme.text(size=theme.BODY, bold=True))
        layout.addWidget(self.eligibility_label)

        self.mass_detail = QLabel("")
        self.mass_detail.setWordWrap(True)
        self.mass_detail.setStyleSheet(theme.text(theme.MUTED, size=theme.CAPTION))
        self.mass_detail.setVisible(self.level.shows_advanced())
        layout.addWidget(self.mass_detail)

        self.scalar_sentence = QLabel("")
        self.scalar_sentence.setWordWrap(True)
        self.scalar_sentence.setStyleSheet(theme.text(theme.MUTED, size=theme.CAPTION))
        self.scalar_sentence.setVisible(self.level.explains())
        layout.addWidget(self.scalar_sentence)

        # Names the neighbour rather than deriving a second refusal picture.
        # "Why did nothing happen" usually has a non-regime answer - the
        # position limit or the risk cap - and that question belongs to the
        # Risk Console. Two screens computing one answer is how they drift.
        self.elsewhere_hint = QLabel(
            "This screen covers the regime only. If the regime permits a strategy and "
            "nothing still trades, the reason is a risk rail - see the Risk Console."
        )
        self.elsewhere_hint.setWordWrap(True)
        self.elsewhere_hint.setStyleSheet(theme.text(theme.MUTED, size=theme.CAPTION))
        layout.addWidget(self.elsewhere_hint)

        self.probability_bars: dict[str, ProbabilityBar] = {}
        for regime in sorted(r.value for r in ALL_REGIMES):
            bar = ProbabilityBar(regime)
            self.probability_bars[regime] = bar
            layout.addWidget(bar)

        self.macro_panel = self._build_macro_panel()
        self.macro_panel.setVisible(self.level.shows_advanced())
        layout.addWidget(self.macro_panel)

        self.matrix_panel = self._build_matrix_panel()
        self.matrix_panel.setVisible(self.level.shows_advanced())
        layout.addWidget(self.matrix_panel)

        self.driver_header = QLabel("Feature drivers")
        self.driver_table = QTableWidget(0, 2)
        self.driver_table.setHorizontalHeaderLabels(["Driver", "Value"])
        for widget in (self.driver_header, self.driver_table):
            widget.setVisible(self.level.prefers_density())
            layout.addWidget(widget)

        # Never level-gated. A regime change can switch a strategy off for a
        # session, and this record is how that gets reconstructed afterwards.
        layout.addWidget(QLabel("Transition history"))
        self.history_list = QListWidget()
        layout.addWidget(self.history_list)

        self.runtime.bus.subscribe(RegimeEvent, self._on_regime)
        self.runtime.bus.subscribe(MacroEvent, self._on_macro)
        self.runtime.bus.subscribe(MarketDataEvent, self._on_market_data)
        # Not a bus subscription: the engine tells us once it has finished
        # reading the regime, so we can never render a verdict it has not made
        # yet. See StrategyEngine.add_eligibility_listener.
        self.runtime.strategy_engine.add_eligibility_listener(self._refresh_eligibility)

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
        self.macro_signal_label.setStyleSheet(theme.text(bold=True))
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

    def _build_matrix_panel(self) -> QGroupBox:
        """The 7-regime matrix, kept SEPARATE from the 4-regime read above.

        TWO BUTTONS ON PURPOSE. Running both from one click would spend two
        model calls per press, and the two readings answer different questions -
        the panel above classifies the tape into four states, this one runs the
        volatility-and-growth rule table and states an exposure target. An
        operator should choose which one to spend a call on.

        ADVISORY, and the panel title says so rather than a tooltip. Operator
        instruction, 8 September 2026: "this sits outside of the authority of
        autonomy, resultant action must be human driven only for now." Nothing
        on this panel reaches `RiskEngine.regime_scalar`, the sizer, or OMS.
        """
        box = QGroupBox("Regime matrix - 7 regimes (advisory, nothing is applied)")
        box_layout = QVBoxLayout(box)

        control_row = QHBoxLayout()
        self.matrix_button = QPushButton("Run Regime Matrix")
        self.matrix_button.clicked.connect(self._on_matrix_clicked)
        control_row.addWidget(self.matrix_button)
        control_row.addStretch(1)
        box_layout.addLayout(control_row)

        self.matrix_decision_label = QLabel("Matrix: (not yet run)")
        self.matrix_decision_label.setWordWrap(True)
        self.matrix_decision_label.setStyleSheet(theme.text(bold=True))
        box_layout.addWidget(self.matrix_decision_label)

        # Its own line, ABOVE the prose. The friction reading is a computed fact
        # and must not be something the reader has to find inside a paragraph.
        self.matrix_friction_label = QLabel("")
        self.matrix_friction_label.setWordWrap(True)
        box_layout.addWidget(self.matrix_friction_label)

        self.matrix_ai_output = QTextEdit()
        self.matrix_ai_output.setReadOnly(True)
        self.matrix_ai_output.setMaximumHeight(180)
        self.matrix_ai_output.setPlaceholderText(
            "The matrix decides the regime and the exposure target in code; the "
            "model only writes them up. Nothing here is applied."
        )
        box_layout.addWidget(self.matrix_ai_output)

        return box

    def _on_matrix_clicked(self) -> None:
        asyncio.ensure_future(self._analyse_matrix())

    async def _analyse_matrix(self) -> None:
        self.matrix_button.setEnabled(False)
        self.matrix_decision_label.setText("Matrix: computing...")
        self.matrix_friction_label.setText("")
        self.matrix_ai_output.clear()
        try:
            signal = await self._matrix_signal()
            if signal is None:
                self.matrix_decision_label.setText(
                    "Matrix: not enough benchmark history yet - refused rather than "
                    "estimated from a short window."
                )
                return

            settings = self.runtime.settings
            decision = self._matrix_gate.settle(
                decide(
                    signal,
                    await self._growth_read(),
                    scaling_unit=scaling_unit_for(settings.macro_risk_mandate),
                    # NOT `signal.exposure_hint`: that is the FOUR-regime read's
                    # answer, and lifting from it stacks two taxonomies. See
                    # `baseline_from_risk_budget`.
                    baseline=baseline_from_risk_budget(
                        settings.max_gap_risk_at_shock_pct, settings.gap_shock_pct
                    ),
                )
            )
            friction = compare(self._execution_regime(), self._regime_scalar, decision)

            # Both rendered BEFORE the model call, so the computed half is on
            # screen even if the model then fails or hangs. Same rule the panel
            # above follows.
            self._render_matrix_decision(decision)
            self._render_friction(friction)

            narrative = await self.runtime.ai_service.get_macro_matrix_narrative(
                decision,
                positions=await self._held_positions(),
                friction=friction,
            )
            self._render_matrix_narrative(narrative, decision)
        except Exception as exc:  # noqa: BLE001 - surfaced to the operator below
            logger.exception("Regime matrix analysis failed")
            self.matrix_ai_output.setHtml(
                f"<b style='color:{theme.DANGER}'>Matrix narrative unavailable:</b> {exc}<br>"
                "Any computed reading above is unaffected."
            )
        finally:
            self.matrix_button.setEnabled(True)

    async def _matrix_signal(self) -> MacroSignal | None:
        bars = await self.runtime.history_source.get_daily_bars(
            self.runtime.benchmark_symbol, n_bars=_MACRO_BARS
        )
        return compute_macro_signal(bars, macro_series=self._macro_series())

    async def _growth_read(self) -> GrowthRead | None:
        """The growth axis, read from the series' own history.

        `None` ON ANY FAILURE, WHICH MAKES THE MATRIX REFUSE. That is the
        intended outcome rather than a degradation: every one of the seven
        regimes keys on growth, and a matrix that answered without it would be
        describing a market it had not measured. The refusal names the gap on
        screen.

        The history comes from the SOURCE, not the bus. `MacroFeed` publishes
        one event per series per poll - the current value - because replaying
        nine thousand observations every poll to communicate five numbers is
        the wrong trade. A direction needs the series, so this asks for it.
        """
        series = self.runtime.settings.macro_growth_series.strip()
        source = self.runtime.macro_source
        if not series or source is None:
            logger.warning(
                "No growth series is configured (QAT_MACRO_GROWTH_SERIES) or no macro "
                "source is available - the regime matrix will refuse"
            )
            return None
        try:
            observations = await source.fetch_series(series)
        except Exception:
            logger.warning(
                "Could not fetch the growth series %s - the regime matrix will refuse "
                "rather than read a regime without it",
                series,
                exc_info=True,
            )
            return None
        return read_growth(series, observations)

    def _execution_regime(self) -> Regime | None:
        """The HMM's label as a `Regime`, or `None` before it has fitted.

        An unrecognised label yields `None` rather than a guess. `compare`
        treats `None` as "no comparison", which is honest; mapping a label it
        does not know onto the nearest regime would manufacture agreement or
        friction out of a parsing accident.
        """
        if self._current_label is None:
            return None
        try:
            return Regime(self._current_label)
        except ValueError:
            logger.warning("Regime label %r is not a known Regime", self._current_label)
            return None

    async def _held_positions(self) -> dict[str, float] | None:
        """What the book holds, or `None` when it could not be read.

        `None` IS NOT `{}`. An empty dict means "measured, and flat", which the
        prompt renders as advice for a flat account. A failed read must not be
        dressed up as one - `advisory_account.py` records the day that exact
        substitution put "given no current positions" in front of an operator
        who held three.
        """
        try:
            snapshot = await self.runtime.account_poller.snapshot()
        except Exception:
            logger.warning(
                "Could not read the account for the regime matrix - the narrative will "
                "be written WITHOUT the book, and must NOT be read as 'the account is flat'",
                exc_info=True,
            )
            return None
        return {position.symbol: position.quantity for position in snapshot.positions}

    def _render_matrix_decision(self, decision: RegimeDecision | MatrixRefusal) -> None:
        if isinstance(decision, MatrixRefusal):
            self.matrix_decision_label.setText("Matrix: NO REGIME - " + "; ".join(decision.missing))
            return
        leverage = "  ABOVE 100% - IMPLIES LEVERAGE." if decision.implies_leverage else ""
        self.matrix_decision_label.setText(
            f"Matrix: {decision.display_regime}. Baseline (BM) {decision.baseline:.1%}, "
            f"scaling unit (SB) {decision.scaling_unit:.2f}, change {decision.change:+.2%} "
            f"-> target {decision.target_weight:.1%}.{leverage}"
        )

    def _render_friction(self, friction: RegimeFriction | None) -> None:
        if friction is None:
            self.matrix_friction_label.setText(
                "Engine comparison: unavailable - one of the two readings is absent, "
                "and one reading is not an agreement."
            )
            self.matrix_friction_label.setStyleSheet(theme.text(theme.MUTED, size=theme.CAPTION))
            return
        self.matrix_friction_label.setText(friction.headline)
        self.matrix_friction_label.setStyleSheet(
            theme.text(theme.MUTED, size=theme.CAPTION)
            if friction.agree
            else theme.text(theme.WARNING, bold=True)
        )

    def _render_matrix_narrative(
        self, narrative: MacroMatrixNarrative, decision: RegimeDecision | MatrixRefusal
    ) -> None:
        parts = [
            f"<b>If:</b> {narrative.condition}",
            f"<b>Then:</b> {narrative.action}",
            f"<b>Because:</b> {narrative.justification}",
        ]
        # The figures come from the DECISION, never from the reply. The service
        # already corrects a model that returned others and records the
        # disagreement in `caveats`; rendering the reply's numbers here would
        # undo that correction one layer later.
        if isinstance(decision, RegimeDecision):
            parts.append(
                f"<b>Computed:</b> change {decision.change:+.2%}, "
                f"target {decision.target_weight:.1%} "
                "<i>(computed in code - the model copies these, it does not set them; "
                "nothing is applied)</i>"
            )
        if narrative.caveats:
            items = "".join(f"<li>{caveat}</li>" for caveat in narrative.caveats)
            parts.append(f"<b>Caveats:</b><ul>{items}</ul>")
        self.matrix_ai_output.setHtml("<br>".join(parts))

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
                f"<b style='color:{theme.DANGER}'>AI synthesis unavailable:</b> {exc}<br>"
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
                f"<b style='color:{theme.WARNING}'>Differs from the deterministic read "
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

    def _refresh_eligibility(self) -> None:
        """What the regime permits, stated from the component that decides it.

        `is_eligible` and `eligible_mass` are ASKED, never reproduced here. A
        screen that summed the published probabilities itself would be a second
        derivation of the same number, and the two drift - leaving the operator
        reading an explanation of a decision taken on different arithmetic. Same
        rule the adopted-positions panel follows.

        Driven by the engine's own listener rather than by this screen's
        RegimeEvent handler, and that is a correctness matter rather than a
        style one: `EventBus.publish` uses `asyncio.gather`, so both handlers
        run concurrently and reading the engine from ours could return the
        PREVIOUS regime's verdict - at exactly the moment a regime changes.
        """
        engine = self.runtime.strategy_engine
        strategies = list(engine.strategies)
        if not strategies:
            self.eligibility_label.setText("Strategies: none deployed.")
            self.mass_detail.setText("")
            return

        verdicts: list[str] = []
        details: list[str] = []
        for strategy in strategies:
            permitted = engine.is_eligible(strategy)
            verdicts.append(f"{strategy.name}: {'PERMITTED' if permitted else 'NOT PERMITTED'}")
            mass = engine.eligible_mass(strategy)
            suitable = " / ".join(sorted(r.value for r in strategy.suitable_regimes()))
            if mass is None:
                details.append(f"{strategy.name}: no distribution yet; suits {suitable}")
            else:
                details.append(
                    f"{strategy.name}: {mass:.2f} of the distribution sits in {suitable} "
                    f"(threshold {engine.regime_eligibility_mass:.2f})"
                )
        self.eligibility_label.setText("Strategies - " + "; ".join(verdicts))
        self.mass_detail.setText("\n".join(details))

    async def _on_regime(self, event: RegimeEvent) -> None:
        self.regime_label.setText(
            f"Regime: {event.label} (exposure scalar={event.exposure_scalar:.2f})"
        )
        # Straight from the event, so no ordering question arises - unlike
        # eligibility, which belongs to the strategy engine. Set regardless of
        # level and merely hidden (M58c), so anything reading this screen
        # programmatically still sees the whole story.
        self.scalar_sentence.setText(
            f"Positions are sized at {event.exposure_scalar * 100:.0f}% of normal "
            "while this regime holds."
        )
        self._regime_probs = event.probs
        self._regime_scalar = event.exposure_scalar
        for label, prob in event.probs.items():
            bar = self.probability_bars.get(label)
            if bar is not None:
                bar.set_probability(prob)

        if event.label != self._current_label:
            self._current_label = event.label
            self.history_list.insertItem(
                0,
                f"{format_display_date(event.ts)} "
                f"{format_session_time(event.ts, self.runtime.settings.market)}"
                f"  ->  {event.label}",
            )
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

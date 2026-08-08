"""AI Advisor (spec §J/§K): free-text research questions answered by the
AIAdvisoryService, every answer carrying its recommendation, confidence,
and risk_flags. An analyst, never a trader - this screen never touches OMS
or a broker; it only ever displays what get_regime_narrative returns.

The question text is passed through AdvisoryContext.fetched_notes, the same
clearly-labelled "untrusted external data" channel used for fetched market
notes (see tests/safety/test_prompt_injection_in_context_is_ignored.py) -
free text a user types is handled with the same discipline as text from any
other external source, not treated as part of the instruction-bearing prompt.
"""

from __future__ import annotations

import asyncio
import logging

from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from qat.domain.ai_advisory.context import AdvisoryContext
from qat.domain.events import RegimeEvent
from qat.presentation import theme
from qat.presentation.runtime import Runtime

logger = logging.getLogger(__name__)


def _answer_caveats(fundamentals: dict[str, object], risk_metrics: dict[str, float]) -> str:
    """What this particular answer was reasoning from, when it was not much.

    `to_prompt_text` already tells the MODEL both of these - it leads the
    fundamentals block with a synthetic warning, and M73 made the absent-risk
    case explicit. The operator reading the reply was told neither, which left
    the two of them working from different information about the same answer.

    Per-answer rather than standing, and empty when there is nothing to say -
    the M69 rule. A caveat printed under every reply is scrolled past.
    """
    caveats: list[str] = []
    if fundamentals.get("is_synthetic"):
        caveats.append(
            "the company fundamentals in its context were SYNTHETIC placeholders, not real "
            "figures"
        )
    if not risk_metrics:
        caveats.append("no portfolio risk check had been recorded yet, so it had no VaR or ES")
    if not caveats:
        return ""
    return "<br><i>Answered without: " + "; ".join(caveats) + ".</i>"


class AiAdvisorScreen(QWidget):
    def __init__(self, runtime: Runtime, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.runtime = runtime
        self._regime_label = "unknown"
        self._regime_probs: dict[str, float] = {}

        layout = QVBoxLayout(self)

        # The framing §4.9 said not to touch, which did not exist (M73).
        #
        # It lived only in this module's docstring - "an analyst, never a
        # trader" - which the operator never sees, while the screen printed
        # "[BUY, confidence=80%]" in bold with nothing to say what happened
        # next. That matters here more than it would elsewhere: this
        # application also trades UNATTENDED, so a recommendation displayed
        # inside it invites exactly the inference that the two are connected.
        # They are not - this screen never touches the OMS or a broker.
        #
        # NOT level-aware, deliberately. M45: safety is not a level, and
        # nothing there may be used to quieten a rail. A Professional operator
        # is not less entitled to know which half of the application is
        # speaking.
        self.framing_label = QLabel(
            "This screen is an <b>analyst, not a trader</b>. Nothing here places, changes or "
            "cancels an order, and the recommendations below reach no part of the trading "
            "system - the strategy engine decides what this account does, and it never reads "
            "these answers. Research only; not financial advice."
        )
        self.framing_label.setWordWrap(True)
        # ACCENT, which theme documents as "structural emphasis, deliberately
        # not a status colour" - this is what the screen IS, not something
        # wrong with it. Styled from the design system rather than inline, per
        # §3a: a hand-styled label here is the 67-stylesheet problem returning
        # one widget at a time.
        self.framing_label.setStyleSheet(theme.text(theme.ACCENT, size=theme.BODY))
        layout.addWidget(self.framing_label)

        self.conversation = QTextEdit()
        self.conversation.setReadOnly(True)
        layout.addWidget(self.conversation)

        input_row = QHBoxLayout()
        self.symbol_picker = QComboBox()
        # Alphabetical, not watchlist order (M76). `resolve_watchlist` returns
        # the universe's own order, which is roughly by market capitalisation -
        # meaningful to the universe and not to someone hunting for WFC in a
        # list of a hundred. Sorted at the dropdown rather than in the watchlist
        # itself: risk_console maps that tuple to correlation-matrix indices, so
        # reordering it there would move a rail's data rather than a control.
        for symbol in sorted(runtime.watchlist):
            self.symbol_picker.addItem(symbol)
        self.question_input = QLineEdit()
        self.question_input.setPlaceholderText("Ask a research question...")
        self.question_input.returnPressed.connect(self._on_ask_clicked)
        self.ask_button = QPushButton("Ask")
        self.ask_button.clicked.connect(self._on_ask_clicked)
        input_row.addWidget(QLabel("Symbol:"))
        input_row.addWidget(self.symbol_picker)
        input_row.addWidget(self.question_input, stretch=1)
        input_row.addWidget(self.ask_button)
        layout.addLayout(input_row)

        self.runtime.bus.subscribe(RegimeEvent, self._on_regime)

    async def _on_regime(self, event: RegimeEvent) -> None:
        self._regime_label = event.label
        self._regime_probs = event.probs

    def _on_ask_clicked(self) -> None:
        question = self.question_input.text().strip()
        if not question:
            return
        self.question_input.clear()
        asyncio.ensure_future(self._ask(question))

    async def _fundamentals_for(self, symbol: str) -> dict[str, object]:
        """The company's figures, or nothing if they cannot be fetched (M40).

        A vendor lookup failing must not cost the operator their answer: the
        advisor still has price, regime and macro, and an advisory reply with
        one input missing is worth more than an error message. The absence is
        logged rather than shown, because the context itself makes it visible -
        no fundamentals line appears in the prompt at all.
        """
        try:
            snapshot = await self.runtime.strategy_engine.fundamentals_source.get_fundamentals(
                symbol
            )
        except Exception:
            logger.exception("Could not fetch fundamentals for %s - asking without them", symbol)
            return {}
        return snapshot.available_figures()

    def _risk_metrics(self) -> dict[str, float]:
        """The portfolio risk figures that actually exist (M73).

        This read `portfolio_check.get("var_95", 0.0)`, so a metric the last
        check did not record reached the model as a MEASURED ZERO - "no tail
        risk" - and a language model has no way to ask which it was.

        `to_prompt_text` applies exactly this discipline to fundamentals two
        lines below, and says so in the prompt: "fields the vendor could not
        answer are omitted rather than zeroed". Absent is omitted here for the
        same reason, and the codebase already states it twice more - the
        Screener's em dash, and `available_figures()`.
        """
        entries = self.runtime.risk_engine.audit_log.entries()
        if not entries:
            return {}
        portfolio_check = entries[-1].inputs.get("portfolio_check")
        if not portfolio_check:
            return {}
        return {
            name: float(value)
            for name in ("var_95", "es_975")
            if (value := portfolio_check.get(name)) is not None
        }

    async def _ask(self, question: str) -> None:
        self.ask_button.setEnabled(False)
        self.conversation.append(f"<b>You:</b> {question}")
        try:
            symbol = self.symbol_picker.currentText()
            positions = {p.symbol: p.quantity for p in await self.runtime.oms.broker.positions()}

            risk_metrics = self._risk_metrics()

            fundamentals = await self._fundamentals_for(symbol)
            context = AdvisoryContext(
                symbol=symbol,
                regime_label=self._regime_label,
                regime_probs=self._regime_probs,
                positions=positions,
                risk_metrics=risk_metrics,
                candidate_signal={},
                fundamentals=fundamentals,
                fetched_notes=[f"User question: {question}"],
            )
            recommendation = await self.runtime.ai_service.get_regime_narrative(context)
            flags = ", ".join(recommendation.risk_flags) if recommendation.risk_flags else "none"
            self.conversation.append(
                f"<b>Advisor</b> [{recommendation.recommendation.upper()}, "
                f"confidence={recommendation.confidence:.0%}, risk flags: {flags}]: "
                f"{recommendation.rationale}{_answer_caveats(fundamentals, risk_metrics)}"
            )
        except Exception as exc:  # noqa: BLE001 - surfaced to the user below
            logger.exception("AI advisor request failed")
            self.conversation.append(
                f"<b style='color:{theme.DANGER}'>Advisor unavailable:</b> {exc}<br>"
                "Check the AI provider settings (Settings tab), then restart the application."
            )
        finally:
            self.ask_button.setEnabled(True)

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
from qat.presentation.runtime import Runtime


class AiAdvisorScreen(QWidget):
    def __init__(self, runtime: Runtime, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.runtime = runtime
        self._regime_label = "unknown"
        self._regime_probs: dict[str, float] = {}

        layout = QVBoxLayout(self)

        self.conversation = QTextEdit()
        self.conversation.setReadOnly(True)
        layout.addWidget(self.conversation)

        input_row = QHBoxLayout()
        self.symbol_picker = QComboBox()
        for symbol in runtime.watchlist:
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

    async def _ask(self, question: str) -> None:
        self.ask_button.setEnabled(False)
        self.conversation.append(f"<b>You:</b> {question}")
        try:
            symbol = self.symbol_picker.currentText()
            positions = {p.symbol: p.quantity for p in await self.runtime.oms.broker.positions()}

            risk_metrics: dict[str, float] = {}
            entries = self.runtime.risk_engine.audit_log.entries()
            if entries:
                portfolio_check = entries[-1].inputs.get("portfolio_check")
                if portfolio_check:
                    risk_metrics = {
                        "var_95": portfolio_check.get("var_95", 0.0),
                        "es_975": portfolio_check.get("es_975", 0.0),
                    }

            context = AdvisoryContext(
                symbol=symbol,
                regime_label=self._regime_label,
                regime_probs=self._regime_probs,
                positions=positions,
                risk_metrics=risk_metrics,
                candidate_signal={},
                fetched_notes=[f"User question: {question}"],
            )
            recommendation = await self.runtime.ai_service.get_regime_narrative(context)
            flags = ", ".join(recommendation.risk_flags) if recommendation.risk_flags else "none"
            self.conversation.append(
                f"<b>Advisor</b> [{recommendation.recommendation.upper()}, "
                f"confidence={recommendation.confidence:.0%}, risk flags: {flags}]: "
                f"{recommendation.rationale}"
            )
        finally:
            self.ask_button.setEnabled(True)

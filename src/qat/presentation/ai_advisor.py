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
from html import escape

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

from qat.domain.events import RegimeEvent
from qat.presentation import theme
from qat.presentation.advisory_inputs import build_advisory_context
from qat.presentation.runtime import Runtime

logger = logging.getLogger(__name__)


def describe_sources(
    news: list[dict[str, object]],
    next_earnings: str,
    news_enabled: bool,
    min_sources: int = 1,
) -> str:
    """What the model was given, in the operator's words (M126).

    The THREE states are deliberately distinct, because collapsing them is how
    a reader concludes the wrong thing from the same blank line:

    * news is switched off - nothing was looked for;
    * news is on and nothing cleared the corroboration bar - it was looked for
      and there was nothing worth passing on;
    * stories were passed, and these are exactly the ones.

    `min_sources` is printed rather than described, because it is now an
    operator setting (`QAT_NEWS_MIN_SOURCES`) rather than the fixed two this
    used to name. A screen that said "the two-source rule" while the rule was
    one would be worse than saying nothing.

    "no news" and "we did not ask" are different facts, the same distinction
    `Status.UNKNOWN` exists for in the pre-flight.
    """
    parts: list[str] = []
    parts.append(
        f"Next scheduled results: {next_earnings}"
        if next_earnings
        else "Next scheduled results: unknown"
    )

    if not news_enabled:
        parts.append("News: OFF (QAT_NEWS_SOURCE=none) - no stories were fetched or passed on.")
        return "  |  ".join(parts)

    if not news:
        outlets = "outlet" if min_sources == 1 else "independent outlets"
        parts.append(
            f"News: fetched, none corroborated - nothing cleared the bar of "
            f"{min_sources} {outlets}, so nothing reached the model."
        )
        return "  |  ".join(parts)

    parts.append(f"News passed to the model ({len(news)}, UNTRUSTED external text):")
    rendered = "  |  ".join(parts)
    for story in news:
        title = str(story.get("title", "")).strip()
        providers = story.get("providers") or []
        joined = ", ".join(str(p) for p in providers) if isinstance(providers, list) else ""
        when = str(story.get("published", "") or "").strip()
        # M116's exception, named where it applies. A story carried on ONE
        # source because that source is the company itself passed a different
        # test from one carried by two aggregators, and an operator weighing
        # the answer should be able to tell which they are looking at.
        basis = "primary source" if story.get("primary") else joined
        rendered += f"\n  • {title} — {basis}{f' ({when})' if when else ''}"
    return rendered


def _sources_html(text: str) -> str:
    """`describe_sources` output, safe to put in the rich-text conversation.

    Escaped first, then newlines become breaks. Order matters: escaping after
    inserting the breaks would escape the breaks too, and doing only the second
    half would render an outlet's headline as markup.

    Styled through `theme.text`, the same call the label it replaced used, so
    moving the text did not quietly promote it to the same weight as the
    answer. Written as `theme.text(...)` rather than as a hand-rolled colour
    and size for the reason this file's own notes already give twice: an inline
    stylesheet here is "the 67-stylesheet problem returning one widget at a
    time", and a hand-written size would bypass the type scale.
    """
    body = escape(text).replace("\n", "<br>")
    return f'<div style="{theme.text(theme.MUTED, size=theme.CAPTION)}">{body}</div>'


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
            "the company fundamentals in its context were SYNTHETIC placeholders, not real figures"
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

        # M126 put this in a one-line QLabel under the conversation. What the
        # model was given is frequently longer than one line - a results date,
        # a bar, and a bullet per story with its outlets - so the label showed
        # the first fragment of it and the rest was simply not visible.
        #
        # It now goes into the conversation itself, immediately above the answer
        # it belongs to, which is scrollable, selectable and already sized for
        # paragraphs. That also fixes something the label could not: with one
        # label, asking a second question overwrote the first question's
        # sources, so scrolling back to an earlier answer showed it beside the
        # inputs of a LATER one. In the transcript each answer keeps its own.
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

    def _corporate_action_notes(self) -> list[str]:
        """Pending corporate actions, into the context the model reasons from
        (M39, R2).

        The reason this is not optional: the model is asked about positions, and
        a pending split means a share count and a per-share price are both about
        to change. Advice about a position whose shape is about to move, given
        without knowing that, is confidently wrong - and `is_synthetic` is the
        precedent for a fact reaching the model late rather than never.
        """
        monitor = getattr(self.runtime, "corporate_action_monitor", None)
        pending = monitor.pending_actions() if monitor is not None else []
        if not pending:
            return []
        mode = self.runtime.settings.corporate_action_mode
        return [
            f"CORPORATE ACTION PENDING: {a.describe()}. The resting stop is "
            + (
                f"adjusted to {a.adjusted_stop:.2f}."
                if a.state == "applied" and a.adjusted_stop is not None
                else f"NOT adjusted (mode={mode})."
            )
            + " New entries in this symbol are refused."
            for a in pending
        ]

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

    # `_news_for` and `_next_earnings_for` went when the double fetch did. Both
    # were one-line passes through to `advisory_inputs`, and their only caller
    # now reads the same material off the context the builder returns. Left in
    # place they would be a second, tempting way to fetch the same thing - which
    # is how the divergence they caused got written in the first place.

    async def _ask(self, question: str) -> None:
        self.ask_button.setEnabled(False)
        # The symbol is read BEFORE the question is echoed, so the transcript
        # line can carry it. Every answer is about one company, and a scrolled-
        # back transcript of "is the valuation stretched?" against six replies
        # gave no way to tell which company each one was about - the picker only
        # ever shows its CURRENT value.
        symbol = self.symbol_picker.currentText()
        self.conversation.append(f"<b>You [{escape(symbol)}]:</b> {escape(question)}")
        try:
            positions = {p.symbol: p.quantity for p in await self.runtime.oms.broker.positions()}

            risk_metrics = self._risk_metrics()

            fundamentals = await self._fundamentals_for(symbol)
            # M117. The question used to travel inside `fetched_notes`, the field
            # whose whole purpose is to quarantine third-party text - so what the
            # operator typed and what a stranger published arrived with identical
            # standing. Only genuinely external material belongs in there now.
            notes = list(self._corporate_action_notes())
            # The context is built FIRST, and the sources block is rendered from
            # what it actually contains. It was the other way round until the
            # 22 August review: this screen fetched news and the results date
            # for the DISPLAY, and `build_advisory_context` then fetched both
            # AGAIN for the model.
            #
            # `news_for` is not a cache read - it calls the vendor live, in a
            # thread, every time, and degrades silently to [] on failure. So two
            # round trips milliseconds apart can legitimately disagree: a story
            # publishes between them, or the second is rate-limited where the
            # first succeeded. The operator would then be shown stories the
            # model never received, or shown none while it reasoned from
            # several, with no way to tell.
            #
            # That is M126's defect exactly - an operator unable to tell what an
            # answer rested on - reproduced inside one screen, on every
            # question. One fetch now, and the display reads its result.
            context = await build_advisory_context(
                self.runtime,
                symbol,
                operator_question=question,
                regime_label=self._regime_label,
                regime_probs=self._regime_probs,
                positions=positions,
                risk_metrics=risk_metrics,
                fundamentals=fundamentals,
                fetched_notes=notes,
                verdict=None,
                position=None,
            )
            # Still appended BEFORE the model is awaited, so the operator reads
            # the reply already knowing what it rested on rather than inferring
            # it afterwards (M126). Only the FETCH moved; the order the operator
            # sees is unchanged, and a test pins that.
            #
            # ESCAPED. This is the one place in the screen where third-party
            # text is rendered, and the conversation widget is rich text - an
            # unescaped headline containing markup would be interpreted as
            # markup rather than shown as the words the outlet published. The
            # prompt already treats this text as untrusted; the display has to
            # as well, or the two disagree about what it is.
            self.conversation.append(
                _sources_html(
                    describe_sources(
                        context.news,
                        context.next_earnings,
                        news_enabled=getattr(self.runtime.settings, "news_source", "none")
                        != "none",
                        min_sources=int(getattr(self.runtime.settings, "news_min_sources", 1) or 1),
                    )
                )
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

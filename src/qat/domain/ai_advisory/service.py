"""AI Advisory Service (spec §J/§14): assemble context -> input guard ->
route -> call LLM -> parse/retry -> output guard -> GuardedRecommendation.

An analyst, never a trader (paper §14): nothing here ever calls OMS or a
broker - this returns a guarded recommendation for a human to review.
"""

from __future__ import annotations

import pandas as pd

from qat.config import Settings
from qat.domain.ai_advisory.context import AdvisoryContext
from qat.domain.ai_advisory.guards import (
    GuardedRecommendation,
    cap_context_size,
    check_recommendation_against_risk_limits,
    redact_context_text,
)
from qat.domain.ai_advisory.prompts import (
    SYSTEM_PROMPT,
    build_macro_analysis_prompt,
    build_performance_narrative_prompt,
    build_regime_narrative_prompt,
    build_trade_rationale_prompt,
)
from qat.domain.ai_advisory.router import LLMRouter
from qat.domain.ai_advisory.schema import AdvisoryRecommendation, MacroAssessment
from qat.domain.macro_analysis.signal import MacroSignal
from qat.domain.risk_engine.engine import OrderCandidate, RiskEngine


class AIAdvisoryService:
    def __init__(
        self, router: LLMRouter, risk_engine: RiskEngine, settings: Settings | None = None
    ) -> None:
        self.router = router
        self.risk_engine = risk_engine
        self.settings = settings or Settings()

    async def get_trade_rationale(
        self,
        context: AdvisoryContext,
        candidate: OrderCandidate,
        equity: float,
        existing_weights: dict[str, float],
        existing_returns: dict[str, pd.Series],
        anthropic_available: bool = True,
    ) -> GuardedRecommendation:
        user_prompt = build_trade_rationale_prompt(context)
        user_prompt = redact_context_text(user_prompt)
        user_prompt = cap_context_size(user_prompt, self.settings.ai_context_max_chars)

        engine = self.router.choose(context, "trade_rationale", anthropic_available)
        recommendation = await engine.complete(SYSTEM_PROMPT, user_prompt, AdvisoryRecommendation)

        return check_recommendation_against_risk_limits(
            recommendation, candidate, self.risk_engine, equity, existing_weights, existing_returns
        )

    async def get_macro_assessment(
        self,
        macro_signal: MacroSignal,
        regime_label: str = "unknown",
        regime_probs: dict[str, float] | None = None,
        fetched_notes: list[str] | None = None,
        anthropic_available: bool = True,
    ) -> MacroAssessment:
        """Market-conditions read: deterministic signal first, AI synthesis on top.

        The MacroSignal is computed by the caller and passed in already measured,
        so the quantitative half of this answer never depends on the model
        having behaved. If the LLM call fails, that measured half is still
        available to the caller - see MacroAssessment vs macro_signal on the
        Regime Monitor, which renders the deterministic read regardless.

        No positions are put in the context: this is a market-wide question, and
        keeping positions out is what lets LLMRouter send it to the general slot
        rather than forcing the sensitive one.
        """
        context = AdvisoryContext(
            symbol=self.settings.market,
            regime_label=regime_label,
            regime_probs=regime_probs or {},
            positions={},
            risk_metrics={},
            candidate_signal={},
            macro_signal=macro_signal.to_dict(),
            macro_series=macro_signal.macro_series,
            fetched_notes=fetched_notes or [],
        )

        user_prompt = build_macro_analysis_prompt(context)
        user_prompt = redact_context_text(user_prompt)
        user_prompt = cap_context_size(user_prompt, self.settings.ai_context_max_chars)

        engine = self.router.choose(context, "macro_analysis", anthropic_available)
        return await engine.complete(SYSTEM_PROMPT, user_prompt, MacroAssessment)

    async def get_performance_narrative(
        self, report_markdown: str, anthropic_available: bool = True
    ) -> str:
        """Plain-English commentary on an already-computed report (spec M16).

        Returns the rationale text rather than the whole recommendation object,
        because that is all a report needs - and returns an empty string rather
        than raising, since a report without a narrative is still complete.
        """
        user_prompt = build_performance_narrative_prompt(report_markdown)
        user_prompt = redact_context_text(user_prompt)
        user_prompt = cap_context_size(user_prompt, self.settings.ai_context_max_chars)

        # No positions in the context, so this can use the general slot - the
        # report itself contains no position sizes, only aggregate results.
        context = AdvisoryContext(
            symbol=self.settings.market,
            regime_label="n/a",
            regime_probs={},
            positions={},
            risk_metrics={},
            candidate_signal={},
        )
        engine = self.router.choose(context, "performance_narrative", anthropic_available)
        recommendation = await engine.complete(SYSTEM_PROMPT, user_prompt, AdvisoryRecommendation)
        return recommendation.rationale

    async def get_regime_narrative(
        self, context: AdvisoryContext, anthropic_available: bool = True
    ) -> AdvisoryRecommendation:
        """Descriptive only - no candidate order exists to risk-check, so
        there's nothing for the output guard to gate here; this path never
        reaches OMS or a broker regardless of what the model returns."""
        user_prompt = build_regime_narrative_prompt(context)
        user_prompt = redact_context_text(user_prompt)
        user_prompt = cap_context_size(user_prompt, self.settings.ai_context_max_chars)

        engine = self.router.choose(context, "regime_narrative", anthropic_available)
        return await engine.complete(SYSTEM_PROMPT, user_prompt, AdvisoryRecommendation)

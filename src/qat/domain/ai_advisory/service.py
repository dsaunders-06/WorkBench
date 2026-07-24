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
    build_regime_narrative_prompt,
    build_trade_rationale_prompt,
)
from qat.domain.ai_advisory.router import LLMRouter
from qat.domain.ai_advisory.schema import AdvisoryRecommendation
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

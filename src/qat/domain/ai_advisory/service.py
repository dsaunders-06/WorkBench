"""AI Advisory Service (spec §J/§14): assemble context -> input guard ->
route -> call LLM -> parse/retry -> output guard -> GuardedRecommendation.

An analyst, never a trader (paper §14): nothing here ever calls OMS or a
broker - this returns a guarded recommendation for a human to review.
"""

from __future__ import annotations

import logging

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
    build_macro_matrix_prompt,
    build_performance_narrative_prompt,
    build_regime_narrative_prompt,
    build_trade_rationale_prompt,
)
from qat.domain.ai_advisory.router import LLMRouter
from qat.domain.ai_advisory.schema import (
    AdvisoryRecommendation,
    MacroAssessment,
    MacroMatrixNarrative,
)
from qat.domain.macro_analysis.friction import RegimeFriction
from qat.domain.macro_analysis.matrix import MatrixRefusal, RegimeDecision
from qat.domain.macro_analysis.signal import MacroSignal
from qat.domain.risk_engine.engine import OrderCandidate, RiskEngine

logger = logging.getLogger(__name__)

# How far the model's echoed figures may sit from the computed ones before
# the caller treats it as disagreement rather than rounding. The prompt
# supplies two decimal places; one decimal place back is a copy, and a
# tolerance any wider would let a real edit through as a rounding artefact.
_ECHO_TOLERANCE_PCT = 0.05


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

    async def get_macro_matrix_narrative(
        self,
        decision: RegimeDecision | MatrixRefusal,
        *,
        positions: dict[str, float] | None = None,
        friction: RegimeFriction | None = None,
        anthropic_available: bool = True,
    ) -> MacroMatrixNarrative:
        """The 7-regime matrix's reading, written up by the model.

        Phase 4 of `docs/superpowers/specs/2026-09-08-macro-regime-matrix-design.md`.

        ⚠️ **ADVISORY ONLY**, by operator instruction of 8 September 2026: *"this
        sits outside of the authority of autonomy, resultant action must be human
        driven only for now."* Nothing here reaches `RiskEngine.regime_scalar`,
        the sizer or an order path - it returns prose and figures for a person.

        ⚠️ **THE POSITIONS GO INTO THE CONTEXT**, not just into the prompt. The
        prompt mentions only how MANY are held, so passing an empty context would
        have worked - and would have routed a request that mentions the book to
        the cloud slot, past the router's own sensitivity check. The check keys
        on the context by design; feeding it honestly is what keeps it a check.
        """
        user_prompt = build_macro_matrix_prompt(decision, positions, friction)
        user_prompt = redact_context_text(user_prompt)
        user_prompt = cap_context_size(user_prompt, self.settings.ai_context_max_chars)

        context = AdvisoryContext(
            symbol=self.settings.market,
            regime_label=(
                decision.regime.value if isinstance(decision, RegimeDecision) else "refused"
            ),
            regime_probs={},
            positions=dict(positions or {}),
            risk_metrics={},
            candidate_signal={},
        )
        engine = self.router.choose(context, "macro_analysis", anthropic_available)
        narrative = await engine.complete(SYSTEM_PROMPT, user_prompt, MacroMatrixNarrative)
        return _hold_the_model_to_the_arithmetic(decision, narrative)


def _hold_the_model_to_the_arithmetic(
    decision: RegimeDecision | MatrixRefusal, narrative: MacroMatrixNarrative
) -> MacroMatrixNarrative:
    """The computed figures win, and a disagreement becomes a visible caveat.

    ⚠️ **CORRECTED, NOT RAISED.** Refusing the whole reply because a model
    rounded differently would take the DETERMINISTIC half off the screen with
    it, and that half is the one with authority. So the numbers rendered are
    always `decide`'s, and the operator is told when the model returned others.

    ⚠️ **NOT SILENT EITHER.** Quietly overwriting would leave a model free to
    disagree on every call with nobody the wiser - which is precisely the
    behaviour `MacroMatrixNarrative` carries echoed fields to detect.
    """
    if isinstance(decision, MatrixRefusal):
        # ⚠️ A refusal computed NO target, so any figure here was invented.
        if narrative.change_pct != 0.0 or narrative.target_pct != 0.0:
            logger.warning(
                "The model returned change=%.2f target=%.2f for a matrix REFUSAL - "
                "no target was computed, so both are cleared",
                narrative.change_pct,
                narrative.target_pct,
            )
            return narrative.model_copy(
                update={
                    "change_pct": 0.0,
                    "target_pct": 0.0,
                    "caveats": [
                        *narrative.caveats,
                        "The matrix could not identify a regime, so no exposure target "
                        "exists; figures the model supplied have been cleared.",
                    ],
                }
            )
        return narrative

    expected_change = decision.change * 100.0
    expected_target = decision.target_weight * 100.0

    # ⚠️ CAVEATS WERE THE ONE CHANNEL WITH NO COUNTER-CHECK, and on
    # 10 September that is exactly where a fabrication landed: the panel showed
    # "Target weight implies leverage" against a computed target of 85.02%.
    # `implies_leverage` had already evaluated False - the Matrix line carried no
    # "ABOVE 100%" suffix and the prompt never appended its leverage instruction
    # - so the model was not told to say it and said it regardless.
    #
    # A fabricated RISK claim is the worst thing to pass through unchecked on a
    # panel whose entire warrant is that the deterministic half has authority.
    # The code already holds the boolean, so it can hold the model to it exactly
    # as it holds it to the arithmetic.
    kept = list(narrative.caveats)
    invented_leverage: list[str] = []
    if not decision.implies_leverage:
        kept = [caveat for caveat in narrative.caveats if "leverage" not in caveat.lower()]
        invented_leverage = [caveat for caveat in narrative.caveats if "leverage" in caveat.lower()]

    caveats = list(kept)
    appended_from = len(kept)

    if invented_leverage:
        caveats.append(
            f"The model claimed leverage - {'; '.join(invented_leverage)} - where the "
            f"computed target of {decision.target_weight:.1%} is below 100%. The claim "
            f"was REMOVED: it rests on no computed figure."
        )

    if abs(narrative.change_pct - expected_change) > _ECHO_TOLERANCE_PCT:
        caveats.append(
            f"The model returned a change of {narrative.change_pct:.1f}%, which did not "
            f"match the computed {expected_change:+.2f}%; the computed figure is shown."
        )
    if abs(narrative.target_pct - expected_target) > _ECHO_TOLERANCE_PCT:
        caveats.append(
            f"The model returned a target of {narrative.target_pct:.1f}%, which did not "
            f"match the computed {expected_target:.2f}%; the computed figure is shown."
        )
    if narrative.regime != decision.regime.value:
        caveats.append(
            f"The model named the regime '{narrative.regime}' where the matrix computed "
            f"'{decision.regime.value}'; the computed regime is shown."
        )

    # ⚠️ CONTENT, NOT LENGTH. This compared counts until 10 September, which
    # was sound while caveats were only ever ADDED. Now that one can be removed
    # and a note appended in its place, a length test reads a corrected reply as
    # an untouched one.
    if caveats == list(narrative.caveats):
        return narrative

    logger.warning(
        "The macro matrix narrative disagreed with the computed arithmetic: %s",
        "; ".join(caveats[appended_from:]),
    )
    return narrative.model_copy(
        update={
            "regime": decision.regime.value,
            "change_pct": expected_change,
            "target_pct": expected_target,
            "caveats": caveats,
        }
    )

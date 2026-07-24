"""Input/output guards (spec §J/§14.1) - the actual enforcement mechanism,
not the system prompt. The prompt tells the model not to follow embedded
instructions or suggest breaching limits; these guards are what make that
true regardless of what the model actually does.

Output guard re-checks the model's recommendation against RiskEngine
independently - it never trusts the model's own self-reported risk_flags
or confidence. This is what makes "AI output that breaches a limit is
blocked" a real, testable property (tests/safety/
test_ai_output_breaching_limits_is_blocked.py) rather than a hope.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from qat.domain.ai_advisory.schema import AdvisoryRecommendation
from qat.domain.risk_engine.engine import OrderCandidate, RiskEngine
from qat.security import get_secret, known_secret_names

_REDACTED = "***REDACTED***"


class ContextTooLargeError(Exception):
    """Raised when the assembled prompt text exceeds the configured size cap."""


def redact_context_text(text: str) -> str:
    """Replaces any value previously requested via qat.security.get_secret()
    with a redaction marker - the same mechanism qat.logging.RedactSecretsFilter
    already uses (M1), applied here to outbound LLM prompts instead of logs."""
    for name in known_secret_names():
        value = get_secret(name)
        if value:
            text = text.replace(value, _REDACTED)
    return text


def cap_context_size(text: str, max_chars: int) -> str:
    if len(text) > max_chars:
        raise ContextTooLargeError(
            f"Context is {len(text)} chars, exceeds the {max_chars}-char cap"
        )
    return text


@dataclass(frozen=True, slots=True)
class GuardedRecommendation:
    recommendation: AdvisoryRecommendation
    blocked: bool
    block_reason: str | None
    risk_check_reason: str


def check_recommendation_against_risk_limits(
    recommendation: AdvisoryRecommendation,
    candidate: OrderCandidate,
    risk_engine: RiskEngine,
    equity: float,
    existing_weights: dict[str, float],
    existing_returns: dict[str, pd.Series],
) -> GuardedRecommendation:
    if recommendation.recommendation == "hold":
        return GuardedRecommendation(
            recommendation,
            blocked=False,
            block_reason=None,
            risk_check_reason="hold - no order to check",
        )

    decision = risk_engine.evaluate_order(candidate, equity, existing_weights, existing_returns)
    if not decision.approved:
        return GuardedRecommendation(
            recommendation,
            blocked=True,
            block_reason=f"Independent risk check rejected this recommendation: {decision.reason}",
            risk_check_reason=decision.reason,
        )
    return GuardedRecommendation(
        recommendation, blocked=False, block_reason=None, risk_check_reason=decision.reason
    )

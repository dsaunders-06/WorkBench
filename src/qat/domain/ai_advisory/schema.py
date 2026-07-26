"""Structured LLM output schema (spec §J/§19.2): trade-rationale and
regime-narrative prompts both return this same shape - a fixed schema, not
free text, so downstream code never has to guess at parsing."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class AdvisoryRecommendation(BaseModel):
    recommendation: Literal["buy", "sell", "hold"]
    rationale: str
    confidence: float = Field(ge=0.0, le=1.0)
    risk_flags: list[str] = Field(default_factory=list)


class MacroAssessment(BaseModel):
    """The AI's read on market conditions (spec M13).

    `regime` is the model's own call and may legitimately differ from the
    deterministic signal it was shown - that disagreement is informative and is
    surfaced to the operator rather than reconciled away.

    `suggested_exposure_scalar` is a *proposal only*. Nothing applies it: the
    Regime Monitor displays it and the operator decides. This is the same
    boundary the original app drew after concluding that letting a model move
    risk settings on its own was a materially larger trust delegation than
    letting it comment on them.
    """

    regime: Literal["risk_on", "neutral", "caution", "risk_off"]
    reasoning: str
    confidence: float = Field(ge=0.0, le=1.0)
    key_insights: list[str] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)
    suggested_exposure_scalar: float | None = Field(default=None, ge=0.0, le=1.0)

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


class MacroMatrixNarrative(BaseModel):
    """The 7-regime matrix's reading, written up.

    Phase 4 of `docs/superpowers/specs/2026-09-08-macro-regime-matrix-design.md`.

    ⚠️ EVERY NUMBER HERE IS COPIED, NOT COMPUTED. `regime`, `change_pct` and
    `target_pct` are echoed back from the deterministic `RegimeDecision` the
    model was handed. They are carried as structured fields so the operator can
    read the figures without parsing prose, and so a model that quietly
    disagreed with the arithmetic is CAUGHT rather than believed - the caller
    compares them against what it sent.

    The model's job is `condition`, `action` and `justification`: the
    If/Then/Justification structure the source document asks for. That is
    writing, which it is good at, rather than arithmetic that sets an exposure
    target, which is the failure mode `guards.py` exists for.

    ⚠️ ADVISORY ONLY. Operator instruction, 8 September 2026: "this sits outside
    of the authority of autonomy, resultant action must be human driven only for
    now." Nothing reads `target_pct` but a person.
    """

    regime: Literal["bull", "bear", "shock", "low_vol_drift", "recession", "recovery", "sideways"]
    condition: str
    """The "If": the market state in plain English, from the supplied figures."""
    action: str
    """The "Then": what to do, carrying the change and the target weight."""
    justification: str
    """Why this serves the portfolio in THIS regime."""
    change_pct: float
    """Echoed from the decision. Signed: positive lifts, negative cuts."""
    target_pct: float
    """Echoed from the decision."""
    caveats: list[str] = Field(default_factory=list)
    """⚠️ Condition-specific, never boilerplate. `workbench.py` records why: "a
    disclaimer printed on every result stops being read". The standing "research
    only, not financial advice" framing already sits on the screen; this carries
    what is true of THIS reading - a stale growth series, a held regime, a
    target implying leverage."""

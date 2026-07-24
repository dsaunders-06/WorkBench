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

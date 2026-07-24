"""LLM routing (spec §J/§16): choose engine by sensitivity, complexity, and
availability/cost - in that precedence order. Sensitivity is checked first
and is an absolute override (a privacy constraint, not a preference): any
request touching specific position sizes goes local regardless of what
else is true, matching the spec's explicit example ("positions/PnL -> local
by default").
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from qat.config import Settings
from qat.domain.ai_advisory.context import AdvisoryContext
from qat.domain.ai_advisory.llm_engine import LLMEngine

RequestKind = Literal["trade_rationale", "regime_narrative"]


@dataclass
class LLMRouter:
    anthropic_engine: LLMEngine
    local_engine: LLMEngine
    settings: Settings = field(default_factory=Settings)
    _calls_today: int = field(default=0, init=False)

    def choose(
        self, context: AdvisoryContext, kind: RequestKind, anthropic_available: bool = True
    ) -> LLMEngine:
        if context.positions:
            return self.local_engine
        if not anthropic_available:
            return self.local_engine
        if self._calls_today >= self.settings.ai_cost_budget_calls_per_day:
            return self.local_engine
        if kind == "regime_narrative":
            self._calls_today += 1
            return self.anthropic_engine
        return self.local_engine

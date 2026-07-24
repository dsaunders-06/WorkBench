from __future__ import annotations

from qat.config import Settings
from qat.domain.ai_advisory.context import AdvisoryContext
from qat.domain.ai_advisory.router import LLMRouter, RequestKind


class _StubEngine:
    def __init__(self, name: str) -> None:
        self.name = name

    async def complete(self, system_prompt, user_prompt, schema, max_retries=1):
        raise NotImplementedError


def _context(positions: dict[str, float] | None = None) -> AdvisoryContext:
    return AdvisoryContext(
        symbol="AAPL",
        regime_label="bull",
        regime_probs={},
        positions=positions or {},
        risk_metrics={},
        candidate_signal={},
    )


def test_positions_present_routes_to_local_regardless_of_kind():
    router = LLMRouter(_StubEngine("anthropic"), _StubEngine("local"))
    engine = router.choose(_context(positions={"AAPL": 10.0}), "regime_narrative")
    assert engine.name == "local"


def test_regime_narrative_without_positions_routes_to_anthropic():
    router = LLMRouter(_StubEngine("anthropic"), _StubEngine("local"))
    engine = router.choose(_context(), "regime_narrative")
    assert engine.name == "anthropic"


def test_trade_rationale_without_positions_still_routes_local_by_default():
    router = LLMRouter(_StubEngine("anthropic"), _StubEngine("local"))
    engine = router.choose(_context(), "trade_rationale")
    assert engine.name == "local"


def test_anthropic_unavailable_falls_back_to_local():
    router = LLMRouter(_StubEngine("anthropic"), _StubEngine("local"))
    engine = router.choose(_context(), "regime_narrative", anthropic_available=False)
    assert engine.name == "local"


def test_cost_budget_exhausted_falls_back_to_local():
    settings = Settings(_env_file=None, ai_cost_budget_calls_per_day=2)
    router = LLMRouter(_StubEngine("anthropic"), _StubEngine("local"), settings=settings)
    kind: RequestKind = "regime_narrative"

    first = router.choose(_context(), kind)
    second = router.choose(_context(), kind)
    third = router.choose(_context(), kind)

    assert first.name == "anthropic"
    assert second.name == "anthropic"
    assert third.name == "local"

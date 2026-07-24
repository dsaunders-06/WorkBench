from __future__ import annotations

import pandas as pd
import pytest

from qat.config import Settings
from qat.domain.ai_advisory.context import AdvisoryContext
from qat.domain.ai_advisory.guards import ContextTooLargeError
from qat.domain.ai_advisory.router import LLMRouter
from qat.domain.ai_advisory.schema import AdvisoryRecommendation
from qat.domain.ai_advisory.service import AIAdvisoryService
from qat.domain.bus import EventBus
from qat.domain.risk_engine.engine import OrderCandidate, RiskEngine
from qat.domain.risk_engine.kill_switch import KillSwitch


class _StubEngine:
    def __init__(self, response: AdvisoryRecommendation) -> None:
        self.response = response
        self.calls: list[tuple[str, str]] = []

    async def complete(self, system_prompt, user_prompt, schema, max_retries=1):
        self.calls.append((system_prompt, user_prompt))
        return self.response


def _flat_returns(n: int = 30) -> pd.Series:
    dates = pd.date_range("2024-01-01", periods=n)
    return pd.Series([0.001] * n, index=dates)


def _candidate(symbol: str = "AAA") -> OrderCandidate:
    return OrderCandidate(
        symbol=symbol,
        side="buy",
        price=100.0,
        atr=2.0,
        win_rate=0.6,
        win_loss_ratio=2.0,
        candidate_returns=_flat_returns(),
    )


def _context(positions: dict[str, float] | None = None) -> AdvisoryContext:
    return AdvisoryContext(
        symbol="AAA",
        regime_label="bull",
        regime_probs={"bull": 0.8},
        positions=positions or {},
        risk_metrics={},
        candidate_signal={"side": "buy"},
    )


@pytest.mark.asyncio
async def test_get_trade_rationale_returns_guarded_recommendation_when_approved():
    bus = EventBus()
    switch = KillSwitch()
    risk_engine = RiskEngine(bus, switch, settings=Settings(_env_file=None))
    stub = _StubEngine(
        AdvisoryRecommendation(
            recommendation="buy", rationale="good setup", confidence=0.8, risk_flags=[]
        )
    )
    router = LLMRouter(stub, stub)
    service = AIAdvisoryService(router, risk_engine)

    result = await service.get_trade_rationale(_context(), _candidate(), 100_000.0, {}, {})

    assert result.blocked is False
    assert result.recommendation.recommendation == "buy"
    assert len(stub.calls) == 1


@pytest.mark.asyncio
async def test_get_trade_rationale_blocks_when_kill_switch_tripped():
    bus = EventBus()
    switch = KillSwitch()
    switch.trigger_manual("test")
    risk_engine = RiskEngine(bus, switch)
    stub = _StubEngine(
        AdvisoryRecommendation(
            recommendation="buy", rationale="good setup", confidence=0.9, risk_flags=[]
        )
    )
    router = LLMRouter(stub, stub)
    service = AIAdvisoryService(router, risk_engine)

    result = await service.get_trade_rationale(_context(), _candidate(), 100_000.0, {}, {})

    assert result.blocked is True


@pytest.mark.asyncio
async def test_get_regime_narrative_returns_raw_recommendation():
    bus = EventBus()
    switch = KillSwitch()
    risk_engine = RiskEngine(bus, switch)
    stub = _StubEngine(
        AdvisoryRecommendation(
            recommendation="hold", rationale="market is calm", confidence=0.7, risk_flags=[]
        )
    )
    router = LLMRouter(stub, stub)
    service = AIAdvisoryService(router, risk_engine)

    result = await service.get_regime_narrative(_context())

    assert result.recommendation == "hold"


@pytest.mark.asyncio
async def test_context_exceeding_size_cap_raises_before_calling_llm():
    bus = EventBus()
    switch = KillSwitch()
    risk_engine = RiskEngine(bus, switch)
    stub = _StubEngine(
        AdvisoryRecommendation(recommendation="hold", rationale="x", confidence=0.5, risk_flags=[])
    )
    router = LLMRouter(stub, stub)
    settings = Settings(_env_file=None, ai_context_max_chars=10)
    service = AIAdvisoryService(router, risk_engine, settings=settings)

    with pytest.raises(ContextTooLargeError):
        await service.get_trade_rationale(_context(), _candidate(), 100_000.0, {}, {})

    assert stub.calls == []

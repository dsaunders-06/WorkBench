"""Spec-mandated safety test 4/5: AI output that breaches a risk limit is
blocked before a human ever sees it endorsed (spec §J/§14.1). The output
guard independently re-checks the recommendation against RiskEngine - it
never trusts the model's own self-reported confidence/risk_flags, which is
what this test actually exercises: a maximally "confident" fake model that
reports zero risk flags of its own still gets blocked."""

from __future__ import annotations

import pandas as pd
import pytest

from qat.config import Settings
from qat.domain.ai_advisory.context import AdvisoryContext
from qat.domain.ai_advisory.router import LLMRouter
from qat.domain.ai_advisory.schema import AdvisoryRecommendation
from qat.domain.ai_advisory.service import AIAdvisoryService
from qat.domain.bus import EventBus
from qat.domain.risk_engine.engine import OrderCandidate, RiskEngine
from qat.domain.risk_engine.kill_switch import KillSwitch


class _OverconfidentStubEngine:
    def __init__(self, response: AdvisoryRecommendation) -> None:
        self.response = response

    async def complete(self, system_prompt, user_prompt, schema, max_retries=1):
        return self.response


def _flat_returns(n: int = 30) -> pd.Series:
    dates = pd.date_range("2024-01-01", periods=n)
    return pd.Series([0.001] * n, index=dates)


def _candidate() -> OrderCandidate:
    return OrderCandidate(
        symbol="AAA",
        side="buy",
        price=100.0,
        atr=2.0,
        win_rate=0.6,
        win_loss_ratio=2.0,
        candidate_returns=_flat_returns(),
    )


def _context() -> AdvisoryContext:
    return AdvisoryContext(
        symbol="AAA",
        regime_label="bull",
        regime_probs={"bull": 0.9},
        positions={},
        risk_metrics={},
        candidate_signal={"side": "buy"},
    )


@pytest.mark.asyncio
async def test_kill_switch_active_blocks_confident_ai_recommendation():
    bus = EventBus()
    switch = KillSwitch()
    switch.trigger_manual("operator")
    risk_engine = RiskEngine(bus, switch, settings=Settings(_env_file=None))

    confident_buy = AdvisoryRecommendation(
        recommendation="buy",
        rationale="Extremely strong setup, no risk concerns.",
        confidence=0.99,
        risk_flags=[],
    )
    stub = _OverconfidentStubEngine(confident_buy)
    service = AIAdvisoryService(LLMRouter(stub, stub), risk_engine)

    result = await service.get_trade_rationale(_context(), _candidate(), 100_000.0, {}, {})

    assert result.blocked is True
    assert "Kill-switch" in result.risk_check_reason
    assert (
        result.recommendation.recommendation == "buy"
    )  # preserved for human review, marked blocked


@pytest.mark.asyncio
async def test_portfolio_es_breach_blocks_confident_ai_recommendation():
    bus = EventBus()
    switch = KillSwitch()
    settings = Settings(_env_file=None, portfolio_es_limit_pct=0.0001)
    risk_engine = RiskEngine(bus, switch, settings=settings)

    confident_buy = AdvisoryRecommendation(
        recommendation="buy",
        rationale="Great trade, fully within limits.",
        confidence=0.95,
        risk_flags=[],
    )
    stub = _OverconfidentStubEngine(confident_buy)
    service = AIAdvisoryService(LLMRouter(stub, stub), risk_engine)

    dates = pd.date_range("2024-01-01", periods=30)
    volatile_candidate = OrderCandidate(
        symbol="AAA",
        side="buy",
        price=100.0,
        atr=2.0,
        win_rate=0.6,
        win_loss_ratio=2.0,
        candidate_returns=pd.Series([0.05, -0.06] * 15, index=dates),
    )

    result = await service.get_trade_rationale(_context(), volatile_candidate, 100_000.0, {}, {})

    assert result.blocked is True


@pytest.mark.asyncio
async def test_hold_recommendation_from_ai_is_never_blocked_since_no_order_exists():
    bus = EventBus()
    switch = KillSwitch()
    switch.trigger_manual("operator")
    risk_engine = RiskEngine(bus, switch)

    hold_rec = AdvisoryRecommendation(
        recommendation="hold", rationale="market is uncertain", confidence=0.6, risk_flags=[]
    )
    stub = _OverconfidentStubEngine(hold_rec)
    service = AIAdvisoryService(LLMRouter(stub, stub), risk_engine)

    result = await service.get_trade_rationale(_context(), _candidate(), 100_000.0, {}, {})

    assert result.blocked is False

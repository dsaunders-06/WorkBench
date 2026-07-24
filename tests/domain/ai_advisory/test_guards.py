from __future__ import annotations

import pandas as pd
import pytest

import qat.domain.ai_advisory.guards as guards_module
from qat.config import Settings
from qat.domain.ai_advisory.guards import (
    ContextTooLargeError,
    cap_context_size,
    check_recommendation_against_risk_limits,
    redact_context_text,
)
from qat.domain.ai_advisory.schema import AdvisoryRecommendation
from qat.domain.bus import EventBus
from qat.domain.risk_engine.engine import OrderCandidate, RiskEngine
from qat.domain.risk_engine.kill_switch import KillSwitch


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


def test_cap_context_size_passes_under_limit():
    assert cap_context_size("short text", max_chars=100) == "short text"


def test_cap_context_size_raises_over_limit():
    with pytest.raises(ContextTooLargeError):
        cap_context_size("x" * 200, max_chars=100)


def test_redact_context_text_replaces_known_secret_values(monkeypatch):
    monkeypatch.setattr(guards_module, "known_secret_names", lambda: frozenset({"API_KEY"}))
    monkeypatch.setattr(
        guards_module,
        "get_secret",
        lambda name: "super-secret-value" if name == "API_KEY" else None,
    )

    text = redact_context_text("here is the key: super-secret-value in context")

    assert "super-secret-value" not in text
    assert "REDACTED" in text


def test_hold_recommendation_is_never_blocked():
    bus = EventBus()
    switch = KillSwitch()
    engine = RiskEngine(bus, switch)
    rec = AdvisoryRecommendation(recommendation="hold", rationale="x", confidence=0.5)

    result = check_recommendation_against_risk_limits(rec, _candidate(), engine, 100_000.0, {}, {})

    assert result.blocked is False


def test_buy_recommendation_approved_by_risk_engine_passes_through():
    settings = Settings(_env_file=None, per_trade_risk_pct=0.01, atr_stop_multiple=2.5)
    bus = EventBus()
    switch = KillSwitch()
    engine = RiskEngine(bus, switch, settings=settings)
    rec = AdvisoryRecommendation(recommendation="buy", rationale="x", confidence=0.8, risk_flags=[])

    result = check_recommendation_against_risk_limits(rec, _candidate(), engine, 100_000.0, {}, {})

    assert result.blocked is False
    assert result.recommendation.recommendation == "buy"


def test_buy_recommendation_rejected_by_risk_engine_is_blocked():
    bus = EventBus()
    switch = KillSwitch()
    switch.trigger_manual("test")
    engine = RiskEngine(bus, switch)
    rec = AdvisoryRecommendation(
        recommendation="buy",
        rationale="the model is very confident",
        confidence=0.99,
        risk_flags=[],
    )

    result = check_recommendation_against_risk_limits(rec, _candidate(), engine, 100_000.0, {}, {})

    assert result.blocked is True
    assert "Kill-switch" in result.risk_check_reason

from __future__ import annotations

import dataclasses
import random

import pandas as pd
import pytest

from qat.config import Settings
from qat.domain.bus import EventBus
from qat.domain.events import RegimeEvent
from qat.domain.regime import Regime
from qat.domain.risk_engine.engine import OrderCandidate, RiskEngine
from qat.domain.risk_engine.kill_switch import KillSwitch


def _settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[arg-type]


def _flat_returns(n: int = 30) -> pd.Series:
    dates = pd.date_range("2024-01-01", periods=n)
    return pd.Series([0.001] * n, index=dates)


def _candidate(
    symbol: str = "AAA",
    price: float = 100.0,
    atr: float = 2.0,
    win_rate: float = 0.6,
    win_loss_ratio: float = 2.0,
) -> OrderCandidate:
    return OrderCandidate(
        symbol=symbol,
        side="buy",
        price=price,
        atr=atr,
        win_rate=win_rate,
        win_loss_ratio=win_loss_ratio,
        candidate_returns=_flat_returns(),
    )


def test_approved_order_never_exceeds_per_trade_risk_budget():
    bus = EventBus()
    switch = KillSwitch()
    settings = _settings(per_trade_risk_pct=0.01, atr_stop_multiple=2.5)
    engine = RiskEngine(bus, switch, settings=settings)

    equity = 100_000.0
    decision = engine.evaluate_order(_candidate(), equity, {}, {})

    assert decision.approved
    implied_loss = decision.final_shares * 2.5 * 2.0
    assert implied_loss <= 0.01 * equity + 1e-6


def test_kill_switch_active_rejects_immediately():
    bus = EventBus()
    switch = KillSwitch()
    switch.trigger_manual("test")
    engine = RiskEngine(bus, switch)

    decision = engine.evaluate_order(_candidate(), 100_000.0, {}, {})

    assert decision.approved is False
    assert "Kill-switch" in decision.reason


def test_no_edge_rejects():
    bus = EventBus()
    switch = KillSwitch()
    engine = RiskEngine(bus, switch)

    decision = engine.evaluate_order(
        _candidate(win_rate=0.3, win_loss_ratio=1.0), 100_000.0, {}, {}
    )

    assert decision.approved is False


@pytest.mark.asyncio
async def test_regime_scalar_scales_final_shares():
    bus = EventBus()
    switch = KillSwitch()
    # Concentration relaxed: this asserts that the scalar *scales*, and a cap
    # that binds at both scalars would trim them to the same number and hide
    # exactly the behaviour under test.
    settings = _settings(
        per_trade_risk_pct=0.01,
        atr_stop_multiple=2.5,
        max_single_name_concentration_pct=1.0,
    )
    engine = RiskEngine(bus, switch, settings=settings)
    await engine.start()

    baseline = engine.evaluate_order(_candidate(), 100_000.0, {}, {})
    await bus.publish(RegimeEvent(label=Regime.RECESSION.value, probs={}, exposure_scalar=0.3))
    scaled = engine.evaluate_order(_candidate(), 100_000.0, {}, {})

    assert scaled.final_shares == pytest.approx(baseline.final_shares * 0.3)
    await engine.stop()


def test_portfolio_breach_rejects():
    bus = EventBus()
    switch = KillSwitch()
    engine = RiskEngine(bus, switch, settings=_settings(portfolio_es_limit_pct=0.0001))
    dates = pd.date_range("2024-01-01", periods=30)
    volatile_returns = pd.Series([0.05, -0.06] * 15, index=dates)
    candidate = dataclasses.replace(_candidate(), candidate_returns=volatile_returns)

    decision = engine.evaluate_order(candidate, 100_000.0, {}, {})

    assert decision.approved is False


def test_audit_log_records_every_decision():
    bus = EventBus()
    switch = KillSwitch()
    engine = RiskEngine(bus, switch)

    engine.evaluate_order(_candidate(), 100_000.0, {}, {})
    engine.evaluate_order(_candidate(win_rate=0.2, win_loss_ratio=1.0), 100_000.0, {}, {})

    assert len(engine.audit_log.entries()) == 2


def test_property_no_approved_order_ever_exceeds_limits_across_random_inputs():
    bus = EventBus()
    switch = KillSwitch()
    settings = _settings(
        per_trade_risk_pct=0.01, atr_stop_multiple=2.5, portfolio_es_limit_pct=0.03
    )
    engine = RiskEngine(bus, switch, settings=settings)

    rng = random.Random(0)  # nosec B311 - deterministic property test, not crypto
    equity = 100_000.0
    for _ in range(200):
        price = rng.uniform(1.0, 500.0)
        atr = rng.uniform(0.01, 20.0)
        win_rate = rng.uniform(0.0, 1.0)
        win_loss_ratio = rng.uniform(0.1, 5.0)
        candidate = _candidate(
            price=price, atr=atr, win_rate=win_rate, win_loss_ratio=win_loss_ratio
        )

        decision = engine.evaluate_order(candidate, equity, {}, {})

        assert decision.final_shares >= 0
        if decision.approved:
            implied_loss = decision.final_shares * settings.atr_stop_multiple * atr
            assert implied_loss <= settings.per_trade_risk_pct * equity + 1e-6


@pytest.mark.asyncio
async def test_a_decision_records_which_regime_produced_its_scalar():
    """`regime_scalar: 1.0` was ambiguous, and the ambiguity was invisible.

    Low-vol's exposure scalar is 1.00 and the engine's untouched default is
    also 1.0, so a decision carrying `regime_scalar: 1` could mean "measured
    low_vol" or "no RegimeEvent has ever arrived and this gate is the default".
    Nothing written to `risk_decisions.csv` distinguished them.

    Found on 19 August, when session_check reported NO REGIME PUBLISHED for a
    whole session and the 120 decisions it wrote could not confirm or deny it.
    Same shape as the corporate-actions failure of 12 August: blindness reading
    identically to a quiet book.

    `None` means the scalar is a default, never a reading - the same
    None-is-not-zero rule the positions panel is built on.
    """
    bus = EventBus()
    engine = RiskEngine(bus, KillSwitch(), settings=_settings())
    await engine.start()

    before = engine.evaluate_order(_candidate(), 100_000.0, {}, {})
    assert before.inputs["regime_scalar"] == 1.0
    assert before.inputs["regime_label"] is None, "a default must not look like a reading"

    await bus.publish(
        RegimeEvent(
            label=Regime.LOW_VOL.value, probs={Regime.LOW_VOL.value: 0.9}, exposure_scalar=1.0
        )
    )
    after = engine.evaluate_order(_candidate(), 100_000.0, {}, {})

    # The scalar is IDENTICAL either side - which is exactly why the label is
    # the only thing that can tell the two states apart.
    assert after.inputs["regime_scalar"] == 1.0
    assert after.inputs["regime_label"] == Regime.LOW_VOL.value
    await engine.stop()

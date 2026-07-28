"""Trades must be able to carry their own fees (spec M27).

IBKR charges a minimum of $6 per transaction, so a round trip costs at least
$12 before the market moves at all. Two things follow, and neither was
represented anywhere in the app before M27: a bps-only cost model cannot
express a floor, and nothing in the live path knew what a trade cost.
"""

from __future__ import annotations

import pytest

from qat.config import Settings
from qat.domain.backtester.costs import CostModel
from qat.domain.bus import EventBus
from qat.domain.risk_engine.engine import OrderCandidate, RiskEngine
from qat.domain.risk_engine.kill_switch import KillSwitch


def _engine(**kwargs: object) -> RiskEngine:
    settings = Settings(_env_file=None, **kwargs)  # type: ignore[arg-type]
    return RiskEngine(EventBus(), KillSwitch(), settings=settings)


def _candidate(price: float = 100.0, stop_price: float | None = None, atr: float = 2.0):
    return OrderCandidate(
        symbol="AAA",
        side="buy",
        price=price,
        atr=atr,
        stop_price=stop_price,
        candidate_returns=[],
        win_rate=0.5,
        win_loss_ratio=2.0,
    )


# --- the cost model itself ----------------------------------------------------


def test_the_floor_binds_where_the_proportional_rate_does_not() -> None:
    """The case a bps-only model gets wrong by six times."""
    model = CostModel(commission_bps=5.0, slippage_bps=0.0, min_commission=6.0)

    # $2,000 at 5bps is $1 of commission - the real charge is $6.
    assert model.commission(2_000.0) == 6.0
    # $20,000 at 5bps is $10, above the floor, so the floor stops mattering.
    assert model.commission(20_000.0) == 10.0


def test_slippage_takes_no_floor() -> None:
    """Slippage is an estimate of market impact, not a charge.

    A minimum dollar slippage on a tiny order would be inventing a cost rather
    than modelling one.
    """
    model = CostModel(commission_bps=0.0, slippage_bps=5.0, min_commission=6.0)

    assert model.slippage(2_000.0) == pytest.approx(1.0)


def test_a_zero_cost_model_is_still_reachable() -> None:
    """The vectorized engine's guardrail depends on being able to build one."""
    model = CostModel(0.0, 0.0)

    assert model.apply(50_000.0) == 0.0
    assert model.total_bps == 0


def test_a_round_trip_is_both_sides() -> None:
    model = CostModel(commission_bps=0.0, slippage_bps=0.0, min_commission=6.0)

    assert model.round_trip(10_000.0) == 12.0
    # An exit at a different price costs its own commission, not the entry's.
    assert model.round_trip(10_000.0, 20_000.0) == 12.0


def test_the_model_is_built_from_configuration() -> None:
    settings = Settings(_env_file=None, broker_min_commission=6.0, commission_bps=5.0)

    assert CostModel.from_settings(settings).min_commission == 6.0


# --- the rail -----------------------------------------------------------------


def test_a_trade_too_small_to_carry_its_fees_is_refused() -> None:
    """$12 of fees against $50 of risk is not a trade, it is a donation."""
    engine = _engine(per_trade_risk_pct=0.01)

    # A tiny account: 1% of $5,000 is $50 at risk, and the round trip is $12+.
    decision = engine.evaluate_order(_candidate(), 5_000.0, {}, {}, available_cash=5_000.0)

    assert not decision.approved
    assert "too small to carry its fees" in decision.reason
    assert decision.inputs["cost_to_risk_pct"] > 0.10


def test_a_normal_swing_trade_clears_the_rail() -> None:
    """A 5%-wide stop on a $100k account spends about 4% of its risk on costs."""
    engine = _engine()

    decision = engine.evaluate_order(
        _candidate(price=100.0, stop_price=95.0), 100_000.0, {}, {}, available_cash=1_000_000.0
    )

    assert decision.approved
    assert decision.inputs["cost_to_risk_pct"] < 0.10
    assert decision.inputs["round_trip_cost"] > 0


def test_the_decision_records_what_it_measured() -> None:
    """Audited like every other risk decision, or it cannot be reviewed later."""
    engine = _engine()

    decision = engine.evaluate_order(
        _candidate(stop_price=95.0), 100_000.0, {}, {}, available_cash=1_000_000.0
    )

    assert "round_trip_cost" in decision.inputs
    assert "cost_to_risk_pct" in decision.inputs


def test_costs_are_measured_against_risk_not_notional() -> None:
    """The invariant that makes the rail scale correctly.

    A tight stop buys far more shares for the same dollar risk, so its notional
    - and therefore its proportional costs - are much larger relative to what
    is actually at stake. Measuring against notional would call that cheap.
    """
    engine = _engine()

    tight = engine.evaluate_order(
        _candidate(price=100.0, stop_price=99.0), 100_000.0, {}, {}, available_cash=10_000_000.0
    )
    wide = engine.evaluate_order(
        _candidate(price=100.0, stop_price=90.0), 100_000.0, {}, {}, available_cash=10_000_000.0
    )

    assert not tight.approved, "a 1% stop spends ~20% of its risk on costs"
    assert wide.approved


def test_an_exit_is_never_refused_for_being_expensive() -> None:
    """Refusing to close a position because it costs money is the same error as
    refusing to de-risk: the cost rail gates added exposure only."""
    engine = _engine()

    decision = engine.evaluate_exit("AAA", quantity=1.0, price=10.0)

    assert decision.approved


def test_costs_can_be_switched_off_but_are_on_by_default() -> None:
    """On by default is the point.

    Alpaca paper charges nothing, so a commission-free measurement would
    promote a strategy onto a broker where the same trades lose money.
    """
    assert Settings(_env_file=None).apply_costs_in_paper is True

    off = _engine(apply_costs_in_paper=False, per_trade_risk_pct=0.01)
    decision = off.evaluate_order(_candidate(), 5_000.0, {}, {}, available_cash=5_000.0)

    assert decision.approved
    assert "cost_to_risk_pct" not in decision.inputs

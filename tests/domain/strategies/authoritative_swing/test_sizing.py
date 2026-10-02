"""Exact cost, prior-volume capacity, and whole-share sizing tests."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import date, timedelta
from decimal import Decimal

import pytest

from qat.domain.strategies.authoritative_swing.model import (
    AdjustmentStatus,
    DataQuality,
    DecisionStatus,
    FinalBar,
    Ohlcv,
)
from qat.domain.strategies.authoritative_swing.numeric import SplitFactor
from qat.domain.strategies.authoritative_swing.sizing import (
    LiquidityProfile,
    capacity_quantity,
    exact_cost_profile,
    modeled_total_risk,
    size_for_risk,
    size_instruction,
)


def D(value: str | int) -> Decimal:
    return Decimal(value)


LIQUIDITY = LiquidityProfile(
    version="fixture-liquidity-v1",
    max_participation=D("0.10"),
    entry_impact_bps=D("5"),
    stop_exit_impact_bps=D("7"),
)


def _bar(index: int, *, volume: int = 100_000, close: str = "10") -> FinalBar:
    prices = Ohlcv(D("10"), D("10.2"), D("9.8"), D(close), volume)
    return FinalBar(
        symbol="BHP.AX",
        session=date(2026, 1, 1) + timedelta(days=index),
        raw=prices,
        adjusted=prices,
        source="fixture",
        quality=DataQuality.VERIFIED,
        adjustment=AdjustmentStatus.SPLIT_NORMALIZED,
        raw_to_adjusted_price_factor=SplitFactor(1, 1),
        finalized=True,
        digest=f"digest-{index}",
    )


def test_risk_quantity_is_the_largest_integer_that_passes_complete_cost() -> None:
    cost = exact_cost_profile("ASX", "fixed")

    result = size_for_risk(D("100000"), D("10"), D("9"), cost, LIQUIDITY)

    assert result.total_at_quantity <= result.budget
    assert result.total_at_next > result.budget
    assert modeled_total_risk(result.quantity, D("10"), D("9"), cost, LIQUIDITY) == (
        result.total_at_quantity
    )


def test_tiny_stop_uses_bisection_with_at_most_32_cost_evaluations() -> None:
    result = size_for_risk(
        D("100000"),
        D("10"),
        D("9.9999"),
        exact_cost_profile("ASX", "fixed"),
        LIQUIDITY,
    )

    assert result.safe_upper_bound > 1_000_000
    assert result.cost_evaluations <= 32
    assert result.total_at_quantity <= result.budget < result.total_at_next


def test_capacity_uses_smaller_prior_median_share_and_dollar_limits() -> None:
    bars = tuple(_bar(index, volume=1000, close="10") for index in range(20))

    result = capacity_quantity(D("20"), bars, date(2026, 2, 1), LIQUIDITY)

    assert result is not None
    assert result.share_quantity == 100
    assert result.dollar_quantity == 50
    assert result.quantity == 50


def test_current_and_future_volume_cannot_change_capacity() -> None:
    prior = tuple(_bar(index, volume=1000) for index in range(20))
    signal_session = date(2026, 2, 1)
    current = replace(_bar(31, volume=10_000_000), session=signal_session)
    future = replace(_bar(32, volume=10_000_000), session=signal_session + timedelta(days=1))

    baseline = capacity_quantity(D("10"), prior, signal_session, LIQUIDITY)
    extended = capacity_quantity(D("10"), (*prior, current, future), signal_session, LIQUIDITY)

    assert extended == baseline


def test_missing_or_unverified_prior_volume_abstains() -> None:
    short = tuple(_bar(index) for index in range(19))
    assert capacity_quantity(D("10"), short, date(2026, 2, 1), LIQUIDITY) is None

    bars = list(_bar(index) for index in range(20))
    bars[-1] = replace(bars[-1], quality=DataQuality.UNVERIFIED)
    assert capacity_quantity(D("10"), bars, date(2026, 2, 1), LIQUIDITY) is None


def test_capacity_can_bind_below_risk_size() -> None:
    bars = tuple(_bar(index, volume=1000) for index in range(20))

    decision = size_instruction(
        equity=D("100000"),
        available_cash=D("100000"),
        limit=D("10"),
        stop=D("9"),
        bars=bars,
        signal_session=date(2026, 2, 1),
        cost_profile=exact_cost_profile("ASX", "fixed"),
        liquidity_profile=LIQUIDITY,
    )

    assert decision.status is DecisionStatus.QUALIFIED
    assert decision.quantity == decision.capacity_quantity < decision.risk_quantity


def test_below_two_shares_is_rejected() -> None:
    bars = tuple(_bar(index, volume=10) for index in range(20))

    decision = size_instruction(
        equity=D("100000"),
        available_cash=D("100000"),
        limit=D("10"),
        stop=D("9"),
        bars=bars,
        signal_session=date(2026, 2, 1),
        cost_profile=exact_cost_profile("ASX", "fixed"),
        liquidity_profile=LIQUIDITY,
    )

    assert decision.status is DecisionStatus.REJECTED
    assert decision.quantity == 1


def test_missing_liquidity_profile_abstains() -> None:
    bars = tuple(_bar(index) for index in range(20))

    decision = size_instruction(
        equity=D("100000"),
        available_cash=D("100000"),
        limit=D("10"),
        stop=D("9"),
        bars=bars,
        signal_session=date(2026, 2, 1),
        cost_profile=exact_cost_profile("ASX", "fixed"),
        liquidity_profile=None,
    )

    assert decision.status is DecisionStatus.ABSTAIN


@pytest.mark.parametrize("pricing_model", ["fixed", "tiered"])
def test_every_approved_profile_has_monotone_nondecreasing_total_risk(
    pricing_model: str,
) -> None:
    cost = exact_cost_profile("ASX", pricing_model)
    totals = [
        modeled_total_risk(quantity, D("10"), D("9"), cost, LIQUIDITY)
        for quantity in range(1001)
    ]

    assert totals == sorted(totals)


def test_sizing_decision_is_immutable_before_the_open() -> None:
    bars = tuple(_bar(index) for index in range(20))
    decision = size_instruction(
        equity=D("100000"),
        available_cash=D("100000"),
        limit=D("10"),
        stop=D("9"),
        bars=bars,
        signal_session=date(2026, 2, 1),
        cost_profile=exact_cost_profile("ASX", "fixed"),
        liquidity_profile=LIQUIDITY,
    )

    with pytest.raises(FrozenInstanceError):
        decision.quantity = decision.quantity + 1  # type: ignore[misc]

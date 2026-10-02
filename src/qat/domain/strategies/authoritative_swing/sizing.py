"""Exact Phase 2 costs, prior-data capacity, and whole-share risk sizing."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_FLOOR, Decimal, localcontext

from qat.domain.backtester.costs import MARKET_COST_PARAMETER_TEXT
from qat.domain.strategies.authoritative_swing.model import (
    DataQuality,
    DecisionStatus,
    FinalBar,
    RuleEvidence,
    RuleOutcome,
)
from qat.domain.strategies.authoritative_swing.numeric import NUMERIC_POLICY


@dataclass(frozen=True, slots=True)
class ExactCostProfile:
    version: str
    label: str
    commission_bps: Decimal
    min_commission: Decimal
    currency: str
    third_party_fees_passed_through: bool
    third_party_bps: Decimal

    def __post_init__(self) -> None:
        values = (self.commission_bps, self.min_commission, self.third_party_bps)
        if any(not value.is_finite() or value < 0 for value in values):
            raise ValueError("exact cost values must be finite and non-negative")

    def broker_charge(self, notional: Decimal) -> Decimal:
        """Commission floor plus proportional pass-through fees for one side."""

        if notional < 0 or not notional.is_finite():
            raise ValueError("notional must be finite and non-negative")
        if notional == 0:
            return Decimal(0)
        commission = max(
            self.min_commission,
            notional * self.commission_bps / Decimal(10_000),
        )
        third_party = notional * self.third_party_bps / Decimal(10_000)
        return commission + third_party


@dataclass(frozen=True, slots=True)
class LiquidityProfile:
    version: str
    max_participation: Decimal
    entry_impact_bps: Decimal
    stop_exit_impact_bps: Decimal
    provisional: bool = False

    def __post_init__(self) -> None:
        values = (self.max_participation, self.entry_impact_bps, self.stop_exit_impact_bps)
        if any(not value.is_finite() for value in values):
            raise ValueError("liquidity profile values must be finite")
        if not Decimal(0) < self.max_participation <= Decimal(1):
            raise ValueError("maximum participation must be in (0, 1]")
        if self.entry_impact_bps < 0 or self.stop_exit_impact_bps < 0:
            raise ValueError("impact rates must be non-negative")


@dataclass(frozen=True, slots=True)
class RiskSizeResult:
    quantity: int
    budget: Decimal
    safe_upper_bound: int
    cost_evaluations: int
    total_at_quantity: Decimal
    total_at_next: Decimal


@dataclass(frozen=True, slots=True)
class CapacityResult:
    quantity: int
    share_quantity: int
    dollar_quantity: int
    median_share_volume: Decimal
    median_dollar_volume: Decimal


@dataclass(frozen=True, slots=True)
class SizingDecision:
    status: DecisionStatus
    risk_quantity: int
    capacity_quantity: int
    cash_quantity: int
    quantity: int
    budget: Decimal
    modeled_total_risk: Decimal
    evidence: tuple[RuleEvidence, ...]


def exact_cost_profile(market: str, pricing_model: str) -> ExactCostProfile:
    parameters = MARKET_COST_PARAMETER_TEXT[(market, pricing_model)]
    return ExactCostProfile(
        version=f"{market.lower()}-{pricing_model}-exact-v1",
        label=parameters.label,
        commission_bps=Decimal(parameters.commission_bps),
        min_commission=Decimal(parameters.min_commission),
        currency=parameters.currency,
        third_party_fees_passed_through=parameters.third_party_fees_passed_through,
        third_party_bps=Decimal(parameters.third_party_bps),
    )


def _impact(notional: Decimal, bps: Decimal) -> Decimal:
    return notional * bps / Decimal(10_000)


def modeled_total_risk(
    quantity: int,
    limit: Decimal,
    stop: Decimal,
    cost_profile: ExactCostProfile,
    liquidity_profile: LiquidityProfile,
) -> Decimal:
    """Price risk plus modeled entry and stop-exit costs."""

    if quantity < 0:
        raise ValueError("quantity must be non-negative")
    if quantity == 0:
        return Decimal(0)
    if limit <= stop or stop <= 0:
        raise ValueError("limit must stand above a positive stop")
    shares = Decimal(quantity)
    entry_notional = shares * limit
    exit_notional = shares * stop
    price_risk = shares * (limit - stop)
    entry_cost = cost_profile.broker_charge(entry_notional) + _impact(
        entry_notional, liquidity_profile.entry_impact_bps
    )
    exit_cost = cost_profile.broker_charge(exit_notional) + _impact(
        exit_notional, liquidity_profile.stop_exit_impact_bps
    )
    return price_risk + entry_cost + exit_cost


def size_for_risk(
    equity: Decimal,
    limit: Decimal,
    stop: Decimal,
    cost_profile: ExactCostProfile,
    liquidity_profile: LiquidityProfile,
) -> RiskSizeResult:
    """Find the largest whole-share quantity within the 1% complete-cost budget."""

    if not equity.is_finite() or equity <= 0:
        raise ValueError("equity must be finite and positive")
    if not limit.is_finite() or not stop.is_finite() or limit <= stop or stop <= 0:
        raise ValueError("limit must be finite and stand above a positive stop")
    budget = equity * Decimal("0.01")
    with localcontext() as context:
        context.prec = NUMERIC_POLICY.precision
        context.rounding = NUMERIC_POLICY.rounding
        upper = int((budget / (limit - stop)).to_integral_value(rounding=ROUND_FLOOR))

    evaluations = 0

    def evaluate(quantity: int) -> Decimal:
        nonlocal evaluations
        evaluations += 1
        return modeled_total_risk(quantity, limit, stop, cost_profile, liquidity_profile)

    low = 0
    high = upper
    while low < high:
        midpoint = (low + high + 1) // 2
        if evaluate(midpoint) <= budget:
            low = midpoint
        else:
            high = midpoint - 1
    total = evaluate(low)
    total_next = evaluate(low + 1)
    return RiskSizeResult(low, budget, upper, evaluations, total, total_next)


def _median(values: Sequence[Decimal]) -> Decimal:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / Decimal(2)


def capacity_quantity(
    limit: Decimal,
    bars: Sequence[FinalBar],
    signal_session: date,
    liquidity_profile: LiquidityProfile,
) -> CapacityResult | None:
    """Calculate capacity from the 20 verified sessions strictly before signal."""

    if not limit.is_finite() or limit <= 0 or liquidity_profile.provisional:
        return None
    prior = tuple(
        sorted(
            (bar for bar in bars if bar.session < signal_session),
            key=lambda bar: (bar.session, bar.digest),
        )
    )[-20:]
    if len(prior) != 20:
        return None
    if any(
        not bar.finalized
        or bar.quality is not DataQuality.VERIFIED
        or bar.raw.volume <= 0
        or not bar.raw.close.is_finite()
        or bar.raw.close <= 0
        for bar in prior
    ):
        return None
    share_median = _median(tuple(Decimal(bar.raw.volume) for bar in prior))
    dollar_median = _median(
        tuple(bar.raw.close * Decimal(bar.raw.volume) for bar in prior)
    )
    share_quantity = int(
        (share_median * liquidity_profile.max_participation).to_integral_value(
            rounding=ROUND_FLOOR
        )
    )
    dollar_quantity = int(
        (
            dollar_median * liquidity_profile.max_participation / limit
        ).to_integral_value(rounding=ROUND_FLOOR)
    )
    return CapacityResult(
        min(share_quantity, dollar_quantity),
        share_quantity,
        dollar_quantity,
        share_median,
        dollar_median,
    )


def _cash_quantity(
    available_cash: Decimal,
    limit: Decimal,
    cost_profile: ExactCostProfile,
    liquidity_profile: LiquidityProfile,
) -> int:
    if not available_cash.is_finite() or available_cash <= 0:
        return 0
    upper = int((available_cash / limit).to_integral_value(rounding=ROUND_FLOOR))

    def needed(quantity: int) -> Decimal:
        notional = Decimal(quantity) * limit
        return (
            notional
            + cost_profile.broker_charge(notional)
            + _impact(notional, liquidity_profile.entry_impact_bps)
        )

    low = 0
    high = upper
    while low < high:
        midpoint = (low + high + 1) // 2
        if needed(midpoint) <= available_cash:
            low = midpoint
        else:
            high = midpoint - 1
    return low


def size_instruction(
    *,
    equity: Decimal,
    available_cash: Decimal,
    limit: Decimal,
    stop: Decimal,
    bars: Sequence[FinalBar],
    signal_session: date,
    cost_profile: ExactCostProfile,
    liquidity_profile: LiquidityProfile | None,
) -> SizingDecision:
    """Freeze the submitted quantity from risk, cash, and prior-data capacity."""

    if liquidity_profile is None or liquidity_profile.provisional:
        return SizingDecision(
            DecisionStatus.ABSTAIN,
            0,
            0,
            0,
            0,
            Decimal(0),
            Decimal(0),
            (
                RuleEvidence(
                    "liquidity_profile",
                    RuleOutcome.ABSTAIN,
                    reason="a frozen non-provisional liquidity profile is required",
                ),
            ),
        )
    try:
        risk = size_for_risk(equity, limit, stop, cost_profile, liquidity_profile)
    except ValueError as error:
        return SizingDecision(
            DecisionStatus.REJECTED,
            0,
            0,
            0,
            0,
            Decimal(0),
            Decimal(0),
            (RuleEvidence("risk_inputs", RuleOutcome.FAIL, reason=str(error)),),
        )
    capacity = capacity_quantity(limit, bars, signal_session, liquidity_profile)
    if capacity is None:
        return SizingDecision(
            DecisionStatus.ABSTAIN,
            risk.quantity,
            0,
            0,
            0,
            risk.budget,
            Decimal(0),
            (
                RuleEvidence(
                    "liquidity_capacity",
                    RuleOutcome.ABSTAIN,
                    reason="20 verified prior raw-volume sessions are required",
                ),
            ),
        )
    cash = _cash_quantity(available_cash, limit, cost_profile, liquidity_profile)
    quantity = min(risk.quantity, capacity.quantity, cash)
    total = modeled_total_risk(quantity, limit, stop, cost_profile, liquidity_profile)
    status = DecisionStatus.QUALIFIED if quantity >= 2 else DecisionStatus.REJECTED
    outcome = RuleOutcome.PASS if quantity >= 2 else RuleOutcome.FAIL
    evidence = (
        RuleEvidence(
            "risk_quantity",
            RuleOutcome.PASS,
            measured=risk.quantity,
            threshold=risk.budget,
        ),
        RuleEvidence(
            "liquidity_capacity",
            RuleOutcome.PASS,
            measured=capacity.quantity,
            threshold=liquidity_profile.max_participation,
        ),
        RuleEvidence("cash_quantity", RuleOutcome.PASS, measured=cash),
        RuleEvidence("minimum_quantity", outcome, measured=quantity, threshold=2),
        RuleEvidence(
            "modeled_total_risk",
            RuleOutcome.PASS,
            measured=total,
            threshold=risk.budget,
        ),
    )
    return SizingDecision(
        status,
        risk.quantity,
        capacity.quantity,
        cash,
        quantity,
        risk.budget,
        total,
        evidence,
    )

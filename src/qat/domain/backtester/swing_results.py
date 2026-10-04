"""Immutable evidence shapes shared by authoritative swing replays and reports."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum

from qat.domain.backtester.swing_events import DividendReceivable
from qat.domain.strategies.authoritative_swing.lifecycle import LifecycleAction
from qat.domain.strategies.authoritative_swing.model import (
    Pattern,
    RuleEvidence,
    SetupDecision,
)


class RunStatus(StrEnum):
    VALID = "valid"
    INVALID = "invalid"


class ReplayArm(StrEnum):
    EMA_PULLBACK = "ema_pullback"
    BULL_FLAG = "bull_flag"
    DOUBLE_BOTTOM = "double_bottom"
    COMBINED = "combined"


class PostFillResistanceDiagnostic(StrEnum):
    ABSTAIN = "post_fill_resistance_abstain"
    CLEAR = "post_fill_resistance_clear"
    INSIDE_ZONE = "post_fill_resistance_inside_zone"
    PATH_BLOCKED = "post_fill_resistance_path_blocked"


class LifecycleActionSeries(tuple[LifecycleAction, ...]):
    """Immutable lifecycle evidence with an exact reason-count helper."""

    def __new__(cls, values: Iterable[LifecycleAction] = ()) -> LifecycleActionSeries:
        return super().__new__(cls, values)

    def count_reason(self, reason: str) -> int:
        return sum(action.reason == reason for action in self)


@dataclass(frozen=True, slots=True)
class SimulatedFill:
    event_id: str
    symbol: str
    session: date
    side: str
    quantity: int
    price: Decimal
    cost: Decimal
    reason: str
    ambiguous: bool = False
    source_event_id: str | None = None

    def __post_init__(self) -> None:
        if not self.event_id or not self.symbol or not self.reason:
            raise ValueError("simulated fill identity, symbol, and reason are required")
        if self.side not in {"buy", "sell"} or self.quantity <= 0:
            raise ValueError("simulated fill side and quantity are invalid")
        if (
            not self.price.is_finite()
            or self.price < 0
            or (
                self.price == 0
                and (
                    self.side != "sell" or self.reason not in {"terminal_zero", "delisting_outcome"}
                )
            )
        ):
            raise ValueError("simulated fill price must be finite and positive")
        if not self.cost.is_finite() or self.cost < 0:
            raise ValueError("simulated fill cost must be finite and non-negative")
        if self.reason in {"terminal_zero", "delisting_outcome"} and not self.source_event_id:
            raise ValueError("terminal fill requires a source market-event identity")


@dataclass(frozen=True, slots=True)
class FillAmbiguity:
    event_id: str
    symbol: str
    session: date
    baseline_sequence: tuple[str, ...]
    optimistic_sequence: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.event_id or not self.symbol:
            raise ValueError("fill ambiguity identity and symbol are required")
        if self.baseline_sequence == self.optimistic_sequence:
            raise ValueError("fill ambiguity requires distinct feasible sequences")


@dataclass(frozen=True, slots=True)
class SwingTrade:
    trade_id: str
    symbol: str
    patterns: tuple[Pattern, ...]
    entry_session: date
    exit_session: date
    quantity: int
    submitted_limit: Decimal
    entry_price: Decimal
    exit_price: Decimal
    initial_stop: Decimal
    gross_pnl: Decimal
    eligible_dividends: Decimal
    costs: Decimal
    net_pnl: Decimal
    order_initial_risk_dollars: Decimal
    fill_initial_risk_dollars: Decimal
    order_r_multiple: Decimal
    fill_r_multiple: Decimal
    mfe_order_r: Decimal
    mae_order_r: Decimal
    mfe_fill_r: Decimal
    mae_fill_r: Decimal
    exit_reason: str
    observed_triggers: tuple[str, ...]
    post_fill_resistance: PostFillResistanceDiagnostic
    analysis_regime: str | None
    edge_sample_eligible: bool
    edge_exclusion_reason: str | None


@dataclass(frozen=True, slots=True)
class ReplayEquityPoint:
    session: date
    equity: Decimal
    cash: Decimal
    position_value: Decimal
    dividend_receivables: Decimal
    stale_marks: tuple[tuple[str, Decimal], ...] = ()
    position_marks: tuple[tuple[str, str, Decimal], ...] = ()


@dataclass(frozen=True, slots=True)
class CorporateActionEvidence:
    event_id: str
    kind: str
    position_id: str
    session: date
    symbol_before: str
    symbol_after: str
    quantity_before: int
    quantity_after: int
    entry_price_before: Decimal
    entry_price_after: Decimal
    stop_before: Decimal
    stop_after: Decimal
    target_before: Decimal | None
    target_after: Decimal | None


@dataclass(frozen=True, slots=True)
class SwingReplayResult:
    status: RunStatus
    arm: ReplayArm
    decisions: tuple[SetupDecision, ...]
    position_events: LifecycleActionSeries
    fills: tuple[SimulatedFill, ...]
    trades: tuple[SwingTrade, ...]
    signal_trades: tuple[SwingTrade, ...]
    equity: tuple[ReplayEquityPoint, ...]
    abstentions: tuple[RuleEvidence, ...]
    ambiguities: tuple[FillAmbiguity, ...]
    invalid_reasons: tuple[str, ...] = ()
    signal_decisions: tuple[SetupDecision, ...] = ()
    corporate_action_evidence: tuple[CorporateActionEvidence, ...] = ()
    dividend_entitlements: tuple[DividendReceivable, ...] = ()
    signal_corporate_action_evidence: tuple[CorporateActionEvidence, ...] = ()
    signal_dividend_entitlements: tuple[DividendReceivable, ...] = ()

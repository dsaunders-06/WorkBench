"""Pure, idempotent state transitions for authoritative swing positions."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from decimal import ROUND_CEILING, Decimal
from enum import StrEnum

from qat.domain.strategies.authoritative_swing.evidence import stable_decision_id
from qat.domain.strategies.authoritative_swing.model import (
    DecisionStatus,
    Pattern,
    SetupDecision,
)


class LifecycleInvariantError(ValueError):
    """Raised when an event cannot occur from the current lifecycle state."""


class PositionState(StrEnum):
    FLAT = "flat"
    ENTRY_PENDING = "entry_pending"
    OPEN_FULL = "open_full"
    RUNNER = "runner"
    EXIT_PENDING = "exit_pending"
    CLOSED = "closed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class ConfirmedFill:
    event_id: str
    session: date
    side: str
    quantity: int
    price: Decimal
    reason: str

    def __post_init__(self) -> None:
        if not self.event_id or not self.reason:
            raise ValueError("fill identity and reason are required")
        if self.side not in {"buy", "sell"}:
            raise ValueError("fill side must be buy or sell")
        if self.quantity <= 0:
            raise ValueError("fill quantity must be positive")
        if not self.price.is_finite() or self.price <= 0:
            raise ValueError("fill price must be finite and positive")


@dataclass(frozen=True, slots=True)
class LifecycleAction:
    event_id: str
    position_id: str
    symbol: str
    session: date
    previous_state: PositionState
    next_state: PositionState
    reason: str
    quantity: int = 0
    price: Decimal | None = None


@dataclass(frozen=True, slots=True)
class PendingEntry:
    instruction_id: str
    symbol: str
    state: PositionState
    signal_session: date
    submitted_limit: Decimal
    initial_stop: Decimal
    quantity: int
    patterns: tuple[Pattern, ...]
    pattern_instance_ids: frozenset[str]
    breakout_event_ids: frozenset[str]
    used_breakout_event_ids: frozenset[str]
    consumed_pattern_instance_ids: frozenset[str]
    applied_event_ids: frozenset[str]


@dataclass(frozen=True, slots=True)
class SwingPosition:
    position_id: str
    instruction_id: str
    symbol: str
    state: PositionState
    patterns: tuple[Pattern, ...]
    entry_session: date
    submitted_limit: Decimal
    entry_fill: Decimal
    initial_stop: Decimal
    current_stop: Decimal
    initial_r: Decimal
    order_initial_risk_dollars: Decimal
    fill_initial_risk_dollars: Decimal
    total_quantity: int
    banked_quantity: int
    runner_quantity: int
    target_price: Decimal
    completed_sessions: int
    highest_high: Decimal
    used_breakout_event_ids: frozenset[str]
    consumed_pattern_instance_ids: frozenset[str]
    applied_event_ids: frozenset[str]

    @property
    def open_quantity(self) -> int:
        if self.state in {PositionState.CLOSED, PositionState.CANCELLED}:
            return 0
        if self.state is PositionState.RUNNER:
            return self.runner_quantity
        return self.total_quantity


def pending_entry_from_setup(decision: SetupDecision) -> PendingEntry:
    """Create one fixed-quantity instruction from qualified Phase 2A evidence."""

    if decision.status is not DecisionStatus.QUALIFIED:
        raise LifecycleInvariantError("only qualified setup evidence can become an instruction")
    if decision.entry_limit_raw is None or decision.initial_stop_raw is None:
        raise LifecycleInvariantError("qualified instruction requires limit and stop")
    if (
        not decision.entry_limit_raw.is_finite()
        or not decision.initial_stop_raw.is_finite()
        or decision.entry_limit_raw <= decision.initial_stop_raw
        or decision.initial_stop_raw <= 0
    ):
        raise LifecycleInvariantError("instruction requires a finite limit above a positive stop")
    if decision.quantity < 2:
        raise LifecycleInvariantError("instruction requires at least two shares")
    candidates = tuple(
        item.candidate
        for item in decision.pattern_decisions
        if item.status is DecisionStatus.QUALIFIED and item.candidate is not None
    )
    pattern_ids = frozenset(item.pattern_instance_id for item in candidates)
    if not pattern_ids:
        raise LifecycleInvariantError("qualified instruction requires pattern identity")
    breakout_ids = frozenset(
        item.breakout_event_id for item in candidates if item.breakout_event_id is not None
    )
    return PendingEntry(
        instruction_id=decision.decision_id,
        symbol=decision.symbol,
        state=PositionState.ENTRY_PENDING,
        signal_session=decision.session,
        submitted_limit=decision.entry_limit_raw,
        initial_stop=decision.initial_stop_raw,
        quantity=decision.quantity,
        patterns=decision.patterns,
        pattern_instance_ids=pattern_ids,
        breakout_event_ids=breakout_ids,
        used_breakout_event_ids=breakout_ids,
        consumed_pattern_instance_ids=frozenset(),
        applied_event_ids=frozenset(),
    )


def apply_entry_fill(
    current: PendingEntry | SwingPosition, fill: ConfirmedFill
) -> SwingPosition:
    """Confirm an entry once and define actual-fill R without resizing."""

    if fill.event_id in current.applied_event_ids:
        if isinstance(current, SwingPosition):
            return current
        raise LifecycleInvariantError("pending entry cannot contain an applied fill")
    if not isinstance(current, PendingEntry) or current.state is not PositionState.ENTRY_PENDING:
        raise LifecycleInvariantError("entry fill requires a pending entry")
    if fill.side != "buy":
        raise LifecycleInvariantError("entry fill must be a buy")
    if fill.session <= current.signal_session:
        raise LifecycleInvariantError("entry fill must follow the signal session")
    if fill.quantity != current.quantity:
        raise LifecycleInvariantError("entry fill must preserve the submitted quantity")
    if fill.price > current.submitted_limit:
        raise LifecycleInvariantError("buy fill cannot exceed the submitted limit")
    if fill.price <= current.initial_stop:
        raise LifecycleInvariantError("entry fill must stand above the structural stop")

    initial_r = fill.price - current.initial_stop
    shares = Decimal(fill.quantity)
    banked = int((shares / Decimal(2)).to_integral_value(rounding=ROUND_CEILING))
    runner = fill.quantity - banked
    position_id = stable_decision_id(
        {
            "instruction_id": current.instruction_id,
            "entry_event_id": fill.event_id,
            "entry_session": fill.session,
            "entry_price": fill.price,
            "quantity": fill.quantity,
        }
    )
    return SwingPosition(
        position_id=position_id,
        instruction_id=current.instruction_id,
        symbol=current.symbol,
        state=PositionState.OPEN_FULL,
        patterns=current.patterns,
        entry_session=fill.session,
        submitted_limit=current.submitted_limit,
        entry_fill=fill.price,
        initial_stop=current.initial_stop,
        current_stop=current.initial_stop,
        initial_r=initial_r,
        order_initial_risk_dollars=shares * (current.submitted_limit - current.initial_stop),
        fill_initial_risk_dollars=shares * initial_r,
        total_quantity=fill.quantity,
        banked_quantity=banked,
        runner_quantity=runner,
        target_price=fill.price + initial_r,
        completed_sessions=1,
        highest_high=fill.price,
        used_breakout_event_ids=current.used_breakout_event_ids,
        consumed_pattern_instance_ids=current.pattern_instance_ids,
        applied_event_ids=current.applied_event_ids | {fill.event_id},
    )


def apply_exit_fill(position: SwingPosition, fill: ConfirmedFill) -> SwingPosition:
    """Apply a complete exit once; partial target fills use the Task 2 reducer."""

    if fill.event_id in position.applied_event_ids:
        return position
    if position.state not in {
        PositionState.OPEN_FULL,
        PositionState.RUNNER,
        PositionState.EXIT_PENDING,
    }:
        raise LifecycleInvariantError("exit fill requires an open position")
    if fill.side != "sell":
        raise LifecycleInvariantError("exit fill must be a sell")
    if fill.session < position.entry_session:
        raise LifecycleInvariantError("exit cannot precede entry")
    if fill.quantity != position.open_quantity:
        raise LifecycleInvariantError("complete exit must close the current quantity")
    return replace(
        position,
        state=PositionState.CLOSED,
        applied_event_ids=position.applied_event_ids | {fill.event_id},
    )


def cancel_pending_entry(
    current: PendingEntry | SwingPosition,
    event_id: str,
    reason: str,
) -> PendingEntry:
    """Cancel one unfilled instruction while retaining its used breakout identity."""

    if not event_id or not reason:
        raise ValueError("cancellation identity and reason are required")
    if event_id in current.applied_event_ids:
        if isinstance(current, PendingEntry):
            return current
        raise LifecycleInvariantError("position cannot replay an entry cancellation")
    if not isinstance(current, PendingEntry) or current.state is not PositionState.ENTRY_PENDING:
        raise LifecycleInvariantError("only a pending entry can be cancelled")
    return replace(
        current,
        state=PositionState.CANCELLED,
        applied_event_ids=current.applied_event_ids | {event_id},
    )

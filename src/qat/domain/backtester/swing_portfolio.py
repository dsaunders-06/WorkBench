"""Exact cash-funded portfolio accounting for authoritative swing replay."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal

from qat.domain.backtester.swing_results import ReplayEquityPoint, SimulatedFill
from qat.domain.strategies.authoritative_swing.lifecycle import SwingPosition
from qat.domain.strategies.authoritative_swing.model import DecisionStatus, SetupDecision
from qat.domain.strategies.authoritative_swing.sizing import (
    ExactCostProfile,
    LiquidityProfile,
    modeled_total_risk,
    size_for_risk,
)


class PortfolioInvariantError(ValueError):
    """Raised when portfolio cash or allocation invariants would be violated."""


@dataclass(frozen=True, slots=True)
class EntryAllocation:
    decision: SetupDecision
    symbol: str
    desired_quantity: int
    quantity: int
    scale_factor: Decimal
    reserved_cash: Decimal
    notional_exposure: Decimal
    zero_price_equity_loss: Decimal
    stop_distance: Decimal
    cost_to_risk_ratio: Decimal


@dataclass(frozen=True, slots=True)
class PortfolioState:
    starting_equity: Decimal
    cash: Decimal
    positions: tuple[SwingPosition, ...] = ()
    pending_allocations: tuple[EntryAllocation, ...] = ()
    dividend_receivables: Decimal = Decimal(0)
    applied_fill_ids: frozenset[str] = frozenset()
    applied_dividend_ids: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        values = (self.starting_equity, self.cash, self.dividend_receivables)
        if any(not value.is_finite() or value < 0 for value in values):
            raise ValueError("portfolio money values must be finite and non-negative")
        if self.starting_equity <= 0:
            raise ValueError("portfolio starting equity must be positive")
        if self.reserved_cash > self.cash:
            raise ValueError("pending purchase reservations cannot exceed cash")

    @property
    def reserved_cash(self) -> Decimal:
        return sum((item.reserved_cash for item in self.pending_allocations), Decimal(0))

    @property
    def available_cash(self) -> Decimal:
        return self.cash - self.reserved_cash


def _validated_candidates(candidates: Sequence[SetupDecision]) -> tuple[SetupDecision, ...]:
    ordered = tuple(sorted(candidates, key=lambda item: (item.symbol, item.decision_id)))
    symbols = tuple(item.symbol for item in ordered)
    if len(symbols) != len(set(symbols)):
        raise PortfolioInvariantError("entry batch permits at most one candidate per symbol")
    for item in ordered:
        if (
            item.status is not DecisionStatus.QUALIFIED
            or item.entry_limit_raw is None
            or item.initial_stop_raw is None
            or item.quantity < 2
        ):
            raise PortfolioInvariantError("entry batch requires complete qualified candidates")
    return ordered


def _reservation(
    quantity: int,
    limit: Decimal,
    costs: ExactCostProfile,
) -> Decimal:
    notional = Decimal(quantity) * limit
    return notional + costs.broker_charge(notional)


def _allocation(
    decision: SetupDecision,
    quantity: int,
    scale: Decimal,
    equity: Decimal,
    costs: ExactCostProfile,
    liquidity: LiquidityProfile,
) -> EntryAllocation:
    limit = decision.entry_limit_raw
    stop = decision.initial_stop_raw
    if limit is None or stop is None:
        raise PortfolioInvariantError("qualified allocation requires limit and stop")
    shares = Decimal(quantity)
    notional = shares * limit
    price_risk = shares * (limit - stop)
    total_risk = modeled_total_risk(quantity, limit, stop, costs, liquidity)
    cost_risk = total_risk - price_risk
    return EntryAllocation(
        decision=decision,
        symbol=decision.symbol,
        desired_quantity=decision.quantity,
        quantity=quantity,
        scale_factor=scale,
        reserved_cash=_reservation(quantity, limit, costs),
        notional_exposure=notional,
        zero_price_equity_loss=notional / equity,
        stop_distance=(limit - stop) / limit,
        cost_to_risk_ratio=cost_risk / price_risk,
    )


def allocate_entry_batch(
    cash: Decimal,
    candidates: Sequence[SetupDecision],
    costs: ExactCostProfile,
    liquidity: LiquidityProfile,
    *,
    current_equity: Decimal | None = None,
) -> tuple[EntryAllocation, ...]:
    """Allocate one simultaneous batch with a common iterative risk scale."""

    if not cash.is_finite() or cash <= 0:
        raise PortfolioInvariantError("allocatable cash must be finite and positive")
    equity = cash if current_equity is None else current_equity
    if not equity.is_finite() or equity < cash:
        raise PortfolioInvariantError("current equity must include allocatable cash")
    ordered = _validated_candidates(candidates)
    if not ordered:
        return ()
    desired_reservation = sum(
        (
            _reservation(item.quantity, item.entry_limit_raw, costs)  # type: ignore[arg-type]
            for item in ordered
        ),
        Decimal(0),
    )
    if desired_reservation <= cash:
        return tuple(
            _allocation(item, item.quantity, Decimal(1), equity, costs, liquidity)
            for item in ordered
        )

    scale = cash / desired_reservation
    for _ in range(64):
        funded: list[EntryAllocation] = []
        for item in ordered:
            limit = item.entry_limit_raw
            stop = item.initial_stop_raw
            if limit is None or stop is None:
                raise PortfolioInvariantError("qualified allocation requires limit and stop")
            original_risk = modeled_total_risk(item.quantity, limit, stop, costs, liquidity)
            scaled = size_for_risk(
                original_risk * scale * Decimal(100),
                limit,
                stop,
                costs,
                liquidity,
            )
            quantity = min(item.quantity, scaled.quantity)
            if quantity < 2:
                continue
            funded.append(_allocation(item, quantity, scale, equity, costs, liquidity))
        if not funded:
            return ()
        total = sum((item.reserved_cash for item in funded), Decimal(0))
        if total <= cash:
            return tuple(funded)
        scale *= cash / total
    raise PortfolioInvariantError("entry allocation failed to converge")


def apply_fills(
    state: PortfolioState,
    fills: Sequence[SimulatedFill],
) -> PortfolioState:
    """Apply ordered cash effects exactly once for each immutable fill ID."""

    cash = state.cash
    applied = set(state.applied_fill_ids)
    pending = list(state.pending_allocations)
    for fill in fills:
        if fill.event_id in applied:
            continue
        notional = Decimal(fill.quantity) * fill.price
        if fill.side == "buy":
            cash -= notional + fill.cost
            pending = [item for item in pending if item.symbol != fill.symbol]
        elif fill.side == "sell":
            cash += notional - fill.cost
        else:  # pragma: no cover - SimulatedFill validates this
            raise PortfolioInvariantError("unknown fill side")
        if cash < 0:
            raise PortfolioInvariantError("fill would create negative cash")
        applied.add(fill.event_id)
    return replace(
        state,
        cash=cash,
        pending_allocations=tuple(pending),
        applied_fill_ids=frozenset(applied),
    )


def apply_dividend_cash(
    state: PortfolioState,
    event_id: str,
    amount: Decimal,
) -> PortfolioState:
    """Settle one previously accrued receivable into spendable cash."""

    if event_id in state.applied_dividend_ids:
        return state
    if not event_id or not amount.is_finite() or amount < 0:
        raise PortfolioInvariantError("dividend settlement is invalid")
    if amount > state.dividend_receivables:
        raise PortfolioInvariantError("dividend settlement exceeds receivables")
    return replace(
        state,
        cash=state.cash + amount,
        dividend_receivables=state.dividend_receivables - amount,
        applied_dividend_ids=state.applied_dividend_ids | {event_id},
    )


def mark_to_market(
    state: PortfolioState,
    session: date,
    closing_prices: Mapping[str, Decimal],
    stale_marks: tuple[tuple[str, Decimal], ...] = (),
) -> ReplayEquityPoint:
    """Mark open quantities at exact raw closes without changing cash."""

    position_marks: list[tuple[str, str, Decimal]] = []
    for position in state.positions:
        price = closing_prices.get(position.symbol)
        if price is None or not price.is_finite() or price < 0:
            raise PortfolioInvariantError(f"missing valid close for {position.symbol}")
        if position.open_quantity:
            position_marks.append(
                (position.position_id, position.symbol, Decimal(position.open_quantity) * price)
            )
    position_marks.sort(key=lambda mark: (mark[0], mark[1]))
    position_value = sum((mark[2] for mark in position_marks), Decimal(0))
    equity = state.cash + position_value + state.dividend_receivables
    return ReplayEquityPoint(
        session,
        equity,
        state.cash,
        position_value,
        state.dividend_receivables,
        stale_marks,
        tuple(position_marks),
    )

"""Conservative exact-decimal daily-bar fills for authoritative swing replay."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum

from qat.domain.backtester.swing_results import FillAmbiguity, SimulatedFill
from qat.domain.strategies.authoritative_swing.evidence import stable_decision_id
from qat.domain.strategies.authoritative_swing.lifecycle import (
    PendingEntry,
    PositionState,
    SwingPosition,
)
from qat.domain.strategies.authoritative_swing.sizing import (
    ExactCostProfile,
    LiquidityProfile,
)

_BPS = Decimal(10_000)


class AmbiguityPolicy(StrEnum):
    CONSERVATIVE = "conservative"
    OPTIMISTIC = "optimistic"


@dataclass(frozen=True, slots=True)
class TradedDailyBar:
    symbol: str
    session: date
    open: Decimal | None
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int

    def __post_init__(self) -> None:
        if not self.symbol:
            raise ValueError("traded bar requires a symbol")
        values = (self.high, self.low, self.close)
        if any(not value.is_finite() or value <= 0 for value in values):
            raise ValueError("traded bar prices must be finite and positive")
        if self.open is not None and (not self.open.is_finite() or self.open <= 0):
            raise ValueError("traded open must be finite and positive when present")
        observed = values + (() if self.open is None else (self.open,))
        if self.high < max(observed) or self.low > min(observed) or self.high < self.low:
            raise ValueError("traded bar OHLC values are inconsistent")
        if self.volume < 0:
            raise ValueError("traded volume cannot be negative")


def _slipped_buy(price: Decimal, profile: LiquidityProfile) -> Decimal:
    return price * (Decimal(1) + profile.entry_impact_bps / _BPS)


def _slipped_sell(price: Decimal, profile: LiquidityProfile) -> Decimal:
    return price * (Decimal(1) - profile.stop_exit_impact_bps / _BPS)


def _fill(
    *,
    position_key: str,
    symbol: str,
    session: date,
    side: str,
    quantity: int,
    price: Decimal,
    reason: str,
    costs: ExactCostProfile,
    ambiguous: bool = False,
) -> SimulatedFill:
    event_id = stable_decision_id(
        {
            "position_key": position_key,
            "session": session,
            "side": side,
            "quantity": quantity,
            "price": price,
            "reason": reason,
            "ambiguous": ambiguous,
        }
    )
    return SimulatedFill(
        event_id=event_id,
        symbol=symbol,
        session=session,
        side=side,
        quantity=quantity,
        price=price,
        cost=costs.broker_charge(Decimal(quantity) * price),
        reason=reason,
        ambiguous=ambiguous,
    )


def resolve_entry_open(
    pending: PendingEntry,
    bar: TradedDailyBar,
    costs: ExactCostProfile,
    liquidity: LiquidityProfile,
) -> tuple[SimulatedFill, ...]:
    """Resolve a one-session fixed-quantity entry instruction at the auction open."""

    if pending.state is not PositionState.ENTRY_PENDING:
        return ()
    if bar.symbol != pending.symbol or bar.session <= pending.signal_session:
        return ()
    if bar.open is None or bar.volume <= 0:
        return ()
    if bar.open > pending.submitted_limit or bar.open <= pending.initial_stop:
        return ()
    price = min(pending.submitted_limit, _slipped_buy(bar.open, liquidity))
    return (
        _fill(
            position_key=pending.instruction_id,
            symbol=pending.symbol,
            session=bar.session,
            side="buy",
            quantity=pending.quantity,
            price=price,
            reason="entry",
            costs=costs,
        ),
    )


def resolve_open_exit(
    position: SwingPosition,
    bar: TradedDailyBar,
    costs: ExactCostProfile,
    liquidity: LiquidityProfile,
) -> tuple[SimulatedFill, ...]:
    """Resolve gap protection before any scheduled next-open replacement exit."""

    if position.state not in {
        PositionState.OPEN_FULL,
        PositionState.RUNNER,
        PositionState.EXIT_PENDING,
    }:
        return ()
    if bar.symbol != position.symbol or bar.session < position.entry_session:
        return ()
    if bar.open is None or bar.volume <= 0:
        return ()
    reason: str | None = None
    if bar.open <= position.current_stop:
        reason = "protective_stop"
    elif position.state is PositionState.EXIT_PENDING:
        reason = "scheduled_open_exit"
    if reason is None:
        return ()
    price = _slipped_sell(bar.open, liquidity)
    return (
        _fill(
            position_key=position.position_id,
            symbol=position.symbol,
            session=bar.session,
            side="sell",
            quantity=position.open_quantity,
            price=price,
            reason=reason,
            costs=costs,
        ),
    )


def _protective_stop_fill(
    position: SwingPosition,
    bar: TradedDailyBar,
    costs: ExactCostProfile,
    liquidity: LiquidityProfile,
    *,
    ambiguous: bool,
    quantity: int | None = None,
    reason: str = "protective_stop",
) -> SimulatedFill:
    reference = (
        bar.open
        if bar.open is not None and bar.open <= position.current_stop
        else position.current_stop
    )
    return _fill(
        position_key=position.position_id,
        symbol=position.symbol,
        session=bar.session,
        side="sell",
        quantity=position.open_quantity if quantity is None else quantity,
        price=_slipped_sell(reference, liquidity),
        reason=reason,
        costs=costs,
        ambiguous=ambiguous,
    )


def _target_fill(
    position: SwingPosition,
    bar: TradedDailyBar,
    costs: ExactCostProfile,
    liquidity: LiquidityProfile,
    *,
    ambiguous: bool,
) -> SimulatedFill:
    price = position.target_price
    if bar.open is not None and bar.open >= position.target_price:
        price = max(position.target_price, _slipped_sell(bar.open, liquidity))
    return _fill(
        position_key=position.position_id,
        symbol=position.symbol,
        session=bar.session,
        side="sell",
        quantity=position.banked_quantity,
        price=price,
        reason="banked_target",
        costs=costs,
        ambiguous=ambiguous,
    )


def _runner_breakeven_fill(
    position: SwingPosition,
    bar: TradedDailyBar,
    costs: ExactCostProfile,
    liquidity: LiquidityProfile,
    *,
    ambiguous: bool,
) -> SimulatedFill:
    return _fill(
        position_key=position.position_id,
        symbol=position.symbol,
        session=bar.session,
        side="sell",
        quantity=position.runner_quantity,
        price=_slipped_sell(position.entry_fill, liquidity),
        reason="runner_breakeven",
        costs=costs,
        ambiguous=ambiguous,
    )


def resolve_protective_session(
    position: SwingPosition,
    bar: TradedDailyBar,
    costs: ExactCostProfile,
    liquidity: LiquidityProfile,
    *,
    policy: AmbiguityPolicy = AmbiguityPolicy.CONSERVATIVE,
) -> tuple[SimulatedFill, ...]:
    """Resolve stop/target paths in the strategy's selected feasible sequence."""

    if position.state not in {
        PositionState.OPEN_FULL,
        PositionState.RUNNER,
        PositionState.EXIT_PENDING,
    }:
        return ()
    if bar.symbol != position.symbol or bar.session < position.entry_session or bar.volume <= 0:
        return ()

    if bar.open is not None and bar.open <= position.current_stop:
        return (
            _protective_stop_fill(
                position,
                bar,
                costs,
                liquidity,
                ambiguous=False,
            ),
        )

    if (
        position.state is PositionState.OPEN_FULL
        and bar.open is not None
        and bar.open >= position.target_price
    ):
        target = _target_fill(position, bar, costs, liquidity, ambiguous=False)
        if bar.low > position.entry_fill:
            return (target,)
        return (
            target,
            _runner_breakeven_fill(position, bar, costs, liquidity, ambiguous=False),
        )

    stop_touched = bar.low <= position.current_stop
    target_touched = position.state is PositionState.OPEN_FULL and bar.high >= position.target_price
    if position.state is not PositionState.OPEN_FULL:
        if not stop_touched:
            return ()
        return (
            _protective_stop_fill(
                position,
                bar,
                costs,
                liquidity,
                ambiguous=False,
            ),
        )

    if stop_touched and target_touched:
        if policy is AmbiguityPolicy.CONSERVATIVE:
            return (
                _protective_stop_fill(
                    position,
                    bar,
                    costs,
                    liquidity,
                    ambiguous=True,
                ),
            )
        return (
            _target_fill(position, bar, costs, liquidity, ambiguous=True),
            _runner_breakeven_fill(position, bar, costs, liquidity, ambiguous=True),
        )
    if stop_touched:
        return (
            _protective_stop_fill(
                position,
                bar,
                costs,
                liquidity,
                ambiguous=False,
            ),
        )
    if not target_touched:
        return ()

    breakeven_reachable = bar.low <= position.entry_fill
    ambiguous = breakeven_reachable
    target = _target_fill(position, bar, costs, liquidity, ambiguous=ambiguous)
    if not breakeven_reachable or policy is AmbiguityPolicy.OPTIMISTIC:
        return (target,)
    return (
        target,
        _runner_breakeven_fill(position, bar, costs, liquidity, ambiguous=True),
    )


def ambiguity_for_session(
    position: SwingPosition,
    bar: TradedDailyBar,
    costs: ExactCostProfile,
    liquidity: LiquidityProfile,
) -> FillAmbiguity | None:
    """Return the frozen baseline and optimistic reason sequences when they differ."""

    baseline = resolve_protective_session(
        position,
        bar,
        costs,
        liquidity,
        policy=AmbiguityPolicy.CONSERVATIVE,
    )
    optimistic = resolve_protective_session(
        position,
        bar,
        costs,
        liquidity,
        policy=AmbiguityPolicy.OPTIMISTIC,
    )
    baseline_sequence = tuple(fill.reason for fill in baseline)
    optimistic_sequence = tuple(fill.reason for fill in optimistic)
    if baseline_sequence == optimistic_sequence:
        return None
    event_id = stable_decision_id(
        {
            "kind": "fill_ambiguity",
            "position_id": position.position_id,
            "session": bar.session,
            "baseline": baseline_sequence,
            "optimistic": optimistic_sequence,
        }
    )
    return FillAmbiguity(
        event_id,
        position.symbol,
        bar.session,
        baseline_sequence,
        optimistic_sequence,
    )

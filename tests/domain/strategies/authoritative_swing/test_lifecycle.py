"""State-machine tests for authoritative swing positions."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from qat.domain.strategies.authoritative_swing.lifecycle import (
    ConfirmedFill,
    LifecycleInvariantError,
    PositionState,
    apply_entry_fill,
    apply_exit_fill,
    cancel_pending_entry,
    pending_entry_from_setup,
)
from qat.domain.strategies.authoritative_swing.model import (
    DecisionStatus,
    Pattern,
    PatternCandidate,
    PatternDecision,
    SetupDecision,
)


def D(value: str | int) -> Decimal:
    return Decimal(value)


def _setup(*, quantity: int = 5) -> SetupDecision:
    candidate = PatternCandidate(
        pattern=Pattern.DOUBLE_BOTTOM,
        pattern_instance_id="pair-1",
        breakout_event_id="cross-1",
        signal_session=date(2026, 1, 5),
        analytical_signal_close=D("10"),
        analytical_invalidation=D("9"),
        analytical_atr14=D("0.5"),
    )
    pattern = PatternDecision(
        pattern=Pattern.DOUBLE_BOTTOM,
        status=DecisionStatus.QUALIFIED,
        rules=(),
        candidate=candidate,
    )
    return SetupDecision(
        strategy_version="phase2-swing-v1",
        schema_version="swing-evidence-v1",
        decision_id="decision-1",
        symbol="BHP.AX",
        session=date(2026, 1, 5),
        status=DecisionStatus.QUALIFIED,
        patterns=(Pattern.DOUBLE_BOTTOM,),
        pattern_decisions=(pattern,),
        entry_limit_raw=D("10"),
        initial_stop_raw=D("9"),
        risk_quantity=quantity,
        capacity_quantity=quantity,
        quantity=quantity,
        input_digests=("bar-1",),
    )


def _fill(
    *,
    event_id: str = "fill-1",
    side: str = "buy",
    price: str = "10",
    quantity: int = 5,
    session: date = date(2026, 1, 6),
) -> ConfirmedFill:
    return ConfirmedFill(event_id, session, side, quantity, D(price), "fixture")


@pytest.mark.parametrize(("quantity", "banked", "runner"), [(3, 2, 1), (5, 3, 2)])
def test_entry_fill_defines_r_and_rounds_banked_half_up(
    quantity: int, banked: int, runner: int
) -> None:
    pending = pending_entry_from_setup(_setup(quantity=quantity))

    position = apply_entry_fill(pending, _fill(quantity=quantity))

    assert position.state is PositionState.OPEN_FULL
    assert position.initial_r == D("1")
    assert position.banked_quantity == banked
    assert position.runner_quantity == runner
    assert position.target_price == D("11")
    assert position.completed_sessions == 1


def test_entry_fill_records_both_risk_denominators_without_resizing() -> None:
    pending = pending_entry_from_setup(_setup(quantity=5))

    position = apply_entry_fill(pending, _fill(price="9.75", quantity=5))

    assert position.total_quantity == 5
    assert position.initial_r == D("0.75")
    assert position.fill_initial_risk_dollars == D("3.75")
    assert position.order_initial_risk_dollars == D("5")
    assert position.target_price == D("10.50")


def test_replaying_entry_and_exit_fill_ids_is_a_no_op() -> None:
    pending = pending_entry_from_setup(_setup())
    entry = _fill()
    once = apply_entry_fill(pending, entry)

    assert apply_entry_fill(once, entry) == once

    exit_fill = _fill(event_id="exit-1", side="sell", price="9.5")
    closed = apply_exit_fill(once, exit_fill)
    assert closed.state is PositionState.CLOSED
    assert apply_exit_fill(closed, exit_fill) == closed


def test_confirmed_fill_consumes_breakout_and_pattern_identity() -> None:
    pending = pending_entry_from_setup(_setup())
    assert pending.used_breakout_event_ids == frozenset({"cross-1"})
    assert not pending.consumed_pattern_instance_ids

    position = apply_entry_fill(pending, _fill())

    assert position.used_breakout_event_ids == frozenset({"cross-1"})
    assert position.consumed_pattern_instance_ids == frozenset({"pair-1"})


def test_cancel_consumes_only_breakout_event_and_is_idempotent() -> None:
    pending = pending_entry_from_setup(_setup())

    cancelled = cancel_pending_entry(pending, "cancel-1", "gap_above_limit")

    assert cancelled.state is PositionState.CANCELLED
    assert cancelled.used_breakout_event_ids == frozenset({"cross-1"})
    assert not cancelled.consumed_pattern_instance_ids
    assert cancel_pending_entry(cancelled, "cancel-1", "gap_above_limit") == cancelled


@pytest.mark.parametrize(("price", "quantity"), [("9", 5), ("8.99", 5), ("10", 4)])
def test_entry_fill_rejects_invalid_price_or_quantity(price: str, quantity: int) -> None:
    pending = pending_entry_from_setup(_setup())

    with pytest.raises(LifecycleInvariantError):
        apply_entry_fill(pending, _fill(price=price, quantity=quantity))


def test_invalid_transitions_raise_but_duplicate_ids_do_not() -> None:
    pending = pending_entry_from_setup(_setup())
    position = apply_entry_fill(pending, _fill())

    with pytest.raises(LifecycleInvariantError):
        apply_entry_fill(position, _fill(event_id="other-entry"))
    with pytest.raises(LifecycleInvariantError):
        apply_exit_fill(position, _fill(event_id="buy-2"))
    with pytest.raises(LifecycleInvariantError):
        cancel_pending_entry(position, "cancel-2", "late")


def test_setup_must_be_a_complete_qualified_two_share_instruction() -> None:
    with pytest.raises(LifecycleInvariantError):
        pending_entry_from_setup(replace(_setup(), status=DecisionStatus.REJECTED))
    with pytest.raises(LifecycleInvariantError):
        pending_entry_from_setup(replace(_setup(), quantity=1))
    with pytest.raises(LifecycleInvariantError):
        pending_entry_from_setup(replace(_setup(), entry_limit_raw=None))

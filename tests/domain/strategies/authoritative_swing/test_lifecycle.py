"""State-machine tests for authoritative swing positions."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from qat.domain.strategies.authoritative_swing.lifecycle import (
    CompletedSession,
    ConfirmedFill,
    LifecycleInvariantError,
    PositionState,
    apply_entry_fill,
    apply_exit_fill,
    apply_target_fill,
    cancel_pending_entry,
    evaluate_completed_close,
    pending_entry_from_setup,
    schedule_exit,
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


def _position(*, quantity: int = 5):
    return apply_entry_fill(
        pending_entry_from_setup(_setup(quantity=quantity)),
        _fill(quantity=quantity),
    )


def _bar(
    session: date,
    *,
    high: str = "10.5",
    close: str = "10.2",
) -> CompletedSession:
    return CompletedSession(session, D(high), D(close))


def test_target_fill_moves_runner_to_breakeven_and_is_idempotent() -> None:
    position = _position()
    target = _fill(
        event_id="target-1",
        side="sell",
        price="11",
        quantity=position.banked_quantity,
        session=date(2026, 1, 7),
    )

    runner = apply_target_fill(position, target)

    assert runner.state is PositionState.RUNNER
    assert runner.current_stop == runner.entry_fill
    assert runner.open_quantity == runner.runner_quantity == 2
    assert runner.target_fill_session == date(2026, 1, 7)
    assert apply_target_fill(runner, target) == runner


def test_trail_starts_after_later_close_and_never_moves_down() -> None:
    position = _position()
    runner = apply_target_fill(
        position,
        _fill(
            event_id="target-1",
            side="sell",
            price="11",
            quantity=position.banked_quantity,
            session=date(2026, 1, 7),
        ),
    )

    same_day = evaluate_completed_close(
        runner, _bar(date(2026, 1, 7), high="13"), ema20=D("10"), atr14=D("1")
    )
    first = evaluate_completed_close(
        same_day.position,
        _bar(date(2026, 1, 8), high="13"),
        ema20=D("10"),
        atr14=D("1"),
    )
    second = evaluate_completed_close(
        first.position,
        _bar(date(2026, 1, 9), high="12"),
        ema20=D("10"),
        atr14=D("1.5"),
    )

    assert same_day.position.current_stop == D("10")
    assert first.position.current_stop == D("11")
    assert second.position.current_stop == D("11")


def test_daily_close_invalidation_records_both_simultaneous_conditions() -> None:
    position = _position()
    first = evaluate_completed_close(
        position,
        _bar(date(2026, 1, 6), close="9.9"),
        ema20=D("10"),
        atr14=D("1"),
    )
    second = evaluate_completed_close(
        first.position,
        _bar(date(2026, 1, 7), close="9.5"),
        ema20=D("10"),
        atr14=D("1"),
    )

    assert second.position.state is PositionState.EXIT_PENDING
    assert second.triggers == (
        "ema_half_atr",
        "ema_two_closes",
        "daily_invalidation",
    )
    assert second.position.current_stop == D("9")


def test_tenth_completed_session_schedules_next_open_exit() -> None:
    position = replace(_position(), completed_sessions=9)

    result = evaluate_completed_close(
        position,
        _bar(date(2026, 1, 7)),
        ema20=D("10"),
        atr14=D("1"),
    )

    assert result.position.state is PositionState.EXIT_PENDING
    assert "time_stop" in result.triggers
    assert result.position.scheduled_exit_triggers == ("time_stop",)


def test_pending_exit_preserves_protection_and_merges_later_triggers() -> None:
    position = schedule_exit(_position(), ("daily_invalidation",))
    before = position.current_stop

    result = evaluate_completed_close(
        replace(position, completed_sessions=9),
        _bar(date(2026, 1, 7)),
        ema20=D("10"),
        atr14=D("1"),
    )

    assert result.position.current_stop == before
    assert result.position.scheduled_exit_triggers == ("daily_invalidation", "time_stop")


def test_close_evaluation_is_idempotent_and_closed_position_stays_closed() -> None:
    position = _position()
    bar = _bar(date(2026, 1, 6))
    once = evaluate_completed_close(position, bar, ema20=D("10"), atr14=D("1"))
    twice = evaluate_completed_close(once.position, bar, ema20=D("10"), atr14=D("1"))
    assert twice.position == once.position
    assert twice.triggers == ()

    closed = apply_exit_fill(
        position,
        _fill(event_id="stop-1", side="sell", price="9", session=date(2026, 1, 6)),
    )
    assert evaluate_completed_close(closed, bar, ema20=D("10"), atr14=D("1")).position == closed


def test_target_fill_requires_exact_banked_quantity_and_target_price() -> None:
    position = _position()
    with pytest.raises(LifecycleInvariantError):
        apply_target_fill(
            position,
            _fill(event_id="bad", side="sell", price="10.99", quantity=3),
        )
    with pytest.raises(LifecycleInvariantError):
        apply_target_fill(
            position,
            _fill(event_id="bad", side="sell", price="11", quantity=2),
        )


def test_deep_atr_trail_candidate_cannot_lower_or_break_the_stop() -> None:
    position = _position()
    runner = apply_target_fill(
        position,
        _fill(
            event_id="target-1",
            side="sell",
            price="11",
            quantity=position.banked_quantity,
            session=date(2026, 1, 7),
        ),
    )

    result = evaluate_completed_close(
        runner,
        _bar(date(2026, 1, 8), high="13"),
        ema20=D("10"),
        atr14=D("20"),
    )

    assert result.position.current_stop == runner.current_stop

"""Conservative exact-decimal daily-bar fill resolution."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal

from qat.domain.backtester.swing_fills import (
    AmbiguityPolicy,
    TradedDailyBar,
    ambiguity_for_session,
    resolve_entry_open,
    resolve_open_exit,
    resolve_protective_session,
)
from qat.domain.strategies.authoritative_swing.lifecycle import (
    ConfirmedFill,
    PositionState,
    apply_entry_fill,
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
from qat.domain.strategies.authoritative_swing.sizing import (
    ExactCostProfile,
    LiquidityProfile,
)


def D(value: str | int) -> Decimal:
    return Decimal(value)


COSTS = ExactCostProfile("fixture-v1", "fixture", D("0"), D("0"), "AUD", False, D("0"))
ZERO_IMPACT = LiquidityProfile("zero-v1", D("1"), D("0"), D("0"))
IMPACT = LiquidityProfile("impact-v1", D("1"), D("10"), D("20"))


def _setup() -> SetupDecision:
    candidate = PatternCandidate(
        Pattern.EMA_PULLBACK,
        "pattern-1",
        None,
        date(2026, 1, 5),
        D("10"),
        D("9"),
        D("0.5"),
    )
    pattern = PatternDecision(Pattern.EMA_PULLBACK, DecisionStatus.QUALIFIED, (), candidate)
    return SetupDecision(
        "phase2-swing-v1",
        "swing-evidence-v1",
        "decision-1",
        "BHP.AX",
        date(2026, 1, 5),
        DecisionStatus.QUALIFIED,
        (Pattern.EMA_PULLBACK,),
        (pattern,),
        D("10"),
        D("9"),
        5,
        5,
        5,
        ("bar-1",),
    )


def _pending():
    return pending_entry_from_setup(_setup())


def _position():
    return apply_entry_fill(
        _pending(),
        ConfirmedFill("entry-1", date(2026, 1, 6), "buy", 5, D("10"), "entry"),
    )


def _bar(
    *,
    session: date = date(2026, 1, 6),
    open_: str | None = "10",
    high: str = "10.5",
    low: str = "9.5",
    close: str = "10",
    volume: int = 100_000,
) -> TradedDailyBar:
    return TradedDailyBar(
        "BHP.AX",
        session,
        None if open_ is None else D(open_),
        D(high),
        D(low),
        D(close),
        volume,
    )


def test_valid_entry_adds_buy_impact_once_and_caps_at_limit() -> None:
    fills = resolve_entry_open(
        _pending(),
        _bar(open_="9.999", high="10.2", low="9.8"),
        COSTS,
        IMPACT,
    )

    assert len(fills) == 1
    assert fills[0].price == D("10")
    assert fills[0].quantity == 5
    assert fills[0].cost == D("0")


def test_broker_charge_is_separate_from_slippage_embedded_in_price() -> None:
    one_percent_cost = ExactCostProfile(
        "cost-v1", "one-percent", D("100"), D("0"), "AUD", False, D("0")
    )
    fills = resolve_entry_open(
        _pending(),
        _bar(open_="9.90", high="10", low="9.8"),
        one_percent_cost,
        IMPACT,
    )

    assert fills[0].price == D("9.90990")
    assert fills[0].cost == D("0.4954950")


def test_entry_cancels_for_gap_invalidation_missing_or_ineligible_open() -> None:
    assert not resolve_entry_open(_pending(), _bar(open_="10.01", high="10.2"), COSTS, IMPACT)
    assert not resolve_entry_open(
        _pending(), _bar(open_="9", high="9.2", low="8.8", close="9.1"), COSTS, IMPACT
    )
    assert not resolve_entry_open(_pending(), _bar(open_=None), COSTS, IMPACT)
    assert not resolve_entry_open(_pending(), _bar(volume=0), COSTS, IMPACT)


def test_auction_open_is_preserved_without_tick_rounding() -> None:
    fills = resolve_entry_open(
        _pending(),
        _bar(open_="9.997", high="10", low="9.9"),
        COSTS,
        ZERO_IMPACT,
    )
    assert fills[0].price == D("9.997")


def test_gap_stop_precedes_a_scheduled_open_exit_and_sells_once() -> None:
    position = schedule_exit(_position(), ("daily_invalidation",))
    fills = resolve_open_exit(
        position,
        _bar(session=date(2026, 1, 7), open_="8.8", high="9", low="8.5", close="8.7"),
        COSTS,
        IMPACT,
    )

    assert [(fill.reason, fill.quantity) for fill in fills] == [("protective_stop", 5)]
    assert fills[0].price == D("8.7824")


def test_scheduled_exit_uses_open_minus_sell_impact() -> None:
    position = schedule_exit(_position(), ("time_stop",))
    fills = resolve_open_exit(
        position,
        _bar(session=date(2026, 1, 7), open_="10", high="10.2", low="9.8"),
        COSTS,
        IMPACT,
    )
    assert fills[0].reason == "scheduled_open_exit"
    assert fills[0].price == D("9.980")


def test_stop_wins_a_bar_that_can_touch_stop_and_target() -> None:
    position = _position()
    fills = resolve_protective_session(
        position,
        _bar(high="11.2", low="8.9"),
        COSTS,
        ZERO_IMPACT,
    )

    assert [(fill.reason, fill.quantity) for fill in fills] == [("protective_stop", 5)]
    assert fills[0].ambiguous is True


def test_optimistic_order_banks_target_before_same_bar_stop() -> None:
    position = _position()
    fills = resolve_protective_session(
        position,
        _bar(high="11.2", low="8.9"),
        COSTS,
        ZERO_IMPACT,
        policy=AmbiguityPolicy.OPTIMISTIC,
    )
    assert [fill.reason for fill in fills] == ["banked_target", "runner_breakeven"]
    assert all(fill.ambiguous for fill in fills)


def test_target_then_breakeven_is_worst_feasible_when_initial_stop_is_safe() -> None:
    position = _position()
    fills = resolve_protective_session(
        position,
        _bar(high="11.2", low="9.8"),
        COSTS,
        ZERO_IMPACT,
    )

    assert [fill.reason for fill in fills] == ["banked_target", "runner_breakeven"]
    assert [fill.quantity for fill in fills] == [3, 2]
    assert all(fill.ambiguous for fill in fills)


def test_optimistic_order_leaves_runner_when_breakeven_order_is_uncertain() -> None:
    position = _position()
    fills = resolve_protective_session(
        position,
        _bar(high="11.2", low="9.8"),
        COSTS,
        ZERO_IMPACT,
        policy=AmbiguityPolicy.OPTIMISTIC,
    )
    assert [fill.reason for fill in fills] == ["banked_target"]
    assert fills[0].ambiguous is True


def test_gap_above_target_gets_better_price_after_sell_impact() -> None:
    position = _position()
    fills = resolve_protective_session(
        position,
        _bar(open_="11.5", high="11.6", low="11.1", close="11.3"),
        COSTS,
        IMPACT,
    )
    assert fills[0].reason == "banked_target"
    assert fills[0].price == D("11.4770")


def test_runner_stop_closes_only_the_remaining_quantity() -> None:
    position = _position()
    runner = replace(position, state=PositionState.RUNNER, current_stop=D("10"))
    fills = resolve_protective_session(
        runner,
        _bar(high="10.5", low="9.9"),
        COSTS,
        ZERO_IMPACT,
    )
    assert [(fill.reason, fill.quantity) for fill in fills] == [("protective_stop", 2)]


def test_open_gap_through_stop_proves_stop_first_under_both_policies() -> None:
    position = _position()
    bar = _bar(open_="8.8", high="11.2", low="8.5", close="10")

    conservative = resolve_protective_session(position, bar, COSTS, ZERO_IMPACT)
    optimistic = resolve_protective_session(
        position, bar, COSTS, ZERO_IMPACT, policy=AmbiguityPolicy.OPTIMISTIC
    )

    assert [fill.reason for fill in conservative] == ["protective_stop"]
    assert conservative == optimistic
    assert conservative[0].ambiguous is False


def test_open_gap_above_target_proves_target_then_breakeven() -> None:
    position = _position()
    fills = resolve_protective_session(
        position,
        _bar(open_="11.2", high="11.4", low="9.8", close="10.5"),
        COSTS,
        ZERO_IMPACT,
    )
    assert [fill.reason for fill in fills] == ["banked_target", "runner_breakeven"]
    assert not any(fill.ambiguous for fill in fills)


def test_open_target_gap_still_proves_order_when_later_low_crosses_original_stop() -> None:
    position = _position()
    fills = resolve_protective_session(
        position,
        _bar(open_="11.2", high="11.4", low="8.8", close="10.5"),
        COSTS,
        ZERO_IMPACT,
    )
    assert [fill.reason for fill in fills] == ["banked_target", "runner_breakeven"]
    assert not any(fill.ambiguous for fill in fills)


def test_ambiguity_evidence_records_baseline_and_optimistic_sequences() -> None:
    position = _position()
    evidence = ambiguity_for_session(
        position,
        _bar(high="11.2", low="8.9"),
        COSTS,
        ZERO_IMPACT,
    )
    assert evidence is not None
    assert evidence.baseline_sequence == ("protective_stop",)
    assert evidence.optimistic_sequence == ("banked_target", "runner_breakeven")

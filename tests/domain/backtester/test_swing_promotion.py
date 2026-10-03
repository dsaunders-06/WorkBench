"""Pure structural-risk and evidence-tier promotion verdict contracts."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal

import pytest

from qat.domain.backtester.swing_method_audit import FeasibilityStatus, FrequencyPlan, MethodStatus
from qat.domain.backtester.swing_promotion import (
    GateResult,
    PatternEdgeInputs,
    PatternEdgeResult,
    Phase4RiskPolicy,
    PositionImpact,
    PromotionCase,
    PromotionStatus,
    SignalEdgeTrade,
    StructuralStatus,
    TerminalScenarioTrade,
    all_exposed_trade_session_pairs,
    evaluate_pattern_edge_gates,
    evaluate_promotion,
    evaluate_structural_risk,
    simulate_terminal_tail,
    simultaneous_two_issuer_zero,
)
from qat.domain.backtester.swing_reference import IncidenceCalibration
from qat.domain.backtester.swing_results import ReplayEquityPoint


def _sessions() -> tuple[date, ...]:
    start = date(2020, 1, 1)
    return tuple(start + timedelta(days=day) for day in range(7))


def _equity(sessions: tuple[date, ...]) -> tuple[ReplayEquityPoint, ...]:
    return tuple(
        ReplayEquityPoint(day, Decimal("10000"), Decimal("9000"), Decimal("1000"), Decimal(0))
        for day in sessions
    )


def _position(sessions: tuple[date, ...], mark: Decimal = Decimal("1000")) -> PositionImpact:
    return PositionImpact(
        trade_id="funded-1",
        issuer_id="issuer-1",
        entry_session=sessions[0],
        exit_session=sessions[-1],
        marks={day: mark for day in sessions[1:-1]},
        exit_proceeds=mark,
        dividends={},
        sector="materials",
        initial_notional=mark,
        stop_distance=Decimal("0.1"),
        cost_to_risk=Decimal("0.05"),
    )


def _policy() -> Phase4RiskPolicy:
    return Phase4RiskPolicy(
        ordinary_drawdown_budget=Decimal("0.05"),
        maximum_drawdown=Decimal("0.2"),
        maximum_single_notional=Decimal("0.35"),
        maximum_aggregate_notional=Decimal("0.6"),
        maximum_sector_notional=Decimal("0.5"),
        minimum_stop_distance=Decimal("0.02"),
        maximum_cost_to_risk=Decimal("0.2"),
    )


def test_phase4_policy_cannot_relax_the_20_percent_drawdown_gate() -> None:
    with pytest.raises(ValueError, match="20%"):
        replace(_policy(), maximum_drawdown=Decimal("0.25"))


def test_zero_price_onset_covers_each_exposed_official_session() -> None:
    sessions = _sessions()
    position = _position(sessions)
    pairs = all_exposed_trade_session_pairs(sessions, (position,))

    assert len(pairs) == 5
    assert (position.trade_id, sessions[-2]) in pairs
    assert (position.trade_id, sessions[-1]) not in pairs


def test_sparse_zero_sweep_matches_independent_full_path_reference() -> None:
    sessions = _sessions()
    position = _position(sessions)
    result = evaluate_structural_risk(sessions, _equity(sessions), (position,), _policy())

    assert result.placements_tested == 5
    assert result.status is StructuralStatus.PASS
    assert result.max_drawdown == Decimal("0.1")
    for placement in result.placements:
        stressed = []
        for point in _equity(sessions):
            if point.session < placement.onset:
                stressed.append(point.equity)
            elif point.session < position.exit_session:
                stressed.append(point.equity - position.marks[point.session])
            else:
                stressed.append(point.equity - position.exit_proceeds)
        peak = stressed[0]
        reference = Decimal(0)
        for value in stressed:
            peak = max(peak, value)
            reference = max(reference, (peak - value) / peak)
        assert placement.max_drawdown == reference


def test_structurally_infeasible_preflight_gives_no_duration_advice() -> None:
    sessions = _sessions()
    oversized = _position(sessions, Decimal("3000"))
    result = evaluate_structural_risk(sessions, _equity(sessions), (oversized,), _policy())
    assert result.status is StructuralStatus.PORTFOLIO_RISK_STRUCTURALLY_INFEASIBLE
    assert result.recommended_holdout_months is None


def test_entry_session_funded_positions_count_toward_aggregate_and_sector_caps() -> None:
    sessions = _sessions()
    first = replace(_position(sessions), exit_session=sessions[1], marks={})
    second = replace(first, trade_id="funded-2", issuer_id="issuer-2")
    policy = replace(
        _policy(),
        maximum_aggregate_notional=Decimal("0.15"),
        maximum_sector_notional=Decimal("0.15"),
    )
    result = evaluate_structural_risk(sessions, _equity(sessions), (first, second), policy)
    assert result.status is StructuralStatus.PORTFOLIO_RISK_STRUCTURALLY_INFEASIBLE
    assert f"{sessions[0]}:aggregate_notional" in result.policy_violations
    assert f"{sessions[0]}:sector_notional" in result.policy_violations


def _frequency(status: FeasibilityStatus) -> FrequencyPlan:
    return FrequencyPlan(
        status,
        72,
        36,
        36,
        "ema",
        "rolling_36_development",
        {"baseline": Decimal("0.9"), "stressed": Decimal("0.8")},
        {},
        {},
        {},
        25,
        35,
        status is FeasibilityStatus.DATASET_INSUFFICIENT,
        True,
    )


def test_engineering_never_passes_and_preserves_feasibility_reason() -> None:
    case = PromotionCase(
        evidence_tier="engineering_synthetic",
        feasibility=_frequency(FeasibilityStatus.DATASET_INSUFFICIENT),
    )
    result = evaluate_promotion(case)
    assert result.status is PromotionStatus.PORTFOLIO_RISK_DESIGN_PENDING
    assert result.feasibility_reason is FeasibilityStatus.DATASET_INSUFFICIENT
    assert result.forward_acquisition_could_help


def test_feasibility_mapping_never_treats_feasible_as_promotion_pass() -> None:
    case = PromotionCase(
        evidence_tier="promotion_point_in_time", feasibility=_frequency(FeasibilityStatus.FEASIBLE)
    )
    assert evaluate_promotion(case).status is PromotionStatus.INSUFFICIENT_EVIDENCE
    no_extension = replace(
        case, feasibility=_frequency(FeasibilityStatus.FREQUENCY_INADEQUATE_WITHIN_MAX_HORIZON)
    )
    result = evaluate_promotion(no_extension)
    assert result.status is PromotionStatus.INSUFFICIENT_EVIDENCE
    assert result.recommended_holdout_months is None


def test_method_and_structural_failures_precede_duration() -> None:
    case = PromotionCase(
        evidence_tier="promotion_point_in_time",
        feasibility=_frequency(FeasibilityStatus.DATASET_INSUFFICIENT),
        method_status=MethodStatus.METHOD_INADEQUATE,
    )
    assert evaluate_promotion(case).status is PromotionStatus.METHOD_INADEQUATE
    sessions = _sessions()
    structural = evaluate_structural_risk(
        sessions, _equity(sessions), (_position(sessions, Decimal("3000")),), _policy()
    )
    result = evaluate_promotion(replace(case, method_status=None, structural=structural))
    assert result.status is PromotionStatus.PORTFOLIO_RISK_STRUCTURALLY_INFEASIBLE
    assert result.recommended_holdout_months is None


def test_insufficient_incidence_precedes_method_and_duration() -> None:
    incidence = IncidenceCalibration(
        PromotionStatus.INCIDENCE_DATA_INSUFFICIENT,
        20,
        0,
        {},
        (),
        None,
        None,
        None,
        None,
        None,
    )
    case = PromotionCase(
        evidence_tier="promotion_point_in_time",
        incidence=incidence,
        method_status=MethodStatus.METHOD_INADEQUATE,
        feasibility=_frequency(FeasibilityStatus.DATASET_INSUFFICIENT),
    )
    verdict = evaluate_promotion(case)
    assert verdict.status is PromotionStatus.INCIDENCE_DATA_INSUFFICIENT
    assert verdict.recommended_holdout_months is None


def test_phase2_evaluator_cannot_return_pass_even_with_claimed_permit() -> None:
    case = PromotionCase(
        evidence_tier="promotion_point_in_time",
        feasibility=_frequency(FeasibilityStatus.FEASIBLE),
        all_edge_gates_pass=True,
        portfolio_safety_pass=True,
        conservative_terminal_gate_pass=True,
        phase4_policy_frozen=True,
        permit_satisfied=True,
    )
    assert evaluate_promotion(case).status is PromotionStatus.INSUFFICIENT_EVIDENCE


def test_concentration_gate_uses_symbol_year_and_top_five_percent_leave_outs() -> None:
    entries = (
        SignalEdgeTrade("a", "AAA.AX", date(2020, 1, 2), Decimal("3"), Decimal("300"), True),
        SignalEdgeTrade("b", "BBB.AX", date(2020, 2, 3), Decimal("-0.5"), Decimal("-50"), True),
        SignalEdgeTrade("c", "CCC.AX", date(2020, 3, 2), Decimal("-0.5"), Decimal("-50"), True),
    )
    inputs = PatternEdgeInputs(
        pattern="ema_pullback",
        trades=entries,
        n_required=100,
        g_required=36,
        wcr_lower_bound=Decimal("0.1"),
        romano_wolf_adjusted_p=Decimal("0.01"),
        doubled_cost_expectancy=Decimal("0.2"),
        method_status=MethodStatus.METHOD_ADEQUATE,
        feasibility_status=FeasibilityStatus.FEASIBLE,
        eligible_holdout_months=36,
        phase4_policy_frozen=True,
        protocol_frozen=True,
        permit_satisfied=False,
    )
    result = evaluate_pattern_edge_gates(inputs)
    assert len(result.gates) == 7
    assert not result.gates[5].passed
    assert not result.gates[6].passed


def test_failed_constituent_pattern_overrides_claimed_combined_edge() -> None:
    failed = PatternEdgeResult(
        "ema_pullback", (GateResult("expectancy", False, "negative mean R_order"),), False
    )
    case = PromotionCase(
        evidence_tier="promotion_point_in_time",
        feasibility=_frequency(FeasibilityStatus.FEASIBLE),
        all_edge_gates_pass=True,
        pattern_edges=(failed,),
    )
    assert evaluate_promotion(case).status is PromotionStatus.FAIL


def test_conservative_terminal_failure_with_recovery_pass_is_non_promotable() -> None:
    case = PromotionCase(
        evidence_tier="promotion_point_in_time",
        feasibility=_frequency(FeasibilityStatus.FEASIBLE),
        all_edge_gates_pass=True,
        portfolio_safety_pass=True,
        conservative_terminal_gate_pass=False,
        recovery_sensitivity_pass=True,
        phase4_policy_frozen=True,
        permit_satisfied=True,
    )
    assert evaluate_promotion(case).status is PromotionStatus.TERMINAL_OUTCOME_SENSITIVE


def test_calibrated_terminal_simulation_replaces_r_and_cash_at_onset() -> None:
    sessions = _sessions()
    trade = TerminalScenarioTrade(
        position=_position(sessions),
        ordinary_r_order=Decimal("1"),
        zero_r_order=Decimal("-9"),
        bucket_probability=Decimal(1),
    )
    first = simulate_terminal_tail(sessions, _equity(sessions), (trade,), simulations=100, seed=31)
    second = simulate_terminal_tail(sessions, _equity(sessions), (trade,), simulations=100, seed=31)

    assert first == second
    assert first.analytical_expected_mean_r == Decimal("-9")
    assert first.simulated_expected_mean_r == Decimal("-9")
    assert first.analytical_parity_pass
    assert first.analytical_parity_gap == Decimal(0)
    assert first.fifth_percentile_mean_r == Decimal("-9")
    assert first.drawdown_95 == Decimal("0.1")
    assert first.signal_es1 == Decimal("-9")


def test_probabilistic_tail_mean_and_drawdown_gate_separately() -> None:
    sessions = _sessions()
    tail = simulate_terminal_tail(
        sessions,
        _equity(sessions),
        (TerminalScenarioTrade(_position(sessions), Decimal("1"), Decimal("-9"), Decimal(1)),),
        simulations=20,
        seed=5,
    )
    case = PromotionCase(
        evidence_tier="promotion_point_in_time",
        feasibility=_frequency(FeasibilityStatus.FEASIBLE),
        all_edge_gates_pass=True,
        portfolio_safety_pass=True,
        terminal_tail=tail,
    )
    assert evaluate_promotion(case).status is PromotionStatus.FAIL
    drawdown_only = replace(
        tail,
        fifth_percentile_mean_r=Decimal("0.1"),
        drawdown_95=Decimal("0.21"),
    )
    assert (
        evaluate_promotion(replace(case, terminal_tail=drawdown_only)).status
        is PromotionStatus.EDGE_PASS_PORTFOLIO_RISK_BLOCKED
    )


def test_simultaneous_two_issuer_zero_is_a_separate_sensitivity() -> None:
    sessions = _sessions()
    first = _position(sessions)
    second = replace(first, trade_id="funded-2", issuer_id="issuer-2")
    result = simultaneous_two_issuer_zero(sessions, _equity(sessions), (first, second))
    assert result.worst_drawdown == Decimal("0.2")
    assert result.placements_tested == 5

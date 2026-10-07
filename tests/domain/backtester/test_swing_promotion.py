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
from qat.domain.backtester.swing_statistics import InferenceCandidate


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

    assert len(pairs) == 6
    assert (position.trade_id, sessions[-2]) in pairs
    assert (position.trade_id, sessions[-1]) in pairs


def test_sparse_zero_sweep_matches_independent_full_path_reference() -> None:
    sessions = _sessions()
    position = _position(sessions)
    result = evaluate_structural_risk(sessions, _equity(sessions), (position,), _policy())

    assert result.placements_tested == 6
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


def test_expected_bull_flag_insufficiency_does_not_block_feasible_pattern() -> None:
    """All three patterns remain reported, but an expected shortfall is per-pattern."""
    from types import SimpleNamespace

    plan = replace(
        _frequency(FeasibilityStatus.FEASIBLE),
        pattern_plans={
            "ema_pullback": SimpleNamespace(status=FeasibilityStatus.FEASIBLE),
            "bull_flag": SimpleNamespace(
                status=FeasibilityStatus.FREQUENCY_INADEQUATE_WITHIN_MAX_HORIZON
            ),
        },
    )
    case = PromotionCase(
        evidence_tier="promotion_point_in_time",
        feasibility=plan,
        pattern_edges=(
            PatternEdgeResult("ema_pullback", (), True),
            PatternEdgeResult("bull_flag", (), False),
        ),
    )
    verdict = evaluate_promotion(case)
    assert verdict.status is PromotionStatus.INSUFFICIENT_EVIDENCE
    assert verdict.expected_insufficient_evidence_patterns == ("bull_flag",)
    assert next(gate for gate in verdict.gates if gate.name == "edge").passed is True


def test_replay_mapping_cannot_omit_expected_insufficient_pattern() -> None:
    """Every tested family member remains in the replay, even if frequency is short."""
    from types import SimpleNamespace

    from qat.domain.backtester.swing_promotion import promotion_case_from_replays

    plan = replace(
        _frequency(FeasibilityStatus.FEASIBLE),
        pattern_plans={
            "ema_pullback": SimpleNamespace(status=FeasibilityStatus.FEASIBLE),
            "bull_flag": SimpleNamespace(
                status=FeasibilityStatus.FREQUENCY_INADEQUATE_WITHIN_MAX_HORIZON
            ),
        },
    )
    case = PromotionCase(evidence_tier="promotion_point_in_time", feasibility=plan)

    with pytest.raises(ValueError, match="feasibility pattern identities"):
        promotion_case_from_replays(case, {"ema_pullback": object()})  # type: ignore[arg-type]


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
        family_adjusted_p=Decimal("0.01"),
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
    holm = evaluate_pattern_edge_gates(replace(inputs, family_method="holm"))
    assert holm.gates[2].passed
    assert "Holm" in holm.gates[2].evidence


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
        all_edge_gates_pass=False,
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
    assert result.placements_tested == 6


def test_terminal_tail_exit_onset_matches_deterministic_sweep() -> None:
    sessions = _sessions()[:2]
    position = replace(
        _position(sessions, Decimal("100")),
        exit_proceeds=Decimal("1500"),
    )
    equity = _equity(sessions)

    sweep = evaluate_structural_risk(sessions, equity, (position,), _policy())
    tail = simulate_terminal_tail(
        sessions,
        equity,
        (TerminalScenarioTrade(position, Decimal("1"), Decimal("-9"), Decimal(1)),),
        simulations=8,
        seed=31,
    )

    assert all_exposed_trade_session_pairs(sessions, (position,)) == (
        (position.trade_id, position.exit_session),
    )
    assert sweep.placements_tested == 1
    assert sweep.placements[0].max_drawdown == Decimal("0.15")
    assert tail.drawdown_95 == sweep.max_drawdown
    assert tail.cash_es1 == Decimal("-0.15")


def test_two_issuer_exit_onset_removes_both_scheduled_proceeds() -> None:
    sessions = _sessions()[:2]
    first = replace(_position(sessions, Decimal("100")), exit_proceeds=Decimal("1500"))
    second = replace(first, trade_id="funded-2", issuer_id="issuer-2")
    equity = _equity(sessions)

    sweep = evaluate_structural_risk(sessions, equity, (first, second), _policy())
    pair = simultaneous_two_issuer_zero(sessions, equity, (first, second))

    assert sweep.placements_tested == 2
    assert all(row.onset == sessions[1] for row in sweep.placements)
    assert all(row.max_drawdown == Decimal("0.15") for row in sweep.placements)
    assert pair.placements_tested == 1
    assert pair.worst_pair == (first.trade_id, second.trade_id, sessions[1])
    assert pair.worst_drawdown == Decimal("0.3")


def test_terminal_zero_only_edge_failure_is_derived_from_replay_results() -> None:
    from qat.domain.backtester.swing_promotion import promotion_case_from_replays
    from qat.domain.backtester.swing_results import (
        LifecycleActionSeries,
        PostFillResistanceDiagnostic,
        ReplayArm,
        RunStatus,
        SwingReplayResult,
        SwingTrade,
    )
    from qat.domain.strategies.authoritative_swing.model import Pattern

    months = tuple(f"{2010 + month // 12}-{1 + month % 12:02}" for month in range(120))
    trades = []
    for ordinal in range(240):
        month = ordinal // 2
        value = Decimal("0.4") + Decimal(ordinal % 3) / Decimal(10)
        terminal = ordinal in (0, 40, 80)
        pnl = Decimal("-10000") if terminal else value * Decimal(100)
        trades.append(
            SwingTrade(
                trade_id=str(ordinal),
                symbol=f"S{ordinal % 10}.AX",
                patterns=(Pattern.EMA_PULLBACK,),
                entry_session=date(2010 + month // 12, 1 + month % 12, 1),
                exit_session=date(2020, 1, 1),
                quantity=1000,
                submitted_limit=Decimal(10),
                entry_price=Decimal(10),
                exit_price=Decimal(0) if terminal else Decimal(10) + value / Decimal(10),
                initial_stop=Decimal("9.9"),
                gross_pnl=pnl,
                eligible_dividends=Decimal(0),
                costs=Decimal(0),
                net_pnl=pnl,
                order_initial_risk_dollars=Decimal(100),
                fill_initial_risk_dollars=Decimal(100),
                order_r_multiple=pnl / Decimal(100),
                fill_r_multiple=pnl / Decimal(100),
                mfe_order_r=value,
                mae_order_r=Decimal(0),
                mfe_fill_r=value,
                mae_fill_r=Decimal(0),
                exit_reason="terminal_zero" if terminal else "target",
                observed_triggers=(),
                post_fill_resistance=PostFillResistanceDiagnostic.CLEAR,
                analysis_regime="fixture",
                edge_sample_eligible=True,
                edge_exclusion_reason=None,
            )
        )

    def replay(rows):
        return SwingReplayResult(
            RunStatus.VALID,
            ReplayArm.EMA_PULLBACK,
            (),
            LifecycleActionSeries(),
            (),
            tuple(rows),
            tuple(rows),
            (),
            (),
            (),
        )

    conservative = replay(trades)
    recovered = replay(
        tuple(
            (
                replace(
                    trade,
                    exit_price=Decimal("10.05"),
                    gross_pnl=Decimal(50),
                    net_pnl=Decimal(50),
                    order_r_multiple=Decimal("0.5"),
                    fill_r_multiple=Decimal("0.5"),
                    exit_reason="delisting_outcome",
                )
                if trade.exit_reason == "terminal_zero"
                else trade
            )
            for trade in trades
        )
    )
    context = PatternEdgeInputs(
        "ema_pullback",
        (),
        100,
        36,
        None,
        None,
        None,
        MethodStatus.METHOD_ADEQUATE,
        FeasibilityStatus.FEASIBLE,
        120,
        True,
        True,
        True,
    )
    case = promotion_case_from_replays(
        PromotionCase(
            evidence_tier="promotion_point_in_time",
            feasibility=_frequency(FeasibilityStatus.FEASIBLE),
        ),
        {"ema_pullback": conservative},
        doubled_cost_replays={"ema_pullback": conservative},
        recovery_replays={"ema_pullback": recovered},
        recovery_doubled_cost_replays={"ema_pullback": recovered},
        contexts={"ema_pullback": context},
        entry_months=months,
        draws=999,
    )
    assert case.all_edge_gates_pass is False
    assert case.conservative_terminal_gate_pass is False
    assert case.recovery_sensitivity_pass is True
    assert evaluate_promotion(case).status is PromotionStatus.TERMINAL_OUTCOME_SENSITIVE
    grouped = promotion_case_from_replays(
        PromotionCase(evidence_tier="engineering"),
        {"ema_pullback": conservative},
        contexts={"ema_pullback": context},
        entry_months=months,
        draws=99,
        candidate=InferenceCandidate("aligned_block", 6),
    )
    assert grouped.pattern_edges[0].gates[0].passed is False  # 20 aligned clusters < G_required=36
    assert (
        evaluate_promotion(replace(case, evidence_tier="engineering")).status
        is PromotionStatus.PORTFOLIO_RISK_DESIGN_PENDING
    )
    no_recovery = promotion_case_from_replays(
        PromotionCase(evidence_tier="engineering"),
        {"ema_pullback": conservative},
        contexts={"ema_pullback": context},
        entry_months=months,
        draws=99,
    )
    assert not no_recovery.recovery_sensitivity_pass
    bad_doubled = replay(
        tuple(
            (
                replace(trade, net_pnl=Decimal(-100), order_r_multiple=Decimal(-1))
                if trade.exit_reason != "terminal_zero"
                else trade
            )
            for trade in trades
        )
    )
    with pytest.raises(ValueError, match="nonterminal outcome"):
        promotion_case_from_replays(
            PromotionCase(evidence_tier="promotion_point_in_time"),
            {"ema_pullback": conservative},
            doubled_cost_replays={"ema_pullback": bad_doubled},
            recovery_replays={"ema_pullback": recovered},
            recovery_doubled_cost_replays={"ema_pullback": recovered},
            contexts={"ema_pullback": context},
            entry_months=months,
            draws=99,
        )
    with pytest.raises(ValueError, match="identities"):
        promotion_case_from_replays(
            PromotionCase(evidence_tier="engineering"),
            {"ema_pullback": conservative},
            doubled_cost_replays={"ema_pullback": replay(trades[:-1])},
            contexts={"ema_pullback": context},
            entry_months=months,
            draws=99,
        )
    with pytest.raises(ValueError, match="identities"):
        promotion_case_from_replays(
            PromotionCase(evidence_tier="engineering"),
            {"ema_pullback": conservative},
            recovery_replays={"ema_pullback": replay(trades[:-1])},
            contexts={"ema_pullback": context},
            entry_months=months,
            draws=99,
        )


def test_terminal_sensitivity_cannot_hide_unrelated_portfolio_failure() -> None:
    case = PromotionCase(
        evidence_tier="promotion_point_in_time",
        feasibility=_frequency(FeasibilityStatus.FEASIBLE),
        all_edge_gates_pass=False,
        conservative_terminal_gate_pass=False,
        recovery_sensitivity_pass=True,
        portfolio_safety_pass=False,
    )
    assert evaluate_promotion(case).status is PromotionStatus.FAIL


def test_exit_session_onset_removes_proceeds_and_can_bind_worst_drawdown() -> None:
    sessions = _sessions()
    position = replace(_position(sessions, Decimal("100")), exit_proceeds=Decimal("1500"))
    result = evaluate_structural_risk(sessions, _equity(sessions), (position,), _policy())
    placement = next(row for row in result.placements if row.onset == position.exit_session)
    assert placement.max_drawdown == Decimal("0.15")
    assert result.max_drawdown == Decimal("0.15")

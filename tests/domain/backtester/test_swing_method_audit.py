"""Synthetic method-size, power, and duration contract tests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import pytest

from qat.domain.backtester.swing_method_audit import (
    FeasibilityStatus,
    MethodAuditProtocol,
    MethodStatus,
    PowerRequirement,
    PowerScenario,
    ScenarioSizeAudit,
    SyntheticScenario,
    _predictive_lower,
    audit_method_size,
    audit_power,
    eligible_month_count_vector,
    plan_holdout_duration,
    run_synthetic_pilot,
)
from qat.domain.strategies.authoritative_swing.model import Pattern


def test_partial_null_configurations_are_mandatory() -> None:
    protocol = MethodAuditProtocol(mandatory_scenarios=("complete", "partial"))
    assert set(protocol.null_configurations) == {"000", "d00", "0d0", "00d", "dd0", "d0d", "0dd"}
    assert protocol.inner_draws == 9_999
    assert protocol.initial_outer_runs == 20_000
    assert protocol.maximum_outer_runs == 100_000


def test_every_mandatory_scenario_must_pass_individually() -> None:
    protocol = MethodAuditProtocol(mandatory_scenarios=("complete", "partial"))
    outcomes = (
        ScenarioSizeAudit("complete", "confidence", 20_000, 200),
        ScenarioSizeAudit("partial", "family", 20_000, 1_500),
    )

    result = audit_method_size(protocol, outcomes)

    assert result.status is MethodStatus.METHOD_INADEQUATE
    assert result.worst_scenario == "partial"


def test_near_cap_extends_and_final_upper_limit_decides() -> None:
    protocol = MethodAuditProtocol(mandatory_scenarios=("near",))
    initial = ScenarioSizeAudit("near", "confidence", 20_000, 600)
    pending = audit_method_size(protocol, (initial,))
    assert pending.requested_outer_runs == 100_000
    final = audit_method_size(
        protocol,
        (ScenarioSizeAudit("near", "confidence", 100_000, 3_200),),
    )
    assert final.status is MethodStatus.METHOD_INADEQUATE
    assert final.worst_scenario == "near"


def test_aggregate_only_size_summary_cannot_claim_accepted_method() -> None:
    protocol = MethodAuditProtocol(mandatory_scenarios=("complete",))
    result = audit_method_size(
        protocol, (ScenarioSizeAudit("complete", "confidence", 20_000, 100),)
    )
    assert result.status is MethodStatus.METHOD_AUDIT_PENDING


def test_declared_size_with_attempt_transcript_can_be_accepted() -> None:
    protocol = MethodAuditProtocol(
        mandatory_scenarios=("complete",),
        declaration_sha256="a" * 64,
        scenario_matrix_sha256="b" * 64,
        pilot_sha256="c" * 64,
    )
    result = audit_method_size(
        protocol,
        (ScenarioSizeAudit("complete", "confidence", 20_000, 100, attempts_sha256="d" * 64),),
    )
    assert result.status is MethodStatus.METHOD_ADEQUATE


def test_missing_mandatory_power_cell_refuses_requirement() -> None:
    with pytest.raises(ValueError, match="mandatory"):
        audit_power(
            (PowerScenario("block-3", "ema", 100, 36, Decimal("0.2"), 1000, 900),),
            mandatory_scenarios=("block-3", "block-6"),
            delta_mme=Decimal("0.2"),
        )


def test_power_uses_maximum_mandatory_requirement_and_declared_effect() -> None:
    trials = (
        PowerScenario("block-3", "ema", 100, 36, Decimal("0.2"), 1_000, 830),
        PowerScenario("block-6", "ema", 110, 40, Decimal("0.2"), 1_000, 815),
        PowerScenario("block-12", "ema", 120, 45, Decimal("0.2"), 1_000, 820),
    )
    result = audit_power(
        trials, mandatory_scenarios=("block-3", "block-6", "block-12"), delta_mme=Decimal("0.2")
    )
    assert result["ema"].n_required == 120
    assert result["ema"].g_required == 45
    assert result["ema"].minimum_detectable_effect == Decimal("0.2")


def _counts(per_month: int, months: int) -> dict[str, tuple[int, ...]]:
    return {name: (per_month,) * months for name in ("ema", "flag", "bottom")}


def _requirements(n: int) -> dict[str, PowerRequirement]:
    return {
        name: PowerRequirement(name, n, 36, Decimal("0.2"), Decimal("0.8"))
        for name in ("ema", "flag", "bottom")
    }


def test_required_duration_precedes_available_data_check() -> None:
    result = plan_holdout_duration(
        development=_counts(1, 60),
        validation=_counts(1, 24),
        requirements=_requirements(111),
        available_months=36,
        simulations=100,
        seed=17,
    )
    assert result.required_months == 111
    assert result.status is FeasibilityStatus.DATASET_INSUFFICIENT
    assert result.forward_acquisition_could_help
    assert all(
        plan.status is FeasibilityStatus.DATASET_INSUFFICIENT
        and plan.required_months == 111
        and plan.shortfall_months == 75
        for plan in result.pattern_plans.values()
    )


def test_variable_months_use_holdout_predictive_lower_rate() -> None:
    counts = (0, 4) * 42
    assert _predictive_lower(counts) > Decimal("1.5")
    result = plan_holdout_duration(
        development={name: counts[:60] for name in ("ema", "flag", "bottom")},
        validation={name: counts[60:] for name in ("ema", "flag", "bottom")},
        requirements=_requirements(100),
        available_months=120,
        simulations=20,
        seed=17,
    )
    assert all(rate > Decimal("1.5") for rate in result.stress_rates.values())
    assert result.status is FeasibilityStatus.FEASIBLE


def test_no_duration_through_120_is_frequency_inadequate() -> None:
    result = plan_holdout_duration(
        development=_counts(0, 60),
        validation=_counts(0, 24),
        requirements=_requirements(100),
        available_months=120,
        simulations=100,
        seed=17,
    )
    assert result.status is FeasibilityStatus.FREQUENCY_INADEQUATE_WITHIN_MAX_HORIZON
    assert result.required_months is None
    assert not result.forward_acquisition_could_help


def test_bull_flag_shortfall_cannot_be_hidden_by_abundant_other_patterns() -> None:
    development = {
        "ema_pullback": (20,) * 60,
        "bull_flag": (0, 1, 0, 0) * 15,
        "double_bottom": (15,) * 60,
    }
    validation = {
        "ema_pullback": (20,) * 24,
        "bull_flag": (0, 1, 0, 0) * 6,
        "double_bottom": (15,) * 24,
    }
    requirements = {
        name: PowerRequirement(name, 100, 6, Decimal("0.2"), Decimal("0.8")) for name in development
    }

    result = plan_holdout_duration(
        development=development,
        validation=validation,
        requirements=requirements,
        available_months=120,
        simulations=50,
        seed=17,
    )

    assert result.status is FeasibilityStatus.FEASIBLE
    assert result.pattern_plans["ema_pullback"].status is FeasibilityStatus.FEASIBLE
    assert result.pattern_plans["double_bottom"].status is FeasibilityStatus.FEASIBLE
    assert (
        result.pattern_plans["bull_flag"].status
        is FeasibilityStatus.FREQUENCY_INADEQUATE_WITHIN_MAX_HORIZON
    )
    assert result.required_months == 36
    assert result.shortfall_months == 0
    assert result.binding_pattern in {"ema_pullback", "double_bottom"}


def test_nonpositive_development_validation_expectancy_refuses_holdout_plan() -> None:
    with pytest.raises(ValueError, match="expectancy"):
        plan_holdout_duration(
            development=_counts(2, 60),
            validation=_counts(2, 24),
            requirements=_requirements(100),
            available_months=120,
            development_validation_expectancy={
                "ema": Decimal(0),
                "flag": Decimal("0.2"),
                "bottom": Decimal("0.1"),
            },
            simulations=10,
        )


@dataclass(frozen=True)
class _Entry:
    entry_session: date
    patterns: tuple[Pattern, ...]
    edge_sample_eligible: bool


@dataclass(frozen=True)
class _Window:
    signal_months: tuple[str, ...]
    signal_sessions: tuple[date, ...]


def test_complete_month_vector_keeps_real_zero_and_excludes_tail_and_overlap() -> None:
    window = _Window(("2020-01", "2020-02"), (date(2020, 1, 2), date(2020, 2, 3)))
    entries = (
        _Entry(date(2020, 1, 2), (Pattern.EMA_PULLBACK,), True),
        _Entry(date(2020, 1, 2), (Pattern.EMA_PULLBACK,), False),
        _Entry(date(2020, 3, 2), (Pattern.EMA_PULLBACK,), True),
    )
    assert eligible_month_count_vector(window, entries, Pattern.EMA_PULLBACK) == (1, 0)


def test_synthetic_pilot_replays_every_attempt_deterministically() -> None:
    scenario = SyntheticScenario(
        scenario_id="gaussian-block3-complete-null",
        family="gaussian",
        months=12,
        observations_per_month=2,
        block_months=3,
        null_configuration="000",
        delta_mme=Decimal("0.2"),
    )
    first = run_synthetic_pilot(scenario, outer_runs=4, inner_draws=31, seed=123, diagnostic=True)
    second = run_synthetic_pilot(scenario, outer_runs=4, inner_draws=31, seed=123, diagnostic=True)

    assert first == second
    assert len(first.attempts) == 4
    assert all(len(attempt.confidence_rejections) == 3 for attempt in first.attempts)
    assert len(first.attempts_sha256) == 64
    assert not first.promotion_eligible
    with pytest.raises(ValueError, match="frozen"):
        run_synthetic_pilot(scenario, outer_runs=4, inner_draws=31, seed=123)


def test_poisson_like_counts_no_longer_bind_on_single_month_variance() -> None:
    import numpy as np

    counts = tuple(int(value) for value in np.random.default_rng(5).poisson(2, 84))
    result = plan_holdout_duration(
        development={name: counts[:60] for name in ("ema", "flag", "bottom")},
        validation={name: counts[60:] for name in ("ema", "flag", "bottom")},
        requirements=_requirements(100),
        available_months=120,
        simulations=200,
        seed=17,
    )
    assert result.binding_rate_source == "full_validation"
    assert result.status is FeasibilityStatus.FEASIBLE
    assert all(rate == Decimal(35) / Decimal(24) for rate in result.stress_rates.values())

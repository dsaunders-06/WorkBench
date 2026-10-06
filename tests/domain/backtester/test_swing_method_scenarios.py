"""Frozen scenario membership and boundary-safe calibrated block sampling."""

from __future__ import annotations

from decimal import Decimal

import numpy as np
import pytest

from qat.domain.backtester import swing_method_audit as audit
from qat.domain.backtester.swing_statistics import (
    ENTRY_MONTH_WCR_S,
    QUARTER_WCR_S,
    InferenceCandidate,
)


def test_scenario_matrix_keeps_supported_persistence_mandatory_and_longer_sensitive() -> None:
    matrix = audit.build_audit_scenario_matrix(
        months=36,
        observations_per_month=8,
        delta_mme=Decimal("0.2"),
        calibrated_block_months=(3, 6),
        generic_persistence_months=(1, 3, 6, 12),
        mandatory_generic_max_months=6,
        null_configurations=("000", "d00"),
        generic_families=("gaussian",),
        imbalance_modes=("observed",),
        diagnostic=True,
    )

    assert {scenario.scenario_id for scenario in matrix.mandatory} == {
        f"{source}-L{length}-{null}"
        for source, lengths in (("calibrated", (3, 6)), ("gaussian", (1, 3, 6)))
        for length in lengths
        for null in ("000", "d00")
    }
    assert {scenario.scenario_id for scenario in matrix.sensitivity} == {
        "gaussian-L12-000",
        "gaussian-L12-d00",
    }
    assert len(matrix.sha256) == 64


def test_regime_supported_two_and_four_month_shocks_are_mandatory() -> None:
    matrix = audit.build_audit_scenario_matrix(
        months=36,
        observations_per_month=8,
        delta_mme=Decimal("0.2"),
        calibrated_block_months=(3, 6),
        generic_persistence_months=(1, 2, 3, 4, 6, 12),
        mandatory_generic_max_months=4,
        null_configurations=("000",),
        generic_families=("gaussian",),
        imbalance_modes=("observed",),
        diagnostic=True,
    )

    assert {cell.block_months for cell in matrix.mandatory if cell.family == "gaussian"} == {
        1,
        2,
        3,
        4,
    }
    assert {cell.block_months for cell in matrix.sensitivity} == {6, 12}


def test_production_matrix_rejects_incomplete_amended_generic_families() -> None:
    with pytest.raises(ValueError, match="amended mandatory generic families"):
        audit.build_audit_scenario_matrix(
            months=36,
            observations_per_month=8,
            delta_mme=Decimal("0.2"),
            calibrated_block_months=(4,),
            generic_persistence_months=(1, 2, 3, 4),
            mandatory_generic_max_months=4,
            null_configurations=("000",),
            generic_families=("gaussian",),
            imbalance_modes=("observed",),
        )


def test_amended_audit_matrix_uses_volatility_and_ar1_mandatory_constant_shocks_sensitive() -> None:
    matrix = audit.build_audit_scenario_matrix(
        months=36,
        observations_per_month=8,
        delta_mme=Decimal("0.2"),
        calibrated_block_months=(4,),
        generic_persistence_months=(1, 2, 3, 4),
        mandatory_generic_max_months=4,
        null_configurations=("000",),
        generic_families=(
            "volatility_regime",
            "ar1_mean",
            "volatility_ar1_stress",
            "empirical_skew",
            "terminal_mixture",
            "gaussian",
        ),
        imbalance_modes=("observed",),
        terminal_probability=Decimal("0.05"),
        terminal_severity=Decimal("-2"),
    )

    assert {cell.family for cell in matrix.mandatory} == {
        "calibrated_block",
        "volatility_regime",
        "ar1_mean",
        "volatility_ar1_stress",
        "empirical_skew",
        "terminal_mixture",
    }
    assert {
        cell.mean_autocorrelation for cell in matrix.mandatory if cell.family == "ar1_mean"
    } == {-0.0874, 0.25}
    assert {
        cell.volatility_autocorrelation
        for cell in matrix.mandatory
        if cell.family in {"volatility_regime", "volatility_ar1_stress"}
    } == {0.4524}
    assert {cell.block_months for cell in matrix.sensitivity if cell.family == "gaussian"} == {
        1,
        2,
        3,
        4,
    }


def test_mandatory_generic_cells_exclude_multimonth_constant_mean_shocks() -> None:
    matrix = audit.build_audit_scenario_matrix(
        months=36,
        observations_per_month=8,
        delta_mme=Decimal("0.2"),
        calibrated_block_months=(4,),
        generic_persistence_months=(1, 2, 3, 4),
        mandatory_generic_max_months=4,
        null_configurations=("000", "d00", "0d0", "00d", "dd0", "d0d", "0dd"),
        generic_families=(
            "volatility_regime",
            "ar1_mean",
            "volatility_ar1_stress",
            "empirical_skew",
            "terminal_mixture",
            "gaussian",
        ),
        imbalance_modes=("observed",),
        terminal_probability=Decimal("0.05"),
        terminal_severity=Decimal("-2"),
    )

    constant_block = {"gaussian", "empirical_skew", "terminal_mixture"}
    assert not [
        cell for cell in matrix.mandatory if cell.family in constant_block and cell.block_months > 1
    ]
    assert {
        (cell.family, cell.block_months, cell.null_configuration)
        for cell in matrix.mandatory
        if cell.family == "volatility_ar1_stress"
    } == {
        ("volatility_ar1_stress", 1, null)
        for null in ("000", "d00", "0d0", "00d", "dd0", "d0d", "0dd")
    }
    assert {
        cell.block_months
        for cell in matrix.sensitivity
        if cell.family in {"empirical_skew", "terminal_mixture"}
    } == {2, 3, 4}


def test_production_matrix_requires_month_independent_skew_and_terminal_cells() -> None:
    with pytest.raises(ValueError, match="month-independent"):
        audit.build_audit_scenario_matrix(
            months=36,
            observations_per_month=8,
            delta_mme=Decimal("0.2"),
            calibrated_block_months=(4,),
            generic_persistence_months=(2, 3, 4),
            mandatory_generic_max_months=4,
            null_configurations=("000",),
            generic_families=(
                "volatility_regime",
                "ar1_mean",
                "volatility_ar1_stress",
                "empirical_skew",
                "terminal_mixture",
            ),
            imbalance_modes=("observed",),
            terminal_probability=Decimal("0.05"),
            terminal_severity=Decimal("-2"),
        )


def test_calibrated_blocks_preserve_joint_months_without_crossing_partitions() -> None:
    names = ("ema_pullback", "bull_flag", "double_bottom")
    development = {
        name: tuple((Decimal(index + offset),) for index in range(1, 7))
        for offset, name in enumerate(names)
    }
    validation = {
        name: tuple((Decimal(100 + index + offset),) for index in range(1, 7))
        for offset, name in enumerate(names)
    }
    frame = audit.CalibratedResidualFrame(development=development, validation=validation)
    scenario = audit.SyntheticScenario(
        scenario_id="calibrated-L3-000",
        family="calibrated_block",
        months=36,
        observations_per_month=1,
        block_months=3,
        null_configuration="000",
        delta_mme=Decimal("0.2"),
    )

    sampled = audit._synthetic_months(scenario, np.random.default_rng(7), calibration=frame)

    for start in range(0, 36, 3):
        ema = [month[0] for month in sampled["ema_pullback"][start : start + 3]]
        assert ema[1] - ema[0] == ema[2] - ema[1] == Decimal(1)
        for name in names:
            assert tuple(month[0] for month in sampled[name][start : start + 3]) == tuple(ema)


def test_calibrated_scenario_requires_an_explicit_frame() -> None:
    scenario = audit.SyntheticScenario(
        scenario_id="calibrated-L3-000",
        family="calibrated_block",
        months=36,
        observations_per_month=1,
        block_months=3,
        null_configuration="000",
        delta_mme=Decimal("0.2"),
    )
    with pytest.raises(ValueError, match="calibration"):
        audit._synthetic_months(scenario, np.random.default_rng(1))


def test_candidate_pilots_use_identical_outer_draws_and_month_weight_matrices() -> None:
    scenario = audit.SyntheticScenario(
        scenario_id="gaussian-L3-000",
        family="gaussian",
        months=36,
        observations_per_month=2,
        block_months=3,
        null_configuration="000",
        delta_mme=Decimal("0.2"),
    )
    candidates = (
        ENTRY_MONTH_WCR_S,
        QUARTER_WCR_S,
        InferenceCandidate("aligned_block", 6),
    )

    pilots = audit.run_candidate_pilots(
        scenario, candidates=candidates, outer_runs=2, inner_draws=64, seed=17, diagnostic=True
    )

    assert tuple(pilots) == candidates
    assert len({pilot.shared_inputs_sha256 for pilot in pilots.values()}) == 1
    assert all(
        len(pilot.attempts) == 2 and not pilot.promotion_eligible for pilot in pilots.values()
    )


def test_random_shock_phase_preserves_persistent_blocks_across_month_zero() -> None:
    class KnownPhaseRng:
        def integers(self, low, high=None):
            assert (low, high) == (0, 4)
            return 2

        def normal(self, size=None):
            return np.arange(size, dtype=float) if size is not None else 0.0

    scenario = audit.SyntheticScenario(
        scenario_id="gaussian-L4-000-random",
        family="gaussian",
        months=12,
        observations_per_month=1,
        block_months=4,
        null_configuration="000",
        delta_mme=Decimal("0.2"),
        shock_phase="random",
    )

    months = audit._synthetic_months(scenario, KnownPhaseRng())

    expected_shocks = (0,) * 2 + (0.35,) * 4 + (0.7,) * 4 + (1.0499999999999998,) * 2
    assert tuple(month[0] for month in months["ema_pullback"]) == tuple(
        Decimal(str(value)) for value in expected_shocks
    )
    assert months["bull_flag"] == months["ema_pullback"] == months["double_bottom"]


def test_random_phase_candidate_pilots_keep_paired_inputs() -> None:
    scenario = audit.SyntheticScenario(
        scenario_id="gaussian-L4-d00-random",
        family="gaussian",
        months=36,
        observations_per_month=2,
        block_months=4,
        null_configuration="d00",
        delta_mme=Decimal("0.2"),
        shock_phase="random",
    )
    pilots = audit.run_candidate_pilots(
        scenario,
        candidates=(ENTRY_MONTH_WCR_S, QUARTER_WCR_S, InferenceCandidate("aligned_block", 4)),
        outer_runs=2,
        inner_draws=64,
        seed=17,
        diagnostic=True,
    )

    assert len({pilot.shared_inputs_sha256 for pilot in pilots.values()}) == 1


def test_ar1_mean_shocks_have_return_bounded_persistence_and_zero_null_mean() -> None:
    scenario = audit.SyntheticScenario(
        scenario_id="ar1-return-000",
        family="ar1_mean",
        months=4000,
        observations_per_month=1,
        block_months=1,
        null_configuration="000",
        delta_mme=Decimal("0.2"),
        mean_autocorrelation=-0.0874,
    )
    monthly = audit._synthetic_months(scenario, np.random.default_rng(17))
    values = np.asarray([float(month[0]) for month in monthly["ema_pullback"]])

    assert abs(float(np.mean(values))) < 0.06
    assert -0.15 < float(np.corrcoef(values[:-1], values[1:])[0, 1]) < 0.01
    with pytest.raises(ValueError, match="return evidence"):
        audit.SyntheticScenario(
            scenario_id="ar1-too-persistent",
            family="ar1_mean",
            months=36,
            observations_per_month=1,
            block_months=1,
            null_configuration="000",
            delta_mme=Decimal("0.2"),
            mean_autocorrelation=0.25,
        )


def test_volatility_regime_has_persistent_variance_without_mean_shift() -> None:
    scenario = audit.SyntheticScenario(
        scenario_id="volatility-regime-000",
        family="volatility_regime",
        months=4000,
        observations_per_month=1,
        block_months=1,
        null_configuration="000",
        delta_mme=Decimal("0.2"),
        volatility_autocorrelation=0.4524,
    )
    monthly = audit._synthetic_months(scenario, np.random.default_rng(17))
    values = np.asarray([float(month[0]) for month in monthly["ema_pullback"]])

    assert abs(float(np.mean(values))) < 0.06
    assert float(np.corrcoef(np.abs(values[:-1]), np.abs(values[1:]))[0, 1]) > 0.01


def test_volatility_regime_matches_observable_proxy_autocorrelation() -> None:
    scales = audit._volatility_regime_scales(50_000, np.random.default_rng(17), 0.4524)

    assert abs(float(np.corrcoef(scales[:-1], scales[1:])[0, 1]) - 0.4524) < 0.015


def test_ar1_stress_targets_monthly_average_outcome_persistence() -> None:
    scenario = audit.SyntheticScenario(
        scenario_id="ar1-average-stress-000",
        family="ar1_mean",
        months=6000,
        observations_per_month=8,
        block_months=1,
        null_configuration="000",
        delta_mme=Decimal("0.2"),
        mean_autocorrelation=0.25,
        dependence_stress=True,
    )
    months = audit._synthetic_months(scenario, np.random.default_rng(17))
    averages = np.asarray([float(sum(month) / len(month)) for month in months["ema_pullback"]])

    assert abs(float(np.corrcoef(averages[:-1], averages[1:])[0, 1]) - 0.25) < 0.04


def test_ar1_centering_preserves_unit_trade_residual_variance() -> None:
    scenario = audit.SyntheticScenario(
        scenario_id="ar1-residual-scale-000",
        family="ar1_mean",
        months=4000,
        observations_per_month=8,
        block_months=1,
        null_configuration="000",
        delta_mme=Decimal("0.2"),
        mean_autocorrelation=0.0,
    )
    months = audit._synthetic_months(scenario, np.random.default_rng(17))
    residuals = np.asarray(
        [
            float(value - sum(month) / len(month))
            for month in months["ema_pullback"]
            for value in month
        ]
    )

    assert abs(float(np.var(residuals)) - 1.0) < 0.03


def test_ar1_monthly_mean_target_survives_varying_projection_month_counts() -> None:
    counts = (5, 6) * 3000
    scenario = audit.SyntheticScenario(
        scenario_id="ar1-variable-count-stress",
        family="ar1_mean",
        months=len(counts),
        observations_per_month=6,
        observation_counts=counts,
        block_months=1,
        null_configuration="000",
        delta_mme=Decimal("0.2"),
        mean_autocorrelation=0.25,
        dependence_stress=True,
    )
    months = audit._synthetic_months(scenario, np.random.default_rng(72))["ema_pullback"]
    averages = np.asarray([float(np.mean(month)) for month in months])

    assert tuple(map(len, months)) == counts
    assert abs(float(np.corrcoef(averages[:-1], averages[1:])[0, 1]) - 0.25) < 0.04

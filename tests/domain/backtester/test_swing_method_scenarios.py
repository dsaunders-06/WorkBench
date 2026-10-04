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
    )

    assert {cell.block_months for cell in matrix.mandatory if cell.family == "gaussian"} == {
        1,
        2,
        3,
        4,
    }
    assert {cell.block_months for cell in matrix.sensitivity} == {6, 12}


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

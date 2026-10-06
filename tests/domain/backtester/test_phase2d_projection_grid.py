"""Power-grid evidence must stay paired and require complete rankings."""

from __future__ import annotations

import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import numpy as np

from qat.domain.backtester.swing_statistics import (
    ENTRY_MONTH_WCR_S,
    romano_wolf_stepdown,
    wcr_s_pvalue,
)
from scripts.research import run_phase2d_projection_grid as grid


def test_projection_grid_has_all_eight_points_and_three_mandatory_models() -> None:
    cells = grid.build_cells()

    assert len(cells) == 24
    assert {(cell.sample_size, cell.effect) for cell in cells} == {
        (size, effect)
        for size in (200, 430)
        for effect in (Decimal("0.10"), Decimal("0.15"), Decimal("0.20"), Decimal("0.30"))
    }
    assert {cell.model for cell in cells} == {"volatility_regime", "ar1_mean", "ar1_mean_stress"}
    assert len({cell.scenario_id for cell in cells}) == 24


def test_projection_grid_is_directly_launchable_from_repository_root() -> None:
    root = Path(__file__).resolve().parents[3]
    completed = subprocess.run(
        [sys.executable, str(root / "scripts/research/run_phase2d_projection_grid.py"), "--help"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr


def test_projection_generator_has_exact_pattern_count_and_additive_effect() -> None:
    low, high = [cell for cell in grid.build_cells() if cell.model == "volatility_regime"][:2]
    low_months = grid.generate_power_months(low, np.random.default_rng(17))
    high_months = grid.generate_power_months(high, np.random.default_rng(17))

    for name in ("ema_pullback", "bull_flag", "double_bottom"):
        assert sum(map(len, low_months[name])) == low.sample_size
        assert sum(map(len, high_months[name])) == high.sample_size
        assert all(len(month) > 0 for month in low_months[name])
        assert all(len(month) > 0 for month in high_months[name])
        assert {
            high_months[name][month][index] - low_months[name][month][index]
            for month in range(36)
            for index in range(len(low_months[name][month]))
        } == {high.effect - low.effect}


def test_projection_pairing_and_prefix_are_reproducible_in_diagnostic_run() -> None:
    cell = grid.build_cells()[0]
    first = grid.run_cell_attempts(cell, outer_runs=2, inner_draws=64)
    replay = grid.run_cell_attempts(cell, outer_runs=3, inner_draws=64)

    assert first["attempts"] == replay["attempts"][:2]
    assert first["shared_inputs_sha256"] != replay["shared_inputs_sha256"]
    assert all(len(row[1]) == 3 for row in first["attempts"])
    assert all(len(patterns) == 3 for row in first["attempts"] for patterns in row[1])


def test_rankings_use_worst_pattern_and_extend_ambiguous_20k_points() -> None:
    cells = [
        cell
        for cell in grid.build_cells()
        if cell.sample_size == 200 and cell.effect == Decimal("0.10")
    ]
    summaries = {
        cell.scenario_id: {
            "sample_size": cell.sample_size,
            "effect": str(cell.effect),
            "model": cell.model,
            "outer_runs": 20_000,
            "candidate_rejections": {
                "entry_month-L1": [12_000, 12_000, 12_000],
                "quarter-L3": [13_000, 13_000, 13_000],
                "aligned_block-L4": [11_000, 11_000, 11_000],
            },
        }
        for cell in cells
    }
    order, extend = grid.rank_point(summaries)
    assert order == ("quarter-L3", "entry_month-L1", "aligned_block-L4")
    assert not extend

    for summary in summaries.values():
        summary["candidate_rejections"]["entry_month-L1"][1] = 13_005
    assert grid.rank_point(summaries)[0][0] == "quarter-L3"
    for summary in summaries.values():
        summary["candidate_rejections"]["entry_month-L1"] = [13_005] * 3
    order, extend = grid.rank_point(summaries)
    assert order == ("entry_month-L1", "quarter-L3", "aligned_block-L4")
    assert extend


def test_projected_rejection_requires_both_confidence_and_family_gates() -> None:
    months = tuple((Decimal(index),) for index in (1, 2, 3, 4, 5))
    samples = {name: months for name in ("ema_pullback", "bull_flag", "double_bottom")}

    assert wcr_s_pvalue(months) == Decimal("0.03125")
    assert romano_wolf_stepdown(samples).adjusted_p_values["bull_flag"] == Decimal("0.03125")
    assert grid.projection_rejections(
        samples, weights=None, draws=9999, candidate=ENTRY_MONTH_WCR_S
    ) == (False, False, False)

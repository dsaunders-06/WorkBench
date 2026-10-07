"""The final Holm candidate reuses frozen inputs and obeys the stop rule."""

from __future__ import annotations

import importlib
import json
import subprocess
import sys
from pathlib import Path

import pytest


def _runner():
    return importlib.import_module("scripts.research.run_phase2d_holm_pilot")


def test_holm_runner_uses_exactly_the_28_existing_mandatory_cells() -> None:
    from scripts.research import run_phase2c_generic_method_pilot as prior

    runner = _runner()
    cells = runner.build_mandatory_cells()

    assert runner.CANDIDATE.family_method == "holm"
    assert runner.CANDIDATE.block_months == 4
    assert tuple(cell.scenario_id for cell in cells) == tuple(
        cell.scenario_id
        for cell in (*prior.build_amended_cells()[0], *prior.build_combined_stress_cells())
    )
    assert len(cells) == 28


def test_holm_runner_applies_binding_all_cells_stopping_rule() -> None:
    runner = _runner()
    cells = runner.build_mandatory_cells()
    pass_rows = [{"scenario_id": cell.scenario_id, "status": "METHOD_ADEQUATE"} for cell in cells]

    assert runner.selection_status(pass_rows[:-1], cells) == "INCOMPLETE"
    assert runner.selection_status(pass_rows, cells) == "METHOD_ADEQUATE"
    fail_rows = [*pass_rows]
    fail_rows[8] = {**fail_rows[8], "status": "METHOD_INADEQUATE"}
    assert runner.selection_status(fail_rows, cells) == "METHOD_INADEQUATE"


def test_holm_runner_refuses_mismatched_paired_input_hash(tmp_path: Path) -> None:
    runner = _runner()
    scenario = runner.build_mandatory_cells()[0]
    reference = tmp_path / f"{scenario.scenario_id}--aligned_block-L4--20000.json"
    reference.write_text(
        json.dumps(
            {"candidate": "aligned_block-L4", "outer_runs": 20_000, "shared_inputs_sha256": "old"}
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="paired input"):
        runner.require_paired_inputs(tmp_path, scenario, 20_000, "new")


def test_holm_runner_refuses_resume_with_changed_source_manifest(tmp_path: Path) -> None:
    runner = _runner()
    original = {"candidate": "aligned_block_holm-L4", "source_sha256": "first"}

    runner.ensure_manifest(tmp_path, original)
    runner.ensure_manifest(tmp_path, original)

    with pytest.raises(ValueError, match="manifest"):
        runner.ensure_manifest(tmp_path, {**original, "source_sha256": "changed"})


def test_holm_runner_script_resolves_its_own_checkout() -> None:
    root = Path(__file__).resolve().parents[3]
    result = subprocess.run(
        [sys.executable, str(root / "scripts/research/run_phase2d_holm_pilot.py"), "--help"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "--prior-report" in result.stdout

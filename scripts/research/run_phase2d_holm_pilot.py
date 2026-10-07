"""Resumable 28-cell final Holm candidate pilot; raw attempts stay outside Git."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from qat.domain.backtester.swing_method_audit import MethodStatus  # noqa: E402
from qat.domain.backtester.swing_statistics import InferenceCandidate  # noqa: E402
from scripts.research import run_phase2c_generic_method_pilot as pilot  # noqa: E402

CANDIDATE = InferenceCandidate("aligned_block", 4, "holm")


def build_mandatory_cells() -> tuple:
    """Keep the already frozen 21 generic and seven combined scenario IDs."""
    generic, _ = pilot.build_amended_cells()
    return (*generic, *pilot.build_combined_stress_cells())


def selection_status(summaries: list[dict], cells: tuple) -> str:
    """One failure makes the final candidate inadequate, after all cells finish."""
    required = {cell.scenario_id for cell in cells}
    if len(summaries) != len(cells) or {row["scenario_id"] for row in summaries} != required:
        return "INCOMPLETE"
    return (
        MethodStatus.METHOD_ADEQUATE.value
        if all(row["status"] == MethodStatus.METHOD_ADEQUATE.value for row in summaries)
        else MethodStatus.METHOD_INADEQUATE.value
    )


def _reference_dir(scenario, generic_dir: Path, combined_dir: Path) -> Path:
    return combined_dir if scenario.family == "volatility_ar1_stress" else generic_dir


def require_paired_inputs(
    reference_dir: Path, scenario, outer_runs: int, shared_inputs_sha256: str
) -> bool:
    """Check the existing L=4 checkpoint where one was produced."""
    path = reference_dir / f"{scenario.scenario_id}--aligned_block-L4--{outer_runs}.json"
    if not path.exists():
        if outer_runs == pilot.INITIAL_OUTER:
            raise ValueError(f"missing paired input reference: {path}")
        return False
    reference = json.loads(path.read_text(encoding="utf-8"))
    if (
        reference.get("candidate") != "aligned_block-L4"
        or reference.get("outer_runs") != outer_runs
        or reference.get("shared_inputs_sha256") != shared_inputs_sha256
    ):
        raise ValueError(f"paired input mismatch: {path}")
    return True


def require_prior_reports(generic_path: Path, combined_path: Path) -> tuple[str, str]:
    generic_bytes = generic_path.read_bytes()
    combined_bytes = combined_path.read_bytes()
    generic = json.loads(generic_bytes)
    combined = json.loads(combined_bytes)
    mandatory, _ = pilot.build_amended_cells()
    combined_cells = pilot.build_combined_stress_cells()
    if (
        generic.get("phase") != "pre-declaration generic pilot"
        or generic.get("completed_cells") != 77
        or {cell["scenario_id"] for cell in generic.get("cells", ()) if cell["role"] == "mandatory"}
        != {cell.scenario_id for cell in mandatory}
        or combined.get("phase") != "pre-declaration combined-dependence pilot"
        or combined.get("completed_cells") != 7
        or {cell["scenario_id"] for cell in combined.get("cells", ())}
        != {cell.scenario_id for cell in combined_cells}
        or combined.get("prior_report_sha256") != hashlib.sha256(generic_bytes).hexdigest()
    ):
        raise ValueError("both completed, linked prior pilot reports are required")
    return hashlib.sha256(generic_bytes).hexdigest(), hashlib.sha256(combined_bytes).hexdigest()


def ensure_manifest(directory: Path, payload: dict) -> None:
    """Refuse to resume checkpoints with a different frozen recipe or code."""
    path = directory / "manifest.json"
    if path.exists():
        if json.loads(path.read_text(encoding="utf-8")) != payload:
            raise ValueError("Holm pilot manifest differs from existing checkpoints")
    else:
        pilot._atomic_json(path, payload)


def run_cell(scenario, output_dir: Path, generic_dir: Path, combined_dir: Path) -> dict:
    reference_dir = _reference_dir(scenario, generic_dir, combined_dir)
    initial = pilot._read_or_run(scenario, CANDIDATE, pilot.INITIAL_OUTER, output_dir)
    require_paired_inputs(
        reference_dir, scenario, pilot.INITIAL_OUTER, initial["shared_inputs_sha256"]
    )
    selected = initial
    decisions = pilot._decisions(scenario, selected, CANDIDATE)
    if any(item["status"] == MethodStatus.METHOD_AUDIT_PENDING.value for item in decisions):
        extended = pilot._read_or_run(scenario, CANDIDATE, pilot.MAXIMUM_OUTER, output_dir)
        if extended["attempts"][: pilot.INITIAL_OUTER] != initial["attempts"]:
            raise ValueError(f"100k run changed the 20k prefix for {scenario.scenario_id}")
        selected = extended
        decisions = pilot._decisions(scenario, selected, CANDIDATE)
    verified_selected = require_paired_inputs(
        reference_dir, scenario, selected["outer_runs"], selected["shared_inputs_sha256"]
    )
    summary = {
        "scenario_id": scenario.scenario_id,
        "role": "mandatory",
        "family": scenario.family,
        "null_configuration": scenario.null_configuration,
        "candidate": pilot._candidate_name(CANDIDATE),
        "seed": pilot.seed_for(scenario),
        "inner_seed": pilot.inner_seed_for(scenario),
        "outer_runs": selected["outer_runs"],
        "attempts_sha256": selected["attempts_sha256"],
        "shared_inputs_sha256": selected["shared_inputs_sha256"],
        "paired_reference_verified_at_selected_runs": verified_selected,
        "decisions": decisions,
        "status": (
            MethodStatus.METHOD_ADEQUATE.value
            if all(item["status"] == MethodStatus.METHOD_ADEQUATE.value for item in decisions)
            else MethodStatus.METHOD_INADEQUATE.value
        ),
    }
    pilot._atomic_json(output_dir / f"{scenario.scenario_id}--holm-summary.json", summary)
    return summary


def write_report(output_dir: Path, cells: tuple, generic_hash: str, combined_hash: str) -> dict:
    summaries = []
    for scenario in cells:
        path = output_dir / f"{scenario.scenario_id}--holm-summary.json"
        if path.exists():
            summaries.append(json.loads(path.read_text(encoding="utf-8")))
    report = {
        "phase": "pre-declaration final Holm candidate pilot",
        "candidate": pilot._candidate_name(CANDIDATE),
        "generic_report_sha256": generic_hash,
        "combined_report_sha256": combined_hash,
        "mandatory_cells": len(cells),
        "completed_cells": len(summaries),
        "inner_draws": pilot.INNER_DRAWS,
        "initial_outer_runs": pilot.INITIAL_OUTER,
        "maximum_outer_runs": pilot.MAXIMUM_OUTER,
        "selection_status": selection_status(summaries, cells),
        "cells": summaries,
    }
    pilot._atomic_json(output_dir / "holm-report.json", report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prior-report", type=Path, required=True)
    parser.add_argument("--combined-report", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    if not 1 <= args.workers <= 12:
        parser.error("workers must be between 1 and 12")
    output_dir = args.output_dir.resolve()
    if any((path / ".git").exists() for path in (output_dir, *output_dir.parents)):
        parser.error("raw pilot output must be outside Git")
    generic_hash, combined_hash = require_prior_reports(args.prior_report, args.combined_report)
    output_dir.mkdir(parents=True, exist_ok=True)
    cells = build_mandatory_cells()
    source_paths = (
        ROOT / "src/qat/domain/backtester/swing_statistics.py",
        ROOT / "src/qat/domain/backtester/swing_method_audit.py",
        ROOT / "scripts/research/run_phase2c_generic_method_pilot.py",
        Path(__file__).resolve(),
    )
    ensure_manifest(
        output_dir,
        {
            "manifest_version": 1,
            "candidate": pilot._candidate_name(CANDIDATE),
            "scenario_ids": [cell.scenario_id for cell in cells],
            "generic_report_sha256": generic_hash,
            "combined_report_sha256": combined_hash,
            "seed_domains": {
                "outer_null": pilot.OUTER_NULL_SEED,
                "inner_signs": pilot.INNER_SIGNS_SEED,
            },
            "inner_draws": pilot.INNER_DRAWS,
            "outer_runs": [pilot.INITIAL_OUTER, pilot.MAXIMUM_OUTER],
            "python": sys.version.split()[0],
            "numpy": np.__version__,
            "source_sha256": {
                str(path.relative_to(ROOT))
                .replace("\\", "/"): hashlib.sha256(path.read_bytes())
                .hexdigest()
                for path in source_paths
            },
            "regeneration_command": (
                "python scripts/research/run_phase2d_holm_pilot.py "
                f"--prior-report {args.prior_report.resolve()} "
                f"--combined-report {args.combined_report.resolve()} "
                f"--output-dir {output_dir} --workers 8"
            ),
        },
    )
    started = time.perf_counter()
    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(
                run_cell,
                scenario,
                output_dir,
                args.prior_report.parent,
                args.combined_report.parent,
            ): scenario
            for scenario in cells
        }
        for future in as_completed(futures):
            summary = future.result()
            report = write_report(output_dir, cells, generic_hash, combined_hash)
            print(
                json.dumps(
                    {
                        "completed": report["completed_cells"],
                        "total": len(cells),
                        "scenario_id": summary["scenario_id"],
                        "elapsed_seconds": round(time.perf_counter() - started, 1),
                    }
                ),
                flush=True,
            )
    report = write_report(output_dir, cells, generic_hash, combined_hash)
    print(
        json.dumps(
            {"complete": len(report["cells"]) == len(cells), "status": report["selection_status"]}
        )
    )


if __name__ == "__main__":
    main()

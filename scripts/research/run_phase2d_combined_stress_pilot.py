"""Run the seven approved combined-dependence cells after the current pilot."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from qat.domain.backtester.swing_method_audit import MethodStatus  # noqa: E402
from scripts.research import run_phase2c_generic_method_pilot as pilot  # noqa: E402


def require_prior_pilot_complete(path: Path) -> dict:
    """Refuse a combined-stress run until all 77 existing cells are recorded."""
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError("complete prior pilot report is required") from exc
    if (
        report.get("phase") != "pre-declaration generic pilot"
        or report.get("matrix_cells") != 77
        or report.get("completed_cells") != 77
        or len(report.get("cells", ())) != 77
    ):
        raise ValueError("complete prior pilot report is required")
    return report


def _report(directory: Path, prior_report: dict, prior_hash: str, cells: tuple) -> dict:
    completed = []
    for scenario in cells:
        path = directory / f"{scenario.scenario_id}--summary.json"
        if path.exists():
            completed.append(json.loads(path.read_text(encoding="utf-8")))
    candidate_status = {}
    for candidate in pilot.CANDIDATES:
        name = pilot._candidate_name(candidate)
        prior_status = prior_report["candidates"].get(name, "INCOMPLETE")
        if len(completed) != 7 or prior_status == "INCOMPLETE":
            status = "INCOMPLETE"
        elif prior_status == MethodStatus.METHOD_ADEQUATE.value and all(
            next(item for item in summary["candidates"] if item["candidate"] == name)["status"]
            == MethodStatus.METHOD_ADEQUATE.value
            for summary in completed
        ):
            status = MethodStatus.METHOD_ADEQUATE.value
        else:
            status = MethodStatus.METHOD_INADEQUATE.value
        candidate_status[name] = {"prior": prior_status, "with_combined_stress": status}
    report = {
        "phase": "pre-declaration combined-dependence pilot",
        "prior_report_sha256": prior_hash,
        "mandatory_combined_cells": 7,
        "completed_cells": len(completed),
        "inner_draws": pilot.INNER_DRAWS,
        "initial_outer_runs": pilot.INITIAL_OUTER,
        "maximum_outer_runs": pilot.MAXIMUM_OUTER,
        "candidates": candidate_status,
        "cells": completed,
    }
    pilot._atomic_json(directory / "combined-report.json", report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prior-report", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    if not 1 <= args.workers <= 12:
        parser.error("workers must be between 1 and 12")
    output_dir = args.output_dir.resolve()
    if output_dir.is_relative_to(ROOT.resolve()):
        parser.error("raw pilot output must be outside the Git checkout")
    prior_report = require_prior_pilot_complete(args.prior_report)
    prior_hash = hashlib.sha256(args.prior_report.read_bytes()).hexdigest()
    output_dir.mkdir(parents=True, exist_ok=True)
    cells = pilot.build_combined_stress_cells()
    started = time.perf_counter()
    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(pilot.run_cell, scenario, output_dir, "mandatory"): scenario
            for scenario in cells
        }
        for future in as_completed(futures):
            summary = future.result()
            report = _report(output_dir, prior_report, prior_hash, cells)
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
    report = _report(output_dir, prior_report, prior_hash, cells)
    print(json.dumps({"complete": len(report["cells"]) == 7, "status": report["candidates"]}))


if __name__ == "__main__":
    main()

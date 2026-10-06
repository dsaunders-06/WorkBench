"""Resumable Phase 2C generic Gaussian method pilot; raw attempts stay outside Git."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from qat.domain.backtester import swing_method_audit as audit  # noqa: E402
from qat.domain.backtester.swing_statistics import (  # noqa: E402
    ENTRY_MONTH_WCR_S,
    QUARTER_WCR_S,
    InferenceCandidate,
)

CANDIDATES = (ENTRY_MONTH_WCR_S, QUARTER_WCR_S, InferenceCandidate("aligned_block", 4))
NULLS = ("000", "d00", "0d0", "00d", "dd0", "d0d", "0dd")
INNER_DRAWS = 9_999
INITIAL_OUTER = 20_000
MAXIMUM_OUTER = 100_000
BASE_SEED = 20261005
OUTER_NULL_SEED = 845317
INNER_SIGNS_SEED = 845318
POWER_SEED = 845319


def build_cells() -> tuple[audit.SyntheticScenario, ...]:
    return tuple(
        audit.SyntheticScenario(
            scenario_id=f"generic-gaussian-L{months}-{null}-{phase}",
            family="gaussian",
            months=36,
            observations_per_month=8,
            block_months=months,
            null_configuration=null,
            delta_mme=Decimal("0.2"),
            shock_phase=phase,
        )
        for months in (1, 2, 3, 4)
        for null in NULLS
        for phase in ("aligned", "random")
    )


def build_amended_cells() -> (
    tuple[tuple[audit.SyntheticScenario, ...], tuple[audit.SyntheticScenario, ...]]
):
    """Market-return-bounded mean dependence and calibrated volatility are mandatory."""
    mandatory = tuple(
        audit.SyntheticScenario(
            scenario_id=f"generic-{family}-{label}-{null}-observable-v2",
            family=family,
            months=36,
            observations_per_month=8,
            block_months=1,
            null_configuration=null,
            delta_mme=Decimal("0.2"),
            mean_autocorrelation=mean_phi,
            volatility_autocorrelation=vol_phi,
            dependence_stress=stress,
        )
        for family, label, mean_phi, vol_phi, stress in (
            ("volatility_regime", "proxy-phi04524", 0.0, 0.4524, False),
            ("ar1_mean", "return-phi-negative00874", -0.0874, 0.0, False),
            ("ar1_mean", "stress-phi025", 0.25, 0.0, True),
        )
        for null in NULLS
    )
    return mandatory, build_cells()


def build_combined_stress_cells() -> tuple[audit.SyntheticScenario, ...]:
    """The seven operator-added mandatory volatility-plus-mean stress cells."""
    return tuple(
        audit.SyntheticScenario(
            scenario_id=f"generic-combined-vol04524-mean025-{null}-observable-v2",
            family="volatility_ar1_stress",
            months=36,
            observations_per_month=8,
            block_months=1,
            null_configuration=null,
            delta_mme=Decimal("0.2"),
            mean_autocorrelation=0.25,
            volatility_autocorrelation=0.4524,
            dependence_stress=True,
        )
        for null in NULLS
    )


def seed_for(scenario: audit.SyntheticScenario) -> int:
    digest = hashlib.sha256(f"{OUTER_NULL_SEED}:{scenario.scenario_id}".encode("ascii")).digest()
    return int.from_bytes(digest[:8], "big")


def inner_seed_for(scenario: audit.SyntheticScenario) -> int:
    digest = hashlib.sha256(f"{INNER_SIGNS_SEED}:{scenario.scenario_id}".encode("ascii")).digest()
    return int.from_bytes(digest[:8], "big")


def power_seed_for(scenario: audit.SyntheticScenario) -> int:
    digest = hashlib.sha256(f"{POWER_SEED}:{scenario.scenario_id}".encode("ascii")).digest()
    return int.from_bytes(digest[:8], "big")


def _candidate_name(candidate: InferenceCandidate) -> str:
    return f"{candidate.method}-L{candidate.block_months}"


def _atomic_json(path: Path, payload: dict) -> None:
    temporary = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, separators=(",", ":")) + "\n", encoding="utf-8")
    temporary.replace(path)


def _attempt_rows(result: audit.SyntheticPilotResult) -> list[list]:
    return [
        [item.attempt, list(item.confidence_rejections), item.family_false_positive]
        for item in result.attempts
    ]


def _read_or_run(
    scenario: audit.SyntheticScenario,
    candidate: InferenceCandidate,
    outer_runs: int,
    directory: Path,
) -> dict:
    path = directory / f"{scenario.scenario_id}--{_candidate_name(candidate)}--{outer_runs}.json"
    seed = seed_for(scenario)
    inner_seed = inner_seed_for(scenario)
    if path.exists():
        payload = json.loads(path.read_text(encoding="utf-8"))
        if (
            payload["scenario_id"] != scenario.scenario_id
            or payload["candidate"] != _candidate_name(candidate)
            or payload["outer_runs"] != outer_runs
            or payload["inner_draws"] != INNER_DRAWS
            or payload["seed"] != seed
            or payload["inner_seed"] != inner_seed
            or len(payload["attempts"]) != outer_runs
        ):
            raise ValueError(f"checkpoint metadata mismatch: {path}")
        digest = hashlib.sha256(
            json.dumps(payload["attempts"], separators=(",", ":")).encode("ascii")
        ).hexdigest()
        if digest != payload["attempts_sha256"]:
            raise ValueError(f"checkpoint attempt hash mismatch: {path}")
        return payload
    started = time.perf_counter()
    result = audit.run_synthetic_pilot(
        scenario,
        outer_runs=outer_runs,
        inner_draws=INNER_DRAWS,
        seed=seed,
        inner_seed=inner_seed,
        candidate=candidate,
    )
    payload = {
        "scenario_id": scenario.scenario_id,
        "candidate": _candidate_name(candidate),
        "seed": seed,
        "inner_seed": inner_seed,
        "outer_runs": outer_runs,
        "inner_draws": INNER_DRAWS,
        "seconds": time.perf_counter() - started,
        "attempts_sha256": result.attempts_sha256,
        "shared_inputs_sha256": result.shared_inputs_sha256,
        "attempts": _attempt_rows(result),
    }
    _atomic_json(path, payload)
    return payload


def _decisions(scenario: audit.SyntheticScenario, payload: dict) -> list[dict]:
    null_indices = [index for index, flag in enumerate(scenario.null_configuration) if flag == "0"]
    rows = payload["attempts"]
    size = (
        audit.ScenarioSizeAudit(
            f"{scenario.scenario_id}:confidence",
            "confidence",
            len(rows),
            max(sum(row[1][index] for row in rows) for index in null_indices),
            payload["attempts_sha256"],
        ),
        audit.ScenarioSizeAudit(
            f"{scenario.scenario_id}:family",
            "family",
            len(rows),
            sum(row[2] for row in rows),
            payload["attempts_sha256"],
        ),
    )
    protocol = audit.MethodAuditProtocol(
        mandatory_scenarios=tuple(item.scenario_id for item in size),
        candidate_methods=CANDIDATES,
    )
    result = audit.audit_method_size(protocol, size)
    return [
        {
            "gate": item.gate,
            "rejections": size[index].false_rejections,
            "runs": item.outer_runs,
            "point_rate": str(item.point_rate),
            "wilson_one_sided_95": [str(item.lower_95), str(item.upper_95)],
            "cap": str(item.cap),
            "status": item.status.value,
        }
        for index, item in enumerate(result.scenarios)
    ]


def run_cell(scenario: audit.SyntheticScenario, output_dir: Path, role: str) -> dict:
    initial = {
        candidate: _read_or_run(scenario, candidate, INITIAL_OUTER, output_dir)
        for candidate in CANDIDATES
    }
    if len({payload["shared_inputs_sha256"] for payload in initial.values()}) != 1:
        raise ValueError(f"candidate inputs diverged in {scenario.scenario_id}")
    summaries = []
    for candidate in CANDIDATES:
        payload = initial[candidate]
        decisions = _decisions(scenario, payload)
        if any(item["status"] == audit.MethodStatus.METHOD_AUDIT_PENDING for item in decisions):
            extended = _read_or_run(scenario, candidate, MAXIMUM_OUTER, output_dir)
            if extended["attempts"][:INITIAL_OUTER] != payload["attempts"]:
                raise ValueError(f"100k run changed the 20k prefix for {scenario.scenario_id}")
            payload = extended
            decisions = _decisions(scenario, payload)
        summaries.append(
            {
                "candidate": _candidate_name(candidate),
                "outer_runs": payload["outer_runs"],
                "attempts_sha256": payload["attempts_sha256"],
                "shared_inputs_sha256": payload["shared_inputs_sha256"],
                "decisions": decisions,
                "status": (
                    audit.MethodStatus.METHOD_ADEQUATE.value
                    if all(
                        item["status"] == audit.MethodStatus.METHOD_ADEQUATE for item in decisions
                    )
                    else audit.MethodStatus.METHOD_INADEQUATE.value
                ),
            }
        )
    summary = {
        "scenario_id": scenario.scenario_id,
        "role": role,
        "family": scenario.family,
        "persistence_months": scenario.block_months,
        "null_configuration": scenario.null_configuration,
        "shock_phase": scenario.shock_phase,
        "seed": seed_for(scenario),
        "candidates": summaries,
    }
    _atomic_json(output_dir / f"{scenario.scenario_id}--summary.json", summary)
    return summary


def _write_report(directory: Path, cells: tuple[audit.SyntheticScenario, ...]) -> dict:
    summaries = []
    for scenario in cells:
        path = directory / f"{scenario.scenario_id}--summary.json"
        if path.exists():
            summaries.append(json.loads(path.read_text(encoding="utf-8")))
    status = {}
    for candidate in CANDIDATES:
        name = _candidate_name(candidate)
        mandatory = [summary for summary in summaries if summary["role"] == "mandatory"]
        if len(mandatory) != 21:
            status[name] = "INCOMPLETE"
        elif all(
            next(item for item in summary["candidates"] if item["candidate"] == name)["status"]
            == audit.MethodStatus.METHOD_ADEQUATE.value
            for summary in mandatory
        ):
            status[name] = audit.MethodStatus.METHOD_ADEQUATE.value
        else:
            status[name] = audit.MethodStatus.METHOD_INADEQUATE.value
    report = {
        "phase": "pre-declaration generic pilot",
        "matrix_cells": len(cells),
        "mandatory_cells": 21,
        "sensitivity_cells": len(cells) - 21,
        "completed_cells": len(summaries),
        "inner_draws": INNER_DRAWS,
        "initial_outer_runs": INITIAL_OUTER,
        "maximum_outer_runs": MAXIMUM_OUTER,
        "seeds": {
            "exploratory": BASE_SEED,
            "outer_null": OUTER_NULL_SEED,
            "inner_signs": INNER_SIGNS_SEED,
            "power": POWER_SEED,
        },
        "candidates": status,
        "cells": summaries,
    }
    _atomic_json(directory / "report.json", report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    output_dir = args.output_dir.resolve()
    if output_dir.is_relative_to(ROOT.resolve()):
        parser.error("raw pilot output must be outside the Git checkout")
    if not 1 <= args.workers <= 12:
        parser.error("workers must be between 1 and 12")
    output_dir.mkdir(parents=True, exist_ok=True)
    mandatory, sensitivity = build_amended_cells()
    cells = (*mandatory, *sensitivity)
    started = time.perf_counter()
    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(
                run_cell,
                scenario,
                output_dir,
                "mandatory" if scenario in mandatory else "sensitivity",
            ): scenario
            for scenario in cells
        }
        for future in as_completed(futures):
            summary = future.result()
            report = _write_report(output_dir, cells)
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
    report = _write_report(output_dir, cells)
    print(
        json.dumps({"complete": len(report["cells"]) == len(cells), "status": report["candidates"]})
    )


if __name__ == "__main__":
    main()

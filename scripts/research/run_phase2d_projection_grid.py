"""Paired pre-declaration projection rankings; raw power stays outside Git."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import time
from collections.abc import Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from qat.domain.backtester import swing_method_audit as audit  # noqa: E402
from qat.domain.backtester.swing_statistics import (  # noqa: E402
    InferenceCandidate,
    romano_wolf_stepdown,
    wcr_s_pvalue,
)
from scripts.research.run_phase2c_generic_method_pilot import (  # noqa: E402
    CANDIDATES,
    INITIAL_OUTER,
    INNER_DRAWS,
    INNER_SIGNS_SEED,
    MAXIMUM_OUTER,
    POWER_SEED,
)

PATTERNS = ("ema_pullback", "bull_flag", "double_bottom")
MODELS = ("volatility_regime", "ar1_mean", "ar1_mean_stress")
EFFECTS = (Decimal("0.10"), Decimal("0.15"), Decimal("0.20"), Decimal("0.30"))
CANDIDATE_NAMES = tuple(f"{candidate.method}-L{candidate.block_months}" for candidate in CANDIDATES)
CLUSTERS = dict(zip(CANDIDATE_NAMES, (36, 12, 9), strict=True))


@dataclass(frozen=True, slots=True)
class ProjectionCell:
    sample_size: int
    effect: Decimal
    model: str

    @property
    def scenario_id(self) -> str:
        return f"projection-N{self.sample_size}-d{self.effect}-{self.model}-observable-v2"


def build_cells() -> tuple[ProjectionCell, ...]:
    return tuple(
        ProjectionCell(sample_size, effect, model)
        for sample_size in (200, 430)
        for effect in EFFECTS
        for model in MODELS
    )


def _derive_seed(base: int, scenario_id: str, replicate: int) -> int:
    digest = hashlib.sha256(f"{base}:{scenario_id}:{replicate}".encode("ascii")).digest()
    return int.from_bytes(digest[:8], "big")


def _scenario(cell: ProjectionCell) -> audit.SyntheticScenario:
    return audit.SyntheticScenario(
        scenario_id=cell.scenario_id,
        family="volatility_regime" if cell.model == "volatility_regime" else "ar1_mean",
        months=36,
        observations_per_month=math.ceil(cell.sample_size / 36),
        observation_counts=tuple(
            cell.sample_size // 36 + (index < cell.sample_size % 36) for index in range(36)
        ),
        block_months=1,
        null_configuration="000",
        delta_mme=cell.effect,
        mean_autocorrelation=(
            0.25
            if cell.model == "ar1_mean_stress"
            else -0.0874 if cell.model == "ar1_mean" else 0.0
        ),
        volatility_autocorrelation=0.4524 if cell.model == "volatility_regime" else 0.0,
        dependence_stress=cell.model == "ar1_mean_stress",
    )


def generate_power_months(
    cell: ProjectionCell, rng: np.random.Generator
) -> dict[str, tuple[tuple[Decimal, ...], ...]]:
    """Keep exactly N observations per pattern and shift every true alternative."""
    source = audit._synthetic_months(_scenario(cell), rng)
    return {
        name: tuple(tuple(value + cell.effect for value in month) for month in source[name])
        for name in PATTERNS
    }


def projection_rejections(
    months: Mapping[str, Sequence[Sequence[Decimal]]],
    *,
    weights: Sequence[Sequence[int]] | None,
    draws: int,
    candidate: InferenceCandidate,
) -> tuple[bool, bool, bool]:
    """Count a pattern only when both declared inference gates reject."""
    family = romano_wolf_stepdown(months, weights=weights, draws=draws, candidate=candidate)
    return tuple(
        wcr_s_pvalue(months[name], weights=weights, draws=draws, candidate=candidate)
        < Decimal("0.025")
        and family.adjusted_p_values[name] < Decimal("0.05")
        for name in PATTERNS
    )  # type: ignore[return-value]


def run_cell_attempts(cell: ProjectionCell, *, outer_runs: int, inner_draws: int) -> dict[str, Any]:
    """One outer sample and sign matrix feed all three candidates."""
    if outer_runs <= 0 or inner_draws <= 0:
        raise ValueError("projection simulation counts must be positive")
    attempts: list[list[Any]] = []
    input_digest = hashlib.sha256()
    counts = {name: [0, 0, 0] for name in CANDIDATE_NAMES}
    started = time.perf_counter()
    for replicate in range(outer_runs):
        months = generate_power_months(
            cell,
            np.random.Generator(
                np.random.PCG64(_derive_seed(POWER_SEED, cell.scenario_id, replicate))
            ),
        )
        weights = np.where(
            np.random.Generator(
                np.random.PCG64(_derive_seed(INNER_SIGNS_SEED, cell.scenario_id, replicate))
            ).integers(0, 2, size=(inner_draws, 36))
            == 0,
            -1,
            1,
        ).astype(np.int8)
        input_digest.update(
            json.dumps(
                [[[str(value) for value in month] for month in months[name]] for name in PATTERNS],
                separators=(",", ":"),
            ).encode("ascii")
        )
        input_digest.update(weights.tobytes())
        weight_rows = weights.tolist()
        candidate_rows: list[list[bool]] = []
        for candidate, name in zip(CANDIDATES, CANDIDATE_NAMES, strict=True):
            rejected = list(
                projection_rejections(
                    months, weights=weight_rows, draws=inner_draws, candidate=candidate
                )
            )
            candidate_rows.append(rejected)
            for index, value in enumerate(rejected):
                counts[name][index] += value
        attempts.append([replicate, candidate_rows])
    encoded = json.dumps(attempts, separators=(",", ":")).encode("ascii")
    return {
        "scenario_id": cell.scenario_id,
        "sample_size": cell.sample_size,
        "effect": str(cell.effect),
        "model": cell.model,
        "outer_runs": outer_runs,
        "inner_draws": inner_draws,
        "seconds": time.perf_counter() - started,
        "shared_inputs_sha256": input_digest.hexdigest(),
        "attempts_sha256": hashlib.sha256(encoded).hexdigest(),
        "attempts": attempts,
        "candidate_rejections": counts,
    }


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, separators=(",", ":")) + "\n", encoding="utf-8")
    temporary.replace(path)


def _read_or_run(
    cell: ProjectionCell, outer_runs: int, inner_draws: int, directory: Path
) -> dict[str, Any]:
    path = directory / f"{cell.scenario_id}--{outer_runs}.json"
    if path.exists():
        payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        if (
            payload["scenario_id"] != cell.scenario_id
            or payload["outer_runs"] != outer_runs
            or payload["inner_draws"] != inner_draws
            or len(payload["attempts"]) != outer_runs
        ):
            raise ValueError(f"projection checkpoint metadata mismatch: {path}")
        digest = hashlib.sha256(
            json.dumps(payload["attempts"], separators=(",", ":")).encode("ascii")
        ).hexdigest()
        if digest != payload["attempts_sha256"]:
            raise ValueError(f"projection checkpoint hash mismatch: {path}")
        return payload
    payload = run_cell_attempts(cell, outer_runs=outer_runs, inner_draws=inner_draws)
    _atomic_json(path, payload)
    return payload


def _wilson_95(successes: int, trials: int) -> tuple[float, float]:
    z = 1.959963984540054
    p = successes / trials
    denominator = 1 + z * z / trials
    centre = (p + z * z / (2 * trials)) / denominator
    radius = z * math.sqrt(p * (1 - p) / trials + z * z / (4 * trials * trials)) / denominator
    return centre - radius, centre + radius


def _rank_limits(summaries: dict[str, dict[str, Any]]) -> dict[str, tuple[float, float, float]]:
    if {summary["model"] for summary in summaries.values()} != set(MODELS):
        raise ValueError("ranking needs every mandatory dependence model")
    points = {(summary["sample_size"], summary["effect"]) for summary in summaries.values()}
    if len(points) != 1:
        raise ValueError("ranking summaries must share a projection point")
    limits: dict[str, tuple[float, float, float]] = {}
    for name in CANDIDATE_NAMES:
        rates = []
        lowers = []
        uppers = []
        for summary in summaries.values():
            counts = summary["candidate_rejections"][name]
            runs = summary["outer_runs"]
            if len(counts) != 3 or any(not 0 <= count <= runs for count in counts):
                raise ValueError("power evidence needs all three patterns and valid counts")
            for count in counts:
                rates.append(count / runs)
                lower, upper = _wilson_95(count, runs)
                lowers.append(lower)
                uppers.append(upper)
        limits[name] = min(rates), min(lowers), min(uppers)
    return limits


def rank_point(summaries: dict[str, dict[str, Any]]) -> tuple[tuple[str, ...], bool]:
    """Rank worst-cell fractions; flag overlap of their 95% MC bounds."""
    limits = _rank_limits(summaries)
    order = tuple(
        sorted(
            CANDIDATE_NAMES,
            key=lambda name: (limits[name][0], CLUSTERS[name], -CANDIDATE_NAMES.index(name)),
            reverse=True,
        )
    )
    uncertain = any(
        limits[order[index]][1] <= limits[order[index + 1]][2] for index in range(len(order) - 1)
    )
    return order, uncertain


def _run_batch(
    cells: tuple[ProjectionCell, ...], *, outer_runs: int, workers: int, directory: Path
) -> dict[str, dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    with ProcessPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(_read_or_run, cell, outer_runs, INNER_DRAWS, directory): cell
            for cell in cells
        }
        for future in as_completed(futures):
            cell = futures[future]
            results[cell.scenario_id] = future.result()
            print(
                json.dumps(
                    {
                        "completed": len(results),
                        "total": len(cells),
                        "scenario_id": cell.scenario_id,
                        "outer_runs": outer_runs,
                    }
                ),
                flush=True,
            )
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    directory = args.output_dir.resolve()
    if directory.is_relative_to(ROOT.resolve()):
        parser.error("raw projection output must be outside the Git checkout")
    if not 1 <= args.workers <= 4:
        parser.error("projection workers must be between 1 and 4")
    directory.mkdir(parents=True, exist_ok=True)
    cells = build_cells()
    results = _run_batch(cells, outer_runs=INITIAL_OUTER, workers=args.workers, directory=directory)
    extensions: list[ProjectionCell] = []
    for size in (200, 430):
        for effect in EFFECTS:
            point_cells = tuple(
                cell for cell in cells if cell.sample_size == size and cell.effect == effect
            )
            _, uncertain = rank_point(
                {cell.scenario_id: results[cell.scenario_id] for cell in point_cells}
            )
            if uncertain:
                extensions.extend(point_cells)
    if extensions:
        extended = _run_batch(
            tuple(extensions), outer_runs=MAXIMUM_OUTER, workers=args.workers, directory=directory
        )
        for cell in extensions:
            if (
                extended[cell.scenario_id]["attempts"][:INITIAL_OUTER]
                != results[cell.scenario_id]["attempts"]
            ):
                raise ValueError(f"100k projection changed the 20k prefix: {cell.scenario_id}")
        results.update(extended)
    rankings: dict[str, dict[str, Any]] = {}
    for size in (200, 430):
        for effect in EFFECTS:
            point_cells = tuple(
                cell for cell in cells if cell.sample_size == size and cell.effect == effect
            )
            summaries = {cell.scenario_id: results[cell.scenario_id] for cell in point_cells}
            order, uncertain = rank_point(summaries)
            rankings[f"N{size}-d{effect}"] = {
                "order": order,
                "outer_runs": min(summary["outer_runs"] for summary in summaries.values()),
                "monte_carlo_overlap_at_cap": uncertain,
                "raw_worst_cell_limits": _rank_limits(summaries),
            }
    stable = len({tuple(row["order"]) for row in rankings.values()}) == 1
    complete = not any(row["monte_carlo_overlap_at_cap"] for row in rankings.values())
    report = {
        "status": "COMPLETE" if complete else "MONTE_CARLO_RANKING_UNRESOLVED",
        "rankings": rankings,
        "ranking_stable": stable,
        "freeze_430_eligible": stable and complete,
        "cells": {
            name: {key: value for key, value in payload.items() if key != "attempts"}
            for name, payload in results.items()
        },
    }
    _atomic_json(directory / "power-report.json", report)
    print(
        json.dumps(
            {
                "status": report["status"],
                "rankings": {key: row["order"] for key, row in rankings.items()},
                "freeze_430_eligible": report["freeze_430_eligible"],
            }
        )
    )


if __name__ == "__main__":
    main()

"""Diagnostic-only synthetic dependence comparison; never supplies a method audit."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from decimal import Decimal
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from qat.domain.backtester import swing_method_audit as audit  # noqa: E402
from qat.domain.backtester import swing_statistics as stats  # noqa: E402

NAMES = ("ema_pullback", "bull_flag", "double_bottom")


def interval(successes: int, trials: int) -> dict:
    z = 1.959963984540054
    p = successes / trials
    denominator = 1 + z * z / trials
    center = (p + z * z / (2 * trials)) / denominator
    half = z * math.sqrt(p * (1 - p) / trials + z * z / (4 * trials * trials)) / denominator
    return {
        "rejections": successes,
        "runs": trials,
        "rate": p,
        "wilson_two_sided_95": [max(0, center - half), min(1, center + half)],
    }


def run_cell(arguments: tuple) -> dict:
    persistence, null, method, outer, inner, seed = arguments[:6]
    conservative_ties = arguments[6] if len(arguments) > 6 else True
    scenario = audit.SyntheticScenario(
        f"diagnostic-persistence-{persistence}-{null}-{method}",
        "gaussian",
        36,
        8,
        max(3, persistence),
        null,
        Decimal("0.2"),
    )
    original_generator = audit._synthetic_months
    original_confidence = audit.wcr_s_pvalue
    original_family = audit.romano_wolf_stepdown
    if persistence == 1:

        def independent_generator(scenario, rng):
            # Constructor deliberately disallows one-month promotion scenarios.
            from types import SimpleNamespace

            diagnostic_scenario = SimpleNamespace(
                **{field: getattr(scenario, field) for field in scenario.__dataclass_fields__}
            )
            diagnostic_scenario.block_months = 1
            return original_generator(diagnostic_scenario, rng)

        audit._synthetic_months = independent_generator
    block = 1 if method == "month_wcr_s" else (3 if method == "quarter_wcr_s" else persistence)
    rows = []
    current = {}

    def transform(months, weights):
        groups = tuple(
            tuple(value for month in months[start : start + block] for value in month)
            for start in range(0, len(months), block)
        )
        # Coupled signs: same full pilot matrix, first sign in each block retained.
        signs = [row[::block] for row in weights]
        return groups, signs

    def confidence(months, *, weights):
        grouped, signs = transform(months, weights)
        value = stats.wcr_s_pvalue(grouped, weights=signs)
        if method == "block_wild" and conservative_ties:
            frame = stats._cluster_frame(grouped)
            observed = frame.mean / frame.standard_error
            bootstrap = stats._bootstrap_statistics(frame, np.asarray(signs), 0.0)
            exceed = (bootstrap >= observed) | np.isclose(
                bootstrap, observed, rtol=1e-12, atol=1e-12
            )
            value = Decimal(1 + int(np.count_nonzero(exceed))) / Decimal(len(signs) + 1)
        current[id(months)] = value
        return value

    def family(samples, *, weights):
        grouped = {name: transform(months, weights)[0] for name, months in samples.items()}
        signs = [row[::block] for row in weights]
        result = stats.romano_wolf_stepdown(grouped, weights=signs)
        if method == "block_wild" and conservative_ties:
            frames = {name: stats._cluster_frame(sample) for name, sample in grouped.items()}
            bootstrap = {
                name: stats._bootstrap_statistics(frame, np.asarray(signs), 0.0)
                for name, frame in frames.items()
            }
            previous = Decimal(0)
            adjusted = {}
            for index, name in enumerate(result.order):
                maximum = np.maximum.reduce([bootstrap[other] for other in result.order[index:]])
                observed = result.observed_statistics[name]
                exceed = (maximum >= observed) | np.isclose(
                    maximum, observed, rtol=1e-12, atol=1e-12
                )
                previous = max(
                    previous, Decimal(1 + int(np.count_nonzero(exceed))) / Decimal(len(signs) + 1)
                )
                adjusted[name] = previous
            result = stats.RomanoWolfResult(
                result.order, adjusted, result.observed_statistics, len(signs)
            )
        pvalues = [
            str(current.get(id(samples[name])) or confidence(samples[name], weights=weights))
            for name in NAMES
        ]
        rows.append(
            {
                "attempt": len(rows),
                "confidence_p": pvalues,
                "adjusted_family_p": [str(result.adjusted_p_values[name]) for name in NAMES],
            }
        )
        current.clear()
        return result

    # Process-local callback instrumentation: production files and declared method untouched.
    audit.wcr_s_pvalue = confidence
    audit.romano_wolf_stepdown = family
    started = time.perf_counter()
    try:
        result = audit.run_synthetic_pilot(
            scenario, outer_runs=outer, inner_draws=inner, seed=seed, diagnostic=True
        )
    finally:
        audit._synthetic_months = original_generator
        audit.wcr_s_pvalue = original_confidence
        audit.romano_wolf_stepdown = original_family
    seconds = time.perf_counter() - started
    if result.promotion_eligible:
        raise RuntimeError("diagnostic unexpectedly became promotion eligible")
    summary = {}
    for index, name in enumerate(NAMES):
        summary[name] = {
            "role": "size" if null[index] == "0" else "power",
            "confidence_0_025": interval(
                sum(Decimal(row["confidence_p"][index]) < Decimal("0.025") for row in rows), outer
            ),
            "adjusted_family_0_05": interval(
                sum(Decimal(row["adjusted_family_p"][index]) < Decimal("0.05") for row in rows),
                outer,
            ),
        }
    null_indices = [i for i, flag in enumerate(null) if flag == "0"]
    family_size = interval(
        sum(
            any(Decimal(row["adjusted_family_p"][i]) < Decimal("0.05") for i in null_indices)
            for row in rows
        ),
        outer,
    )
    return {
        "persistence_months": persistence,
        "null_configuration": null,
        "method": method,
        "clusters": 36 // block,
        "seed": seed,
        "seconds": seconds,
        "pilot_attempts_sha256": result.attempts_sha256,
        "retained_pvalues_sha256": hashlib.sha256(
            json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "family_false_positive": family_size,
        "patterns": summary,
        "attempts": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--outer-runs", type=int, default=600)
    parser.add_argument("--inner-draws", type=int, default=999)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--raw-kernel", action="store_true")
    args = parser.parse_args()
    cells = [
        (p, null, method, args.outer_runs, args.inner_draws, 20261004, not args.raw_kernel)
        for p in (1, 3, 6, 12)
        for null in ("000", "d00")
        for method in ("month_wcr_s", "quarter_wcr_s", "block_wild")
    ]
    started = time.perf_counter()
    results = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for result in pool.map(run_cell, cells):
            results.append(result)
            print(
                json.dumps(
                    {
                        key: result[key]
                        for key in ("persistence_months", "null_configuration", "method", "seconds")
                    }
                ),
                flush=True,
            )
    payload = {
        "diagnostic_only": True,
        "block_conservative_ties": not args.raw_kernel,
        "tie_rtol": "1e-12" if not args.raw_kernel else None,
        "tie_atol": "1e-12" if not args.raw_kernel else None,
        "promotion_eligible": False,
        "outer_runs": args.outer_runs,
        "inner_draws": args.inner_draws,
        "months": 36,
        "observations_per_month": 8,
        "delta_mme": "0.2",
        "family": "gaussian",
        "common_shock_coefficient": "0.35",
        "workers": args.workers,
        "wall_seconds": time.perf_counter() - started,
        "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "cells": results,
    }
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

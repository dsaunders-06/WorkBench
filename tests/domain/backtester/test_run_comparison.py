"""Comparing two runs, and refusing to when the comparison means nothing.

The guard is the point of this module. A rail that never bound in the baseline
had nothing for its removal to change, so the difference is SUPPRESSED rather
than printed as a zero beside a caveat - a zero gets quoted and a caveat does
not.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from qat.domain.backtester.manifest import build_manifest
from qat.domain.backtester.run_comparison import compare_runs

_DECISION_FIELDS = [
    "timestamp",
    "symbol",
    "approved",
    "final_shares",
    "stop_price",
    "reason",
    "inputs",
]


def _run(
    directory: Path,
    *,
    reasons: list[str],
    trades: list[tuple[str, float]],
    disabled: list[str] | None = None,
) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "risk_decisions.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=_DECISION_FIELDS)
        writer.writeheader()
        for reason in reasons:
            writer.writerow(
                {
                    "timestamp": "2026-07-31T15:00:00+00:00",
                    "symbol": "AAA",
                    "approved": "False",
                    "final_shares": "0.0",
                    "stop_price": "",
                    "reason": reason,
                    "inputs": json.dumps({"regime_scalar": 1.0}),
                }
            )
    with (directory / "closed_trades.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["symbol", "r_multiple"])
        writer.writeheader()
        for symbol, r in trades:
            writer.writerow({"symbol": symbol, "r_multiple": r})
    build_manifest(
        data_dir=directory,
        disabled=disabled or [],
        universe=["AAA"],
        starting_equity=100_000.0,
    ).write(directory / "manifest.json")


_SECTOR_REFUSAL = "Technology already holds $31,000, at or above the 30% sector cap"


def _flat(report: str) -> str:
    """The report with its line breaks collapsed.

    The report is WRAPPED for a terminal, so a phrase can straddle a newline -
    "100% of equity" arrives as "100% of\\nequity" and a substring assertion
    fails on formatting rather than on content. What matters is that the
    sentence is present, not where it folds.
    """
    return " ".join(report.split())


def test_an_unexercised_rail_suppresses_the_difference(tmp_path: Path):
    """The heart of the design. The ablated arm here is dramatically better, and
    none of that improvement may be reported, because the rail never bound in
    the baseline and so cannot be what caused it."""
    _run(tmp_path / "base", reasons=[], trades=[("AAA", 1.0)])
    _run(tmp_path / "abl", reasons=[], trades=[("AAA", 9.9)], disabled=["sector_cap"])

    report = compare_runs(tmp_path / "base", tmp_path / "abl", "sector_cap")

    assert "NOT EXERCISED" in report
    assert "measures nothing" in report
    assert "9.9" not in report, "a suppressed figure must not appear anywhere in the report"


def test_an_unobservable_rail_says_the_ledger_cannot_tell(tmp_path: Path):
    """Different from "it did not bind". The churn cap writes no audit row, so
    zero would be an assertion the record cannot support."""
    _run(tmp_path / "base", reasons=[], trades=[("AAA", 1.0)])
    _run(tmp_path / "abl", reasons=[], trades=[("AAA", 2.0)], disabled=["churn_cap"])

    report = compare_runs(tmp_path / "base", tmp_path / "abl", "churn_cap")

    assert "NOT OBSERVABLE" in report
    assert "cannot say" in _flat(report)
    assert "2.0" not in report


def test_an_exercised_rail_reports_the_difference(tmp_path: Path):
    _run(tmp_path / "base", reasons=[_SECTOR_REFUSAL, _SECTOR_REFUSAL], trades=[("AAA", 1.0)])
    _run(
        tmp_path / "abl",
        reasons=[],
        trades=[("AAA", 1.0), ("BBB", -1.0), ("CCC", 2.0)],
        disabled=["sector_cap"],
    )

    report = compare_runs(tmp_path / "base", tmp_path / "abl", "sector_cap")

    assert "NOT EXERCISED" not in report
    assert "bound 2 time(s)" in report
    assert "baseline" in report and "ablated" in report


def test_the_report_scopes_its_own_claim(tmp_path: Path):
    """The scoping the operator approved on 13 August, in the artefact rather
    than in a reader's memory."""
    _run(tmp_path / "base", reasons=[_SECTOR_REFUSAL], trades=[("AAA", 1.0)])
    _run(tmp_path / "abl", reasons=[], trades=[("AAA", 1.0)], disabled=["sector_cap"])

    report = compare_runs(tmp_path / "base", tmp_path / "abl", "sector_cap")

    assert "inside the harness" in _flat(report)
    assert "not what it costs the live book" in _flat(report)


def test_an_imperfect_rail_carries_its_caveat(tmp_path: Path):
    breach = "aggregate risk-at-stop 5.01% is at or above the 5.00% cap"
    _run(tmp_path / "base", reasons=[breach], trades=[("AAA", 1.0)])
    _run(tmp_path / "abl", reasons=[], trades=[("AAA", 1.0)], disabled=["aggregate_risk_cap"])

    report = compare_runs(tmp_path / "base", tmp_path / "abl", "aggregate_risk_cap")

    assert "100% of equity at risk" in _flat(report)


def test_a_rail_the_manifest_does_not_know_is_named_not_guessed(tmp_path: Path):
    _run(tmp_path / "base", reasons=[], trades=[])
    _run(tmp_path / "abl", reasons=[], trades=[])

    report = compare_runs(tmp_path / "base", tmp_path / "abl", "not_a_rail")

    assert "not a rail" in report.lower()


def test_the_ablated_arm_must_actually_have_the_rail_disabled(tmp_path: Path):
    """A comparison whose two arms are the same configuration measures noise.
    Cheap to get wrong by passing the wrong directory, and invisible in the
    output unless it is checked."""
    _run(tmp_path / "base", reasons=[_SECTOR_REFUSAL], trades=[("AAA", 1.0)])
    _run(tmp_path / "abl", reasons=[], trades=[("AAA", 2.0)], disabled=[])

    report = compare_runs(tmp_path / "base", tmp_path / "abl", "sector_cap")

    assert "STILL ENABLED" in report
    assert "2.0" not in report

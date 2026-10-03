"""Append-only Phase 2C evidence bundle contracts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from qat.domain.backtester.swing_artifacts import SwingArtifactRun, write_swing_artifacts
from qat.domain.backtester.swing_promotion import PromotionCase, evaluate_promotion
from qat.domain.backtester.swing_results import (
    LifecycleActionSeries,
    ReplayArm,
    RunStatus,
    SwingReplayResult,
)


def _run(*, tier: str = "engineering", created_at: datetime | None = None) -> SwingArtifactRun:
    empty = SwingReplayResult(
        status=RunStatus.VALID,
        arm=ReplayArm.COMBINED,
        decisions=(),
        position_events=LifecycleActionSeries(),
        fills=(),
        trades=(),
        signal_trades=(),
        equity=(),
        abstentions=(),
        ambiguities=(),
    )
    return SwingArtifactRun(
        evidence_tier=tier,
        dataset_manifest={
            "catalog_id": "fixture-catalog",
            "shard_ids": ["fixture-development"],
            "T0": "2020-01-01",
            "T64": "2020-03-31",
            "signal_reference_equity": Decimal("10000.00"),
        },
        replays={arm: replace(empty, arm=arm) for arm in ReplayArm},
        metrics={"combined": {"mean_r_order": Decimal("1.00"), "mean_r_fill": Decimal("1.1")}},
        promotion=evaluate_promotion(PromotionCase(evidence_tier=tier)),
        method_audit={"status": "METHOD_AUDIT_PENDING", "numeric_policy": "wcr-s-cv1-v2"},
        feasibility={"status": "PENDING"},
        reference_incidence={"status": "INCIDENCE_DATA_INSUFFICIENT"},
        sensitivities={"ambiguity_optimistic": {"delta_r": Decimal("0")}},
        created_at=created_at or datetime(2026, 10, 3, tzinfo=UTC),
    )


def test_existing_run_directory_is_never_overwritten(tmp_path: Path) -> None:
    run = _run()
    path = write_swing_artifacts(run, tmp_path)
    with pytest.raises(FileExistsError):
        write_swing_artifacts(run, tmp_path)
    assert path.exists()


def test_engineering_bundle_has_schema_checksums_and_warning(tmp_path: Path) -> None:
    path = write_swing_artifacts(_run(), tmp_path)
    expected = {
        "manifest.json",
        "decisions.jsonl",
        "fills.csv",
        "trades.csv",
        "equity.csv",
        "metrics.json",
        "promotion.json",
        "method_audit.json",
        "feasibility.json",
        "reference_incidence.json",
        "report.md",
        "SHA256SUMS",
    }
    assert {item.name for item in path.iterdir()} == expected
    report = (path / "report.md").read_text(encoding="utf-8")
    assert "SURVIVORSHIP-BIASED — NOT PROMOTION EVIDENCE" in report.splitlines()[:8]
    assert "R_order" in report and "R_fill" in report
    assert "EMA pullback" in report and "Combined portfolio" in report
    assert "PORTFOLIO_RISK_DESIGN_PENDING" in report
    manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["dataset"]["signal_reference_equity"] == "10000"
    assert manifest["run_id"] == path.name
    assert "holdout_authorized" not in manifest
    assert manifest["method_audit"]["numeric_policy"] == "wcr-s-cv1-v2"
    checksums = (path / "SHA256SUMS").read_text(encoding="utf-8").splitlines()
    assert len(checksums) == len(expected) - 1
    for line in checksums:
        digest, filename = line.split("  ", 1)
        assert digest == hashlib.sha256((path / filename).read_bytes()).hexdigest()
    promotion = json.loads((path / "promotion.json").read_text(encoding="utf-8"))
    assert promotion["status"] == "PORTFOLIO_RISK_DESIGN_PENDING"


def test_created_at_does_not_change_semantic_run_id(tmp_path: Path) -> None:
    first = write_swing_artifacts(_run(), tmp_path / "first")
    second = write_swing_artifacts(
        _run(created_at=datetime(2026, 10, 4, tzinfo=UTC)), tmp_path / "second"
    )
    assert first.name == second.name
    assert (first / "metrics.json").read_bytes() == (second / "metrics.json").read_bytes()


def test_nonfinite_payload_is_rejected_before_directory_publish(tmp_path: Path) -> None:
    run = replace(_run(), metrics={"combined": {"bad": float("nan")}})
    with pytest.raises(ValueError, match="non-finite"):
        write_swing_artifacts(run, tmp_path)
    assert not list(tmp_path.iterdir())

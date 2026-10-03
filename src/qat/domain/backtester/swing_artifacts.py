"""Deterministic, append-only Phase 2 swing evidence bundles."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import shutil
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any

from qat.domain.backtester.swing_promotion import PromotionVerdict
from qat.domain.backtester.swing_reference import PromotionStatus
from qat.domain.backtester.swing_results import (
    ReplayArm,
    SimulatedFill,
    SwingReplayResult,
    SwingTrade,
)

ARTIFACT_SCHEMA_VERSION = "phase-2c-swing-evidence-v2"
_ARMS = tuple(ReplayArm)


@dataclass(frozen=True, slots=True)
class SwingArtifactRun:
    evidence_tier: str
    dataset_manifest: Mapping[str, object]
    replays: Mapping[ReplayArm, SwingReplayResult]
    metrics: Mapping[str, object]
    promotion: PromotionVerdict
    method_audit: Mapping[str, object]
    feasibility: Mapping[str, object]
    reference_incidence: Mapping[str, object]
    sensitivities: Mapping[str, object]
    created_at: datetime


def _canonical_decimal(value: Decimal) -> str:
    if not value.is_finite():
        raise ValueError("non-finite Decimal in swing artifact")
    if value.is_zero():
        return "0"
    return format(value.normalize(), "f")


def _plain(value: object) -> Any:
    if isinstance(value, Decimal):
        return _canonical_decimal(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: _plain(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        return {str(_plain(key)): _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("non-finite float in swing artifact")
        return value
    if value is None or isinstance(value, (str, int, bool)):
        return value
    raise TypeError(f"unsupported swing artifact value: {type(value).__name__}")


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(_plain(value), sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode("utf-8")


def _csv_bytes(rows: Sequence[Mapping[str, object]], columns: tuple[str, ...]) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        serialized: dict[str, object] = {}
        for column in columns:
            item = _plain(row.get(column))
            serialized[column] = (
                json.dumps(item, sort_keys=True, separators=(",", ":"), allow_nan=False)
                if isinstance(item, (list, dict))
                else item
            )
        writer.writerow(serialized)
    return buffer.getvalue().encode("utf-8")


def _rows(run: SwingArtifactRun, kind: str) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    for arm in _ARMS:
        replay = run.replays[arm]
        for item in getattr(replay, kind):
            row = {field.name: getattr(item, field.name) for field in fields(item)}
            row["arm"] = arm.value
            if isinstance(item, SwingTrade):
                row["entry_fill_event_ids"] = tuple(
                    fill.event_id
                    for fill in replay.fills
                    if fill.symbol == item.symbol
                    and fill.session == item.entry_session
                    and fill.side == "buy"
                )
                row["exit_fill_event_ids"] = tuple(
                    fill.event_id
                    for fill in replay.fills
                    if fill.symbol == item.symbol
                    and fill.session == item.exit_session
                    and fill.side == "sell"
                )
            output.append(row)
    return output


def _overlap_suppressed(replay: SwingReplayResult) -> int:
    return sum(not trade.edge_sample_eligible for trade in replay.signal_trades) + sum(
        rule.code == "OVERLAPPING_EVENT" for rule in replay.abstentions
    )


def _report(run: SwingArtifactRun, run_id: str) -> bytes:
    lines = ["# Authoritative swing Phase 2C engineering evidence", ""]
    if run.evidence_tier != "promotion_point_in_time":
        lines.extend(["SURVIVORSHIP-BIASED — NOT PROMOTION EVIDENCE", ""])
    lines.extend(
        [
            f"Run ID: `{run_id}`",
            f"Evidence tier: `{run.evidence_tier}`",
            f"Catalog: `{run.dataset_manifest.get('catalog_id', 'unavailable')}`",
            f"Period: {run.dataset_manifest.get('T0', 'unavailable')} through "
            f"{run.dataset_manifest.get('T64', 'unavailable')}",
            f"Verdict: **{run.promotion.status.value}**",
            "",
            "## Signal-level edge (R_order primary; R_fill diagnostic)",
            "",
        ]
    )
    labels = {
        ReplayArm.EMA_PULLBACK: "EMA pullback",
        ReplayArm.BULL_FLAG: "Bull flag",
        ReplayArm.DOUBLE_BOTTOM: "Double bottom",
        ReplayArm.COMBINED: "Combined portfolio",
    }
    for arm in _ARMS:
        replay = run.replays[arm]
        eligible = sum(trade.edge_sample_eligible for trade in replay.signal_trades)
        suppressed = _overlap_suppressed(replay)
        lines.extend(
            [
                f"### {labels[arm]}",
                f"Replay status: {replay.status.value}; decisions: {len(replay.decisions)}; "
                f"fills: {len(replay.fills)}; trades: {len(replay.trades)}; "
                f"eligible signal trades: {eligible}; "
                f"overlap-suppressed: {suppressed}; "
                f"ambiguities: {len(replay.ambiguities)}.",
                "Abstention codes: "
                + ", ".join(sorted({rule.code for rule in replay.abstentions})),
                "",
            ]
        )
    lines.extend(
        [
            "## Combined portfolio, risk, and limitations",
            "",
            "The uncapped portfolio is a concentration and gap-risk stress case, "
            "not a deployable forecast. Phase 4 risk policy and promotion controls remain pending.",
            "",
            "## Metrics and non-promotional sensitivities",
            "",
            "```json",
            json.dumps(
                _plain({"metrics": run.metrics, "sensitivities": run.sensitivities}),
                indent=2,
                sort_keys=True,
            ),
            "```",
            "",
            "## Method, frequency, and reference incidence",
            "",
            "```json",
            json.dumps(
                _plain(
                    {
                        "method_audit": run.method_audit,
                        "feasibility": run.feasibility,
                        "reference_incidence": run.reference_incidence,
                    }
                ),
                indent=2,
                sort_keys=True,
            ),
            "```",
            "",
            f"Operator action: {run.promotion.recommended_operator_action}",
            "",
        ]
    )
    return "\n".join(lines).encode("utf-8")


def write_swing_artifacts(run: SwingArtifactRun, output_root: Path) -> Path:
    """Publish one complete bundle under a semantic ID, never replacing an earlier run."""
    if set(run.replays) != set(_ARMS):
        raise ValueError("swing artifact requires all four replay arms")
    if any(replay.arm is not arm for arm, replay in run.replays.items()):
        raise ValueError("replay arm key does not match result")
    if run.promotion.status is PromotionStatus.PASS:
        raise ValueError("Phase 2 artifact cannot claim promotion PASS")
    semantic = {
        "schema": ARTIFACT_SCHEMA_VERSION,
        "evidence_tier": run.evidence_tier,
        "dataset": run.dataset_manifest,
        "replays": {arm.value: run.replays[arm] for arm in _ARMS},
        "metrics": run.metrics,
        "promotion": run.promotion,
        "method_audit": run.method_audit,
        "feasibility": run.feasibility,
        "reference_incidence": run.reference_incidence,
        "sensitivities": run.sensitivities,
    }
    run_id = hashlib.sha256(_json_bytes(semantic)).hexdigest()[:32]
    output_root.mkdir(parents=True, exist_ok=True)
    destination = output_root / run_id
    if destination.exists():
        raise FileExistsError(destination)
    manifest = {
        "schema": ARTIFACT_SCHEMA_VERSION,
        "run_id": run_id,
        "evidence_tier": run.evidence_tier,
        "dataset": run.dataset_manifest,
        "packaging": {"created_at": run.created_at},
        "metrics": run.metrics,
        "method_audit": run.method_audit,
        "feasibility": run.feasibility,
        "reference_incidence": run.reference_incidence,
        "sensitivities": run.sensitivities,
        "promotion_status": run.promotion.status,
        "replay_status": {arm.value: run.replays[arm].status for arm in _ARMS},
        "signal_counts": {
            arm.value: {
                "eligible": sum(t.edge_sample_eligible for t in run.replays[arm].signal_trades),
                "overlap_suppressed": _overlap_suppressed(run.replays[arm]),
            }
            for arm in _ARMS
        },
    }
    fill_columns = ("arm",) + tuple(field.name for field in fields(SimulatedFill))
    trade_columns = (
        ("arm",)
        + tuple(field.name for field in fields(SwingTrade))
        + (
            "entry_fill_event_ids",
            "exit_fill_event_ids",
        )
    )
    equity_rows = _rows(run, "equity")
    equity_columns = (
        "arm",
        "session",
        "equity",
        "cash",
        "position_value",
        "dividend_receivables",
        "stale_marks",
    )
    decision_lines = [
        _json_bytes({"arm": arm.value, "decision": decision})
        for arm in _ARMS
        for decision in run.replays[arm].decisions
    ]
    payloads = {
        "manifest.json": _json_bytes(manifest),
        "decisions.jsonl": b"".join(decision_lines),
        "fills.csv": _csv_bytes(_rows(run, "fills"), fill_columns),
        "trades.csv": _csv_bytes(_rows(run, "trades"), trade_columns),
        "equity.csv": _csv_bytes(equity_rows, equity_columns),
        "metrics.json": _json_bytes({"metrics": run.metrics, "sensitivities": run.sensitivities}),
        "promotion.json": _json_bytes(run.promotion),
        "method_audit.json": _json_bytes(run.method_audit),
        "feasibility.json": _json_bytes(run.feasibility),
        "reference_incidence.json": _json_bytes(run.reference_incidence),
        "report.md": _report(run, run_id),
    }
    temporary = Path(tempfile.mkdtemp(prefix=".swing-evidence-", dir=output_root))
    try:
        for name, content in payloads.items():
            (temporary / name).write_bytes(content)
        checksums = "".join(
            f"{hashlib.sha256(content).hexdigest()}  {name}\n"
            for name, content in sorted(payloads.items())
        )
        (temporary / "SHA256SUMS").write_text(checksums, encoding="utf-8", newline="\n")
        if destination.exists():
            raise FileExistsError(destination)
        temporary.rename(destination)
    finally:
        if temporary.exists() and temporary.parent.resolve() == output_root.resolve():
            shutil.rmtree(temporary)
    return destination

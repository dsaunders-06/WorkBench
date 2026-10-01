"""Fail-closed application of an evidence-bound historical ledger correction."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import shutil
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from qat.domain.performance.trades import ClosedTrade, audit_closed_trades


class CorrectionRefused(ValueError):
    """The evidence or filesystem state is not safe for this correction."""


@dataclass(frozen=True)
class CorrectionPlan:
    proposal_path: Path
    statement_path: Path
    ledger_path: Path
    correction_id: str
    proposal_sha256: str
    statement_sha256: str
    ledger_sha256: str
    fieldnames: tuple[str, ...]
    rows: tuple[dict[str, str], ...]
    target_index: int
    original_row: dict[str, str]
    corrected_row: dict[str, object]
    provenance: dict[str, str]


@dataclass(frozen=True)
class ApplyResult:
    backup_path: Path
    journal_path: Path
    after_sha256: str


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _decimal(value: Any, label: str) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise CorrectionRefused(f"{label} is not a decimal number") from exc


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)


def _rounded(value: Decimal, places: str) -> Decimal:
    return value.quantize(Decimal(places), rounding=ROUND_HALF_EVEN)


def _load_proposal(path: Path) -> dict[str, Any]:
    try:
        proposal = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CorrectionRefused(f"proposal cannot be read: {exc}") from exc
    if not isinstance(proposal, dict):
        raise CorrectionRefused("proposal must be a JSON object")
    if proposal.get("status") != "PROPOSED_ONLY_NOT_APPLIED":
        raise CorrectionRefused("proposal status is not PROPOSED_ONLY_NOT_APPLIED")
    return proposal


def _require_hash(path: Path, expected: Any, label: str) -> str:
    actual = _sha256(path)
    if not isinstance(expected, str) or actual.lower() != expected.lower():
        raise CorrectionRefused(f"{label} SHA-256 mismatch: expected {expected!r}, got {actual}")
    return actual


def _read_ledger(path: Path) -> tuple[tuple[str, ...], tuple[dict[str, str], ...]]:
    try:
        with path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None:
                raise CorrectionRefused("ledger has no CSV header")
            rows = tuple(dict(row) for row in reader)
    except (OSError, UnicodeError, csv.Error) as exc:
        raise CorrectionRefused(f"ledger cannot be read: {exc}") from exc
    return tuple(reader.fieldnames), rows


def _validate_broker_arithmetic(values: dict[str, Any]) -> None:
    quantity = _decimal(values.get("quantity"), "broker quantity")
    entry = _decimal(values.get("entry_price"), "broker entry price")
    exit_price = _decimal(values.get("exit_price"), "broker exit price")
    entry_cost = _decimal(values.get("entry_commission"), "broker entry commission")
    exit_cost = _decimal(values.get("exit_commission"), "broker exit commission")
    net = _decimal(values.get("realised_net_pnl"), "broker realised net P&L")
    if quantity <= 0 or entry_cost < 0 or exit_cost < 0:
        raise CorrectionRefused("broker quantity and commissions are internally inconsistent")
    price_gross = _money((exit_price - entry) * quantity)
    stated_gross = _money(net + entry_cost + exit_cost)
    if price_gross != stated_gross:
        raise CorrectionRefused(
            f"broker values are internally inconsistent: prices imply {price_gross}, "
            f"but net plus commissions implies {stated_gross}"
        )


def _decimal_derived_fields(broker: dict[str, Any], stop_price: str) -> dict[str, float]:
    """Recompute quantity-dependent stored columns without binary float arithmetic."""
    quantity = _rounded(_decimal(broker.get("quantity"), "broker quantity"), "0.000001")
    entry = _rounded(_decimal(broker.get("entry_price"), "broker entry price"), "0.00000001")
    exit_price = _rounded(_decimal(broker.get("exit_price"), "broker exit price"), "0.00000001")
    stop = _rounded(_decimal(stop_price, "ledger stop price"), "0.00000001")
    entry_cost = _money(_decimal(broker.get("entry_commission"), "broker entry commission"))
    exit_cost = _money(_decimal(broker.get("exit_commission"), "broker exit commission"))
    gross = _money((exit_price - entry) * quantity)
    net = _money(gross - entry_cost - exit_cost)
    risk_per_share = _rounded(entry - stop, "0.00000001")
    if entry <= 0 or risk_per_share <= 0:
        raise CorrectionRefused("corrected entry and stop cannot produce valid risk metrics")
    return {
        "quantity": float(quantity),
        "entry_price": float(entry),
        "exit_price": float(exit_price),
        "entry_cost": float(entry_cost),
        "exit_cost": float(exit_cost),
        "gross_pnl": float(gross),
        "net_pnl": float(net),
        "pnl_pct": float(_rounded(net / (entry * quantity), "0.000001")),
        "risk_per_share": float(risk_per_share),
        "r_multiple": float(_rounded(net / (risk_per_share * quantity), "0.0001")),
        "gross_r_multiple": float(_rounded((exit_price - entry) / risk_per_share, "0.0001")),
    }


def prepare_correction(
    proposal_path: Path,
    statement_path: Path,
    ledger_path: Path,
    expected_proposal_sha256: str,
) -> CorrectionPlan:
    """Validate immutable evidence and build, but do not write, one correction."""
    proposal_path = Path(proposal_path)
    statement_path = Path(statement_path)
    ledger_path = Path(ledger_path)
    proposal_sha = _require_hash(proposal_path, expected_proposal_sha256, "approved proposal")
    proposal = _load_proposal(proposal_path)
    statement_sha = _require_hash(statement_path, proposal.get("statement_sha256"), "statement")
    ledger_sha = _require_hash(ledger_path, proposal.get("ledger_sha256"), "ledger")

    fieldnames, rows = _read_ledger(ledger_path)
    original = proposal.get("original_ledger_row")
    match = proposal.get("match")
    broker = proposal.get("broker_statement_values")
    if not isinstance(original, dict) or not all(isinstance(v, str) for v in original.values()):
        raise CorrectionRefused("proposal original_ledger_row is invalid")
    if not isinstance(match, dict) or not isinstance(broker, dict):
        raise CorrectionRefused("proposal match or broker values are invalid")
    if any(key not in fieldnames for key in original):
        raise CorrectionRefused("proposal original row names a column absent from the ledger")

    exact = [
        index for index, row in enumerate(rows) if all(row.get(k) == v for k, v in original.items())
    ]
    if len(exact) != 1:
        raise CorrectionRefused(f"expected exactly one original row, found {len(exact)}")
    target_index = exact[0]
    target = rows[target_index]
    identity_matches = [
        row
        for row in rows
        if row.get("symbol") == match.get("symbol")
        and row.get("order_id") == match.get("ledger_order_id")
        and row.get("opened_at") == match.get("opened_at")
    ]
    if len(identity_matches) != 1 or identity_matches[0] != target:
        raise CorrectionRefused("proposal identity does not uniquely select the exact original row")

    _validate_broker_arithmetic(broker)
    trade = ClosedTrade.from_row(target)
    if trade is None:
        raise CorrectionRefused("the selected ledger row cannot be parsed by the application")
    corrected_trade = replace(
        trade,
        quantity=float(_decimal(broker.get("quantity"), "broker quantity")),
        entry_price=float(_decimal(broker.get("entry_price"), "broker entry price")),
        exit_price=float(_decimal(broker.get("exit_price"), "broker exit price")),
        entry_cost=float(_decimal(broker.get("entry_commission"), "broker entry commission")),
        exit_cost=float(_decimal(broker.get("exit_commission"), "broker exit commission")),
        exit_reason=None,
    )
    corrected = corrected_trade.as_row()
    corrected.update(_decimal_derived_fields(broker, target["stop_price"]))
    expected_net = _money(_decimal(broker.get("realised_net_pnl"), "broker realised net P&L"))
    if _money(_decimal(corrected["net_pnl"], "recalculated net P&L")) != expected_net:
        raise CorrectionRefused("recalculated row does not reproduce broker realised net P&L")

    correction_id = f"tne-20260903-{proposal_sha[:12]}"
    return CorrectionPlan(
        proposal_path=proposal_path,
        statement_path=statement_path,
        ledger_path=ledger_path,
        correction_id=correction_id,
        proposal_sha256=proposal_sha,
        statement_sha256=statement_sha,
        ledger_sha256=ledger_sha,
        fieldnames=fieldnames,
        rows=rows,
        target_index=target_index,
        original_row=dict(original),
        corrected_row=corrected,
        provenance={
            "strategy": "preserved from original ledger; not statement-verified",
            "exit_reason": "cleared because the statement does not verify it",
            "broker_values": "quantity, prices, commissions, and realised net P&L",
        },
    )


def _candidate_bytes(plan: CorrectionPlan) -> bytes:
    rows = [dict(row) for row in plan.rows]
    rows[plan.target_index] = {
        field: str(plan.corrected_row.get(field, "")) for field in plan.fieldnames
    }
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=list(plan.fieldnames), lineterminator="\r\n")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8")


def _write_synced(path: Path, content: bytes, *, exclusive: bool = False) -> None:
    mode = "xb" if exclusive else "wb"
    with path.open(mode) as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())


def apply_correction(plan: CorrectionPlan) -> ApplyResult:
    """Atomically apply a previously validated plan, with backup and journal."""
    ledger = plan.ledger_path
    backup = ledger.with_name(f"{ledger.name}.bak-pre-{plan.correction_id}")
    journal = ledger.with_name(f"{ledger.name}.correction-{plan.correction_id}.json")
    if backup.exists() or journal.exists():
        raise CorrectionRefused("correction backup or journal already exists; refusing repetition")
    if _sha256(ledger) != plan.ledger_sha256:
        raise CorrectionRefused("ledger changed after validation")

    candidate = _candidate_bytes(plan)
    candidate_sha = hashlib.sha256(candidate).hexdigest()
    ledger_tmp = ledger.with_name(f"{ledger.name}.tmp-{plan.correction_id}")
    journal_tmp = journal.with_name(f"{journal.name}.tmp")
    rollback_tmp = ledger.with_name(f"{ledger.name}.rollback-{plan.correction_id}")
    for path in (ledger_tmp, journal_tmp, rollback_tmp):
        if path.exists():
            raise CorrectionRefused(f"staging path already exists: {path.name}")

    try:
        _write_synced(ledger_tmp, candidate, exclusive=True)
        findings = audit_closed_trades(ledger_tmp)
        if findings:
            raise CorrectionRefused("candidate ledger failed audit: " + "; ".join(findings))
        source = ledger.read_bytes()
        if hashlib.sha256(source).hexdigest() != plan.ledger_sha256:
            raise CorrectionRefused("ledger changed before backup")
        _write_synced(backup, source, exclusive=True)
        if backup.read_bytes() != source:
            raise CorrectionRefused("backup is not byte-for-byte identical")

        journal_record = {
            "correction_id": plan.correction_id,
            "applied_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "proposal_sha256": plan.proposal_sha256,
            "statement_sha256": plan.statement_sha256,
            "before_sha256": plan.ledger_sha256,
            "after_sha256": candidate_sha,
            "target": {
                "symbol": plan.original_row["symbol"],
                "order_id": plan.original_row["order_id"],
                "opened_at": plan.original_row["opened_at"],
            },
            "before": plan.original_row,
            "after": plan.corrected_row,
            "provenance": plan.provenance,
        }
        _write_synced(
            journal_tmp,
            (json.dumps(journal_record, indent=2, sort_keys=True) + "\n").encode("utf-8"),
            exclusive=True,
        )
        os.replace(ledger_tmp, ledger)
        if _sha256(ledger) != candidate_sha or audit_closed_trades(ledger):
            raise OSError("post-write ledger verification failed")
        try:
            os.replace(journal_tmp, journal)
        except OSError:
            shutil.copyfile(backup, rollback_tmp)
            os.replace(rollback_tmp, ledger)
            if _sha256(ledger) == plan.ledger_sha256:
                backup.unlink(missing_ok=True)
            raise
    except CorrectionRefused:
        ledger_tmp.unlink(missing_ok=True)
        journal_tmp.unlink(missing_ok=True)
        if _sha256(ledger) == plan.ledger_sha256:
            backup.unlink(missing_ok=True)
        raise
    except OSError as exc:
        ledger_tmp.unlink(missing_ok=True)
        journal_tmp.unlink(missing_ok=True)
        rollback_tmp.unlink(missing_ok=True)
        if backup.exists() and ledger.exists() and _sha256(ledger) != plan.ledger_sha256:
            try:
                shutil.copyfile(backup, rollback_tmp)
                os.replace(rollback_tmp, ledger)
            except OSError as restore_exc:
                raise CorrectionRefused(
                    f"filesystem write failed ({exc}); automatic restore also failed "
                    f"({restore_exc}). Restore {ledger.name} from {backup.name}"
                ) from restore_exc
        if ledger.exists() and _sha256(ledger) == plan.ledger_sha256:
            backup.unlink(missing_ok=True)
        raise CorrectionRefused(f"filesystem write failed: {exc}") from exc

    return ApplyResult(backup_path=backup, journal_path=journal, after_sha256=candidate_sha)


def write_candidate_for_audit(plan: CorrectionPlan, path: Path) -> None:
    """Write a candidate only to caller-selected scratch space for a dry-run audit."""
    path.write_bytes(_candidate_bytes(plan))

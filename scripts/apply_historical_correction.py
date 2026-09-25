"""Validate and optionally apply one evidence-bound historical ledger correction.

The default is a read-only dry run. ``--apply`` is deliberately explicit and
must only be used after the operator has reviewed the dry-run result.
"""

from __future__ import annotations

import argparse
import os
import subprocess  # nosec B404 - fixed absolute executable and argv, shell disabled
import tempfile
from pathlib import Path

from qat.domain.performance.historical_correction import (
    CorrectionRefused,
    apply_correction,
    prepare_correction,
    write_candidate_for_audit,
)
from qat.domain.performance.trades import audit_closed_trades

APPROVED_PROPOSAL_SHA256 = "58aaae8c02c81efe61f9a0e3c0b949504be73a49d5f34bda0fe54dada1f54ccc"


def _app_is_running() -> bool:
    system_root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    tasklist = system_root / "System32" / "tasklist.exe"
    if not tasklist.is_file():
        print(f"REFUSING: cannot find {tasklist} to prove the app is stopped.")
        return True
    try:
        result = subprocess.run(  # nosec B603 - fixed absolute path and fixed argv
            [str(tasklist), "/FI", "IMAGENAME eq QuantAdvisoryTerminal.exe"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"REFUSING: cannot determine whether the app is running ({exc}).")
        return True
    if result.returncode != 0:
        print(f"REFUSING: tasklist failed with exit {result.returncode}.")
        return True
    return "QuantAdvisoryTerminal.exe" in (result.stdout or "")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--proposal", required=True, type=Path)
    parser.add_argument("--statement", required=True, type=Path)
    parser.add_argument("--ledger", required=True, type=Path)
    parser.add_argument("--apply", action="store_true", help="write the correction")
    parser.add_argument(
        "--confirm-correction-id",
        help="required with --apply; copy the correction id from the reviewed dry run",
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        plan = prepare_correction(
            args.proposal,
            args.statement,
            args.ledger,
            expected_proposal_sha256=APPROVED_PROPOSAL_SHA256,
        )
    except (CorrectionRefused, OSError) as exc:
        print(f"REFUSING: {exc}")
        return 1

    before = plan.original_row
    after = plan.corrected_row
    print(f"correction : {plan.correction_id}")
    print(f"statement  : SHA-256 {plan.statement_sha256}")
    print(f"proposal   : SHA-256 {plan.proposal_sha256}")
    print(f"ledger     : SHA-256 {plan.ledger_sha256}")
    print(f"target     : {before['symbol']} order {before['order_id']}")
    print(f"quantity   : {before['quantity']} -> {after['quantity']}")
    print(f"net P&L    : {before['net_pnl']} -> {after['net_pnl']}")
    print(f"exit reason: {before['exit_reason']!r} -> {after['exit_reason']!r}")
    print(f"strategy   : {after['strategy']!r} ({plan.provenance['strategy']})")

    with tempfile.TemporaryDirectory(prefix="qat-historical-correction-", dir=Path.cwd()) as tmp:
        candidate = Path(tmp) / "closed_trades.csv"
        write_candidate_for_audit(plan, candidate)
        findings = audit_closed_trades(candidate)
    if findings:
        print(f"REFUSING: candidate ledger failed audit with {len(findings)} finding(s):")
        for finding in findings:
            print(f"  {finding}")
        return 1
    print("audit      : clean")

    if not args.apply:
        print("DRY RUN - validated in scratch space; nothing written.")
        return 0
    if args.confirm_correction_id != plan.correction_id:
        print(
            "REFUSING: --apply requires --confirm-correction-id "
            f"{plan.correction_id} from the reviewed dry run."
        )
        return 1
    if _app_is_running():
        print("REFUSING: QuantAdvisoryTerminal.exe may be running. Close it before applying.")
        return 1
    try:
        result = apply_correction(plan)
    except CorrectionRefused as exc:
        print(f"REFUSING: {exc}")
        return 1
    print(f"APPLIED    : SHA-256 {result.after_sha256}")
    print(f"backup     : {result.backup_path}")
    print(f"journal    : {result.journal_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

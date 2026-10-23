"""Append one audited ASX session to the private OPERATIONAL authority ledger.

No broker client, OMS, or order path is imported. The four source files remain
fixed; --apply writes one hash-chained line only after a reviewed daily audit.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import date, datetime, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from qat.domain.market_calendar import is_trading_day  # noqa: E402
from qat.operational.authority_attestations import (  # noqa: E402
    AUTHORITY_FILES,
    SYDNEY,
    AuthorityAttestations,
    base_validity,
)
from qat.operational.history import (  # noqa: E402
    CalendarLedger,
    load_actions,
    load_calendar,
    load_halts,
    load_membership,
    require_operational_file,
)


def validate_inputs(
    session: date,
    root: Path,
    authorities: Path,
    approved_hashes: dict[str, str],
    audit_file: Path,
    audit_sha256: str,
    now: datetime,
) -> tuple[AuthorityAttestations, CalendarLedger, date]:
    """Validate the fixed files and complete daily audit without a write."""
    local = now.astimezone(SYDNEY)
    if (
        now.tzinfo is None
        or local.date() != session
        or local.time() < time(16, 20)
        or not is_trading_day("ASX", session)
    ):
        raise ValueError("attestation requires today's completed ASX session after 16:20")
    ledger = AuthorityAttestations(root / "authority_attestations.jsonl")
    require_operational_file(ledger.path)
    if not authorities.is_dir() or {path.name for path in authorities.iterdir()} != set(
        AUTHORITY_FILES
    ):
        raise ValueError("exactly four fixed authority files are required")
    if set(approved_hashes) != set(AUTHORITY_FILES):
        raise ValueError("exactly four DS-approved hashes are required")
    for name in AUTHORITY_FILES:
        path = authorities / name
        if not path.is_file() or path.is_symlink() or path.is_junction():
            raise ValueError(f"{name}: authority is unavailable or linked")
        if hashlib.sha256(path.read_bytes()).hexdigest() != approved_hashes[name]:
            raise ValueError(f"{name}: file differs from DS-approved SHA-256")
    calendar = load_calendar(authorities / "calendar.json")
    membership = load_membership(authorities / "membership.json")
    halts = load_halts(authorities / "halts.jsonl")
    actions = load_actions(authorities / "actions.json")
    if any(
        item.fixture or item.valid_through is None
        for item in (calendar, membership, halts, actions)
    ):
        raise ValueError("attestation requires real dated authorities")
    calendar.next_open(session)
    if membership.effective_from > session:
        raise ValueError("membership has not taken effect")
    if (
        not audit_file.is_file()
        or hashlib.sha256(audit_file.read_bytes()).hexdigest() != audit_sha256
    ):
        raise ValueError("daily audit evidence differs from its reviewed SHA-256")
    base = base_validity(
        calendar.valid_through,
        membership.valid_through,
        halts.valid_through,
        actions.valid_through,
    )
    if session <= base:
        raise ValueError("fixed authority files already cover this session")
    return ledger, calendar, base


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", type=date.fromisoformat, required=True)
    parser.add_argument("--operational-root", type=Path, required=True)
    parser.add_argument("--authorities-dir", type=Path, required=True)
    parser.add_argument("--audit-file", type=Path, required=True)
    parser.add_argument("--audit-sha256", required=True)
    parser.add_argument("--operator", required=True)
    for name in AUTHORITY_FILES:
        parser.add_argument(f"--{name.replace('.', '-')}-sha256", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    hashes = {
        name: getattr(args, name.replace(".", "_").replace("-", "_") + "_sha256")
        for name in AUTHORITY_FILES
    }
    now = datetime.now(SYDNEY)
    ledger, calendar, base = validate_inputs(
        args.session,
        args.operational_root,
        args.authorities_dir,
        hashes,
        args.audit_file,
        args.audit_sha256,
        now,
    )
    if not args.apply:
        print(
            json.dumps({"session": args.session.isoformat(), "result": "dry_run", "hashes": hashes})
        )
        return 0
    record = ledger.append(
        args.session,
        hashes,
        args.audit_file,
        operator=args.operator,
        recorded_at=now,
        calendar=calendar,
        base_valid_through=base,
    )
    ledger.require_current(args.session, hashes, calendar, base)
    print(
        json.dumps({"session": args.session.isoformat(), "attestation_sha256": record.content_hash})
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

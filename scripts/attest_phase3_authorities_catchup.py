"""Dry-run/apply one DS-pinned retrospective range; never rewrite old evidence."""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime
from pathlib import Path

from attest_phase3_authorities import validate_inputs

from qat.operational.authority_attestations import AUTHORITY_FILES, SYDNEY, AuthorityAttestations
from qat.operational.continuity import add_continuity_arguments, evidence_from_settings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--first-session", type=date.fromisoformat, required=True)
    parser.add_argument("--last-session", type=date.fromisoformat, required=True)
    parser.add_argument("--operational-root", type=Path, required=True)
    parser.add_argument("--authorities-dir", type=Path, required=True)
    parser.add_argument("--audit-file", type=Path, required=True)
    parser.add_argument("--audit-sha256", required=True)
    for name in AUTHORITY_FILES:
        parser.add_argument(f"--{name.replace('.', '-')}-sha256", required=True)
    add_continuity_arguments(parser)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    args.phase3_catchup_audit_file = str(args.audit_file)
    evidence = evidence_from_settings(args)
    if evidence is None:
        raise ValueError("independently pinned DS catch-up approval is required")
    hashes = {name: getattr(args, name.replace(".", "_") + "_sha256") for name in AUTHORITY_FILES}
    now = datetime.now(SYDNEY)
    ledger, calendar, base = validate_inputs(
        args.last_session,
        args.operational_root,
        args.authorities_dir,
        hashes,
        args.audit_file,
        args.audit_sha256,
        now,
        evidence=evidence,
        catch_up=True,
    )
    record = ledger.validate_catchup(
        args.first_session,
        args.last_session,
        hashes,
        recorded_at=now,
        calendar=calendar,
        base_valid_through=base,
    )
    if not args.apply:
        print(
            json.dumps(
                {
                    "result": "dry_run",
                    "content_hash": record.content_hash,
                    "first_session": str(args.first_session),
                    "last_session": str(args.last_session),
                }
            )
        )
        return 0
    record = ledger.append_catchup(
        args.first_session,
        args.last_session,
        hashes,
        recorded_at=now,
        calendar=calendar,
        base_valid_through=base,
    )
    fresh = AuthorityAttestations(ledger.path, evidence=evidence)
    fresh.require_current(args.last_session, hashes, calendar, base, verify_evidence=True)
    print(json.dumps({"result": "applied", "content_hash": record.content_hash}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

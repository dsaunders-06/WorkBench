"""Review one material shadow-bar revision in an outside-Git OPERATIONAL store.

The default is a read-only preview. Only --apply appends DS's decision to the
audit trail and, when selected, appends the revised bar as an accepted version.
This script has no broker, order, or QAT application surface.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from qat.operational.history import SYDNEY, HistoryStore  # noqa: E402


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--operational-root", type=Path, required=True)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--session", type=date.fromisoformat, required=True)
    parser.add_argument("--decision", choices=("accept_revised", "keep_original"), required=True)
    parser.add_argument("--expected-revision-hash", required=True)
    parser.add_argument("--operator", choices=("DS",), required=True)
    parser.add_argument("--reason", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    if (
        not args.operational_root.is_dir()
        or not (args.operational_root / "history.sqlite3").is_file()
    ):
        raise ValueError("existing OPERATIONAL history store is required")
    repository = Path(__file__).resolve().parents[1]
    store = HistoryStore(args.operational_root, repository_root=repository, protected_roots=())
    if not store.shadow_revision_pending((args.symbol,), sessions=(args.session,)):
        raise ValueError("no pending revision for symbol and session")
    material = [
        event
        for line in store.audit_bytes().splitlines()
        if (event := json.loads(line)).get("kind") == "shadow_bar_revision"
        and event.get("symbol") == args.symbol
        and event.get("session") == args.session.isoformat()
        and event.get("review_required") is True
    ]
    if not material or material[-1].get("observed_hash") != args.expected_revision_hash:
        raise ValueError("expected hash is not the latest material revision")
    versions = store.versions(args.symbol, args.session)
    observed = next(
        (record for record in versions if record.content_hash == args.expected_revision_hash),
        None,
    )
    if observed is None or observed.accepted:
        raise ValueError("expected hash does not name a rejected observed version")
    current = next((record for record in reversed(versions) if record.accepted), None)
    if current is None:
        raise ValueError("no accepted original version")
    result = {
        "mode": "apply" if args.apply else "preview",
        "symbol": args.symbol,
        "session": args.session.isoformat(),
        "decision": args.decision,
        "operator": args.operator,
        "reason": args.reason,
        "current_accepted_hash": current.content_hash,
        "observed_hash": observed.content_hash,
        "current_bar": asdict(current.bar),
        "observed_bar": asdict(observed.bar),
    }
    if args.apply:
        accepted = store.review_shadow_revision(
            args.symbol,
            args.session,
            decision=args.decision,
            expected_revision_hash=args.expected_revision_hash,
            operator=args.operator,
            reason=args.reason,
            reviewed_at=datetime.now(SYDNEY),
        )
        result["result_accepted_hash"] = accepted.content_hash
        result["pending_after"] = bool(
            store.shadow_revision_pending((args.symbol,), sessions=(args.session,))
        )
        if result["pending_after"]:
            raise RuntimeError("revision review did not clear its block")
    print(json.dumps(result, default=str, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

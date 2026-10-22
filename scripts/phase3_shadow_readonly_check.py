"""Read-only five-symbol Phase 3 check while operational authorities are absent.

This entry point contains no broker adapter or OMS. It invokes the shadow
authority gate and the raw IBKR history probe only, writing observations to
an explicit outside-Git OPERATIONAL root. No card can be published without
the dated ASX authorities.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from datetime import date, datetime, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from qat.config import Settings  # noqa: E402
from qat.domain.market_calendar import is_trading_day  # noqa: E402
from qat.operational.history import SYDNEY  # noqa: E402
from qat.operational.shadow import Phase3ShadowRunner, ShadowRecord  # noqa: E402


class _NoTradingSurface:
    def __getattr__(self, name: str) -> object:
        raise RuntimeError(f"read-only check cannot access {name}")


def validate_window(session: date, now: datetime, authorities: Path) -> None:
    local = now.astimezone(SYDNEY)
    if (
        local.date() != session
        or not is_trading_day("ASX", session)
        or not datetime.combine(session, time(17, 30), SYDNEY)
        <= local
        < datetime.combine(session, time(20), SYDNEY)
    ):
        raise ValueError("read-only shadow check requires today's 17:30–20:00 ASX window")
    if any(
        (authorities / name).exists()
        for name in ("calendar.json", "membership.json", "halts.jsonl", "actions.json")
    ):
        raise ValueError("dated authorities appeared; this raw-only check must be reviewed")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", type=date.fromisoformat, required=True)
    parser.add_argument("--operational-root", type=Path, required=True)
    parser.add_argument("--authorities-dir", type=Path, required=True)
    args = parser.parse_args()
    now = datetime.now(SYDNEY)
    validate_window(args.session, now, args.authorities_dir)
    settings = Settings(
        market="ASX",
        broker="ibkr",
        trading_mode="paper",
        execution_mode="recommend",
        delever_sweep_enabled=False,
        phase3_shadow_enabled=True,
        phase3_operational_root=str(args.operational_root),
        phase3_authorities_dir=str(args.authorities_dir),
    )
    if not settings.ibkr_account_id:
        raise ValueError("a configured IBKR paper account is required")
    no_trading = _NoTradingSurface()
    runner = Phase3ShadowRunner(settings, no_trading, no_trading, now=lambda: now)  # type: ignore[arg-type]
    complete = asyncio.run(runner.run_once(args.session))
    event = ShadowRecord(args.operational_root / "shadow.jsonl").events[-1]
    evidence_hashes = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(args.operational_root.iterdir())
        if path.is_file()
    }
    print(
        json.dumps(
            {
                "session": args.session.isoformat(),
                "complete": complete,
                "kind": event["kind"],
                "detail": event["detail"],
                "content_hash": event["content_hash"],
                "evidence_sha256": evidence_hashes,
            },
            sort_keys=True,
        )
    )
    return 0 if complete and event["kind"] == "abstention" else 1


if __name__ == "__main__":
    raise SystemExit(main())

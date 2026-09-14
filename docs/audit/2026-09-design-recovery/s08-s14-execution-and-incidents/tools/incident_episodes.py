"""Audit, brief §14: what each protective control actually caught, from the log.

Read-only. Reads qat.log and its rotated files; writes nothing.

    python incident_episodes.py <logs_dir> [since-YYYY-MM-DD]

Two controls log what they found, and both repeat the same finding every poll
while it stands, so repeats are collapsed into episodes:

* reconciliation: "Broker reconciliation mismatch: SYM tracked=N broker=M"
  (oms.py:2568-2576), the input that trips the kill switch;
* the resting-order scan: "RESTING ORDER ORPHAN: SYM SIDE resting=... "
  (oms.py:2579-2758), which quarantines the symbol.

Whether each episode was the broker doing something the app did not expect,
or the app's own record being wrong, is read from the detail line and the
lines around it; the report cites them.

Run it from PowerShell (HANDOFF, "THE ONE RULE").
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

AEST = timezone(timedelta(hours=10))
PATTERNS = {
    "reconciliation": re.compile(r"^Broker reconciliation mismatch: (.*)"),
    "orphan": re.compile(r"^RESTING ORDER ORPHAN: (.*)"),
}
GAP = timedelta(minutes=16)


def records(logs: Path):
    files = sorted(
        logs.glob("qat.log*"),
        key=lambda p: -int(p.suffix[1:]) if p.suffix[1:].isdigit() else 0,
    )
    for path in files:
        with path.open(encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                if raw.startswith("{"):
                    try:
                        yield json.loads(raw)
                    except json.JSONDecodeError:
                        continue


def main(logs: Path, since: str) -> None:
    for name, rx in PATTERNS.items():
        print(f"== {name} episodes (repeats within {GAP} collapsed) ==")
        last_key, last_ts, first_ts, count = None, None, None, 0
        episodes = []
        for rec in records(logs):
            m = rx.match(rec.get("message", ""))
            if not m:
                continue
            ts = datetime.fromisoformat(rec["ts"]).astimezone(AEST)
            if ts.date().isoformat() < since:
                continue
            key = re.sub(r"\s+-\s+\d+ (buy|sell).*", "", m.group(1))[:160]
            if key == last_key and last_ts is not None and ts - last_ts <= GAP:
                count += 1
                last_ts = ts
                continue
            if last_key is not None:
                episodes.append((first_ts, last_ts, count, last_key))
            last_key, first_ts, last_ts, count = key, ts, ts, 1
        if last_key is not None:
            episodes.append((first_ts, last_ts, count, last_key))
        for first, last, n, key in episodes:
            print(f"{first:%d %b %H:%M}-{last:%H:%M} x{n:<3d} {key}")
        print()


if __name__ == "__main__":
    main(Path(sys.argv[1]), sys.argv[2] if len(sys.argv) > 2 else "0000")

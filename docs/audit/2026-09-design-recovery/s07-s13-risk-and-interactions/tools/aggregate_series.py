"""Audit, brief §7 and §13: aggregate risk-at-stop over time, from the app's log.

Read-only. Reads qat.log and its rotated files; writes nothing.

    python aggregate_series.py <logs_dir> [since-YYYY-MM-DD]

The de-lever sweep (risk_engine/delever.py:143-165) logs one WARNING per poll
(every 300 s) while the book's aggregate risk-at-stop is OVER the cap, and
nothing at all when it is under. So a day with no reading means "under the
cap" only on a day the app was running - the run markers are printed beside
it for that reason. The sweep's snapshot excludes pending orders
(governor.py:505-534), so it can read lower than the entry gate's figure.

Run it from PowerShell (HANDOFF, "THE ONE RULE").
"""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

AEST = timezone(timedelta(hours=10))
OVER = re.compile(r"^Aggregate risk-at-stop ([\d.]+)% is over the ([\d.]+)% cap")
BUILD = re.compile(r"^Build: (M\d+)")
ADOPTED = re.compile(r"^Adopted (\d+) pre-existing broker position")
STOPS = re.compile(r"(\d+) of (\d+) carry a stop")


def lines(logs: Path):
    for path in sorted(logs.glob("qat.log*"), key=lambda p: p.name, reverse=True):
        with path.open(encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                if not raw.startswith("{"):
                    continue
                try:
                    rec = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                yield path.name, rec


def main(logs: Path, since: str) -> None:
    over: dict[str, list[tuple[str, float]]] = defaultdict(list)
    builds: dict[str, set[str]] = defaultdict(set)
    first_last: dict[str, list[str]] = {}
    adopted: dict[str, list[str]] = defaultdict(list)
    seen: set[tuple[str, str]] = set()
    for _file, rec in lines(logs):
        ts = datetime.fromisoformat(rec["ts"]).astimezone(AEST)
        day = ts.date().isoformat()
        if day < since:
            continue
        msg = rec.get("message", "")
        key = (rec["ts"], msg[:60])
        if key in seen:  # the rotated files do not overlap, but be sure
            continue
        seen.add(key)
        fl = first_last.setdefault(day, [ts.strftime("%H:%M"), ts.strftime("%H:%M")])
        fl[0] = min(fl[0], ts.strftime("%H:%M"))
        fl[1] = max(fl[1], ts.strftime("%H:%M"))
        if m := OVER.match(msg):
            over[day].append((ts.strftime("%H:%M"), float(m.group(1))))
        elif m := BUILD.match(msg):
            builds[day].add(m.group(1))
        elif ADOPTED.match(msg):
            s = STOPS.search(msg)
            adopted[day].append(
                f"{ts:%H:%M} adopted {ADOPTED.match(msg).group(1)}"
                + (f", {s.group(1)}/{s.group(2)} stopped" if s else "")
            )

    print(
        "AEST day    | log span    | builds       | over-cap readings: n  min   max   first  last"
    )
    for day in sorted(first_last):
        span = f"{first_last[day][0]}-{first_last[day][1]}"
        b = ",".join(sorted(builds[day])) or "-"
        o = over.get(day, [])
        if o:
            vals = [v for _, v in o]
            txt = f"{len(o):4d}  {min(vals):4.2f}  {max(vals):4.2f}  {o[0][0]}  {o[-1][0]}"
        else:
            txt = "   0  (none logged)"
        print(f"{day}  | {span} | {b:12s} | {txt}")
    print("\nposition adoption at launch (count, and how many carried a broker stop):")
    for day in sorted(adopted):
        print(f"  {day}: " + "; ".join(adopted[day]))


if __name__ == "__main__":
    main(Path(sys.argv[1]), sys.argv[2] if len(sys.argv) > 2 else "0000")

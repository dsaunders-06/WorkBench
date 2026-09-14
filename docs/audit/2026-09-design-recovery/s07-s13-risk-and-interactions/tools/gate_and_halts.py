"""Audit, brief §7: the autonomy gate, the kill switch and the bridge's own
holds, counted from the app's log.

Read-only. Reads qat.log and its rotated files; writes nothing.

    python gate_and_halts.py <logs_dir> [since-YYYY-MM-DD]

Why the log and not decision_journal.csv: the journal writes a verdict only
when it CHANGES for a symbol (decision_journal.py:88-109, M31b), so a gate
refusal repeated every minute appears once. The log line is written on every
evaluation (autonomy/executor.py:190-196). Both units are printed: LINES
(evaluations), distinct ORDERS and distinct SYMBOLS (CE-024).

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

BLOCKED = re.compile(r"^Autonomy blocked order (\S+) \((buy|sell) (\S+)\): (.*)")
SIGNED = re.compile(r"^Autonomy signed off order (\S+): (buy|sell) \S+ (\S+)")
EVAL_FAILED = re.compile(r"^Autonomous evaluation failed for order (\S+)")
TRIPPED = re.compile(r"^KILL-SWITCH TRIPPED: (.*?)\. All new order flow")
RESET = re.compile(r"^Kill-switch reset by (.+?) - order flow resumes \(was: (.*)\)")
RESTORED = re.compile(r"^KILL-SWITCH RESTORED FROM THE PREVIOUS SESSION: (.*?)\. The halt")
DRIFT_SKIPPED = re.compile(r"^No usable quote for (\S+), so the price-drift check is SKIPPED")
TURNOVER = re.compile(r"^Turnover budget reached: .* - (\S+) not opened")
HOLD_BACK = re.compile(r"^Signal exit on (\S+) held back")
HOLD_ESCAPE = re.compile(r"^(\S+) is [\d.]+R down after \d+ trading days - the minimum hold")
TIME_STOP = re.compile(r"^TIME STOP on (\S+)")


def shape(reason: str) -> str:
    text = re.sub(r"[0-9a-f]{32}", "<id>", reason)
    text = re.sub(r"-?\d[\d,.]*%?", "#", text)
    return text[:95]


def records(logs: Path):
    for path in sorted(logs.glob("qat.log*"), key=lambda p: p.name, reverse=True):
        with path.open(encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                if raw.startswith("{"):
                    try:
                        yield json.loads(raw)
                    except json.JSONDecodeError:
                        continue


def main(logs: Path, since: str) -> None:
    blocked: dict[tuple[str, str], list[tuple[str, str]]] = defaultdict(list)
    counters: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    halts: list[tuple[datetime, str, str]] = []
    for rec in records(logs):
        ts = datetime.fromisoformat(rec["ts"]).astimezone(AEST)
        day = ts.date().isoformat()
        if day < since:
            continue
        msg = rec.get("message", "")
        if m := BLOCKED.match(msg):
            blocked[(day, shape(m.group(4)))].append((m.group(1), m.group(3)))
        elif m := SIGNED.match(msg):
            counters["gate signed off (orders, symbol)"][day].append(m.group(3))
        elif m := EVAL_FAILED.match(msg):
            counters["gate evaluation FAILED (left pending)"][day].append(m.group(1))
        elif m := DRIFT_SKIPPED.match(msg):
            counters["price-drift check SKIPPED (no quote)"][day].append(m.group(1))
        elif m := TURNOVER.match(msg):
            counters["weekly entry budget refused"][day].append(m.group(1))
        elif m := HOLD_BACK.match(msg):
            counters["minimum hold held a signal exit back"][day].append(m.group(1))
        elif m := HOLD_ESCAPE.match(msg):
            counters["minimum hold escaped (>= 0.5R down)"][day].append(m.group(1))
        elif m := TIME_STOP.match(msg):
            counters["time stop fired"][day].append(m.group(1))
        elif m := TRIPPED.match(msg):
            halts.append((ts, "TRIP", m.group(1)))
        elif m := RESTORED.match(msg):
            halts.append((ts, "RESTORED AT LAUNCH", m.group(1)))
        elif m := RESET.match(msg):
            halts.append((ts, f"RESET by {m.group(1)}", m.group(2)))

    print("== autonomy gate blocks: day | lines | orders | symbols | reason ==")
    for (day, reason), hits in sorted(blocked.items()):
        orders = {o for o, _ in hits}
        syms = sorted({s for _, s in hits})
        print(f"{day} {len(hits):5d} {len(orders):4d} {len(syms):3d}  {reason}  [{','.join(syms)}]")

    print("\n== totals by reason over the period: lines / orders / symbols / days ==")
    totals: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    for (day, reason), hits in blocked.items():
        totals[reason].extend((day, o, s) for o, s in hits)
    for reason, hits in sorted(totals.items(), key=lambda kv: -len(kv[1])):
        print(
            f"{len(hits):6d} {len({o for _, o, _ in hits}):5d} {len({s for _, _, s in hits}):4d} "
            f"{len({d for d, _, _ in hits}):3d}  {reason}"
        )

    print("\n== other rails and holds: day -> lines (distinct symbols) ==")
    for name, by_day in counters.items():
        cells = "; ".join(f"{d}: {len(v)} ({len(set(v))})" for d, v in sorted(by_day.items()))
        print(f"{name}: {cells}")

    print("\n== kill switch: trips, launch restores and resets, in order ==")
    open_since: datetime | None = None
    for ts, kind, reason in sorted(halts):
        note = ""
        if kind == "TRIP" and open_since is None:
            open_since = ts
        elif kind.startswith("RESET") and open_since is not None:
            note = f"  (halted {ts - open_since})"
            open_since = None
        print(f"{ts:%m-%d %H:%M:%S}  {kind:22s} {reason[:110]}{note}")


if __name__ == "__main__":
    main(Path(sys.argv[1]), sys.argv[2] if len(sys.argv) > 2 else "0000")

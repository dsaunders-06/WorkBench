"""Audit, brief §8: which execution behaviours have actually happened live.

Read-only. Reads qat.log and its rotated files; writes nothing.

    python execution_evidence.py <logs_dir> [since-YYYY-MM-DD]

The brief asks to keep "code exists" apart from "behaviour has been
demonstrated under realistic conditions". The evidence for the second is a log
line the behaviour writes when it runs. For each behaviour this prints how
many times it ran, on how many days and symbols, when first and last, and
under which builds (the "Build: Mnnn" line each launch writes). A behaviour
with no line is "code only" as far as the log can show.

The patterns are the messages in src/qat as of the deployed build (M175);
the file:line of each is in the report. Run from PowerShell (HANDOFF, "THE ONE
RULE").
"""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

AEST = timezone(timedelta(hours=10))

# (label, pattern). A named group "sym" is counted as the symbol when present.
BEHAVIOURS: list[tuple[str, str]] = [
    (
        "entry signed off by the autonomy gate",
        r"^Autonomy signed off order \S+: buy \S+ (?P<sym>\S+)",
    ),
    (
        "exit signed off by the autonomy gate",
        r"^Autonomy signed off order \S+: sell \S+ (?P<sym>\S+)",
    ),
    (
        "transmitted, signed by the operator (blotter)",
        r"^Order signed off and transmitted: .*operator=operator \(blotter\) symbol=(?P<sym>\S+)",
    ),
    (
        "transmitted, signed by the operator (dashboard close)",
        r"^Order signed off and transmitted: .*operator=operator \(dashboard\) symbol=(?P<sym>\S+)",
    ),
    (
        "protective stop/OCO resting after sign-off (re-arm)",
        r"^Protective (?:OCO|stop) resting: .*symbol=(?P<sym>\S+)",
    ),
    (
        "re-arm proposed for unprotected positions",
        r"^Proposed protective stops for \d+ unprotected",
    ),
    (
        "entry fill confirmed at the broker after 'transmitted'",
        r"^Order \S+ \(buy (?P<sym>\S+) [\d.]+\) is filled at the broker",
    ),
    ("entry price corrected mid-session to the fill", r"^ENTRY PRICE CORRECTED: (?P<sym>\S+)"),
    (
        "entry price corrected at startup from avgCost",
        r"^Corrected the recorded entry price for (?P<sym>\S+)",
    ),
    (
        "broker-side fill absorbed (stop/target/manual)",
        r"^BROKER-SIDE FILL absorbed: \w+ \S+ (?P<sym>\S+) at",
    ),
    ("missed executions replayed at startup", r"^Replayed \d+ execution"),
    (
        "exit cancelled its protective legs first",
        r"^Cancelled \d+ protective leg\(s\) on (?P<sym>\S+) before exiting",
    ),
    (
        "exit refused: a leg still resting after cancel",
        r"^\d+ protective leg\(s\) on (?P<sym>\S+) are STILL RESTING",
    ),
    ("manual close completed", r"^MANUAL CLOSE: (?P<sym>\S+) "),
    ("manual close hit a problem path", r"^MANUAL CLOSE (?:of|LEFT) (?P<sym>\S+)"),
    ("position unprotected (stop gone at broker)", r"^POSITION UNPROTECTED: (?P<sym>\S+)"),
    ("protection pending (grace kept)", r"^PROTECTION PENDING on (?P<sym>\S+)"),
    ("protection level changed at broker", r"^PROTECTION LEVEL CHANGED"),
    (
        "booking reversed after a broker rejection",
        r"^Reversed [\d.]+ of the booking for (?P<sym>\S+)",
    ),
    ("duplicate-transmission guard refused", r"has already been transmitted to the broker"),
    ("IBKR rejection classified (REJECT/HALT)", r"^IBKR REJECTED order"),
    ("reconciliation mismatch trip", r"^KILL-SWITCH TRIPPED: Broker reconciliation mismatch"),
    ("resting-order orphan detected", r"^RESTING ORDER ORPHAN: (?P<sym>\S+)"),
    ("resting-order quarantine lifted", r"^Resting-order quarantine on (?P<sym>\S+) LIFTED"),
    ("position anomaly declared", r"^POSITION ANOMALY DECLARED"),
    ("time stop fired", r"^TIME STOP on (?P<sym>\S+)"),
    ("commission verified against IBKR", r"^COMMISSION VERIFIED"),
    ("commission disagrees with IBKR", r"^COMMISSION DISAGREES"),
    ("corporate action seen / stop adjusted", r"^(?:CORPORATE ACTION first seen|ADJUSTED:)"),
    ("IBKR error 10349 (TIF preset)", r"^Error 10349"),
    ("IBKR error 202 (order cancelled)", r"^Error 202"),
    ("IBKR error 383 (size limit)", r"^Error 383"),
    ("IBKR error 10148 (cannot cancel)", r"^Error 10148"),
]
BUILD = re.compile(r"^Build: (M\d+)")


def records(logs: Path):
    # qat.log.6 is the oldest; qat.log the newest. Read oldest first so the
    # running "current build" is right for every line.
    files = sorted(
        logs.glob("qat.log*"), key=lambda p: -int(p.suffix[1:]) if p.suffix[1:].isdigit() else 0
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
    compiled = [(label, re.compile(p)) for label, p in BEHAVIOURS]
    hits: dict[str, list[tuple[datetime, str, str]]] = defaultdict(list)
    build = "?"
    for rec in records(logs):
        msg = rec.get("message", "")
        if m := BUILD.match(msg):
            build = m.group(1)
            continue
        ts = datetime.fromisoformat(rec["ts"]).astimezone(AEST)
        if ts.date().isoformat() < since:
            continue
        for label, rx in compiled:
            if m := rx.search(msg):
                sym = m.groupdict().get("sym") or "-"
                hits[label].append((ts, sym, build))
                break

    # A protective re-arm is also a SELL signed by the gate. Split the gate's
    # sell sign-offs by order id: an id that later logs "Protective ... resting"
    # is a protective stop, anything else is a market exit.
    protective_ids: set[str] = set()
    sells: list[tuple[datetime, str, str, str]] = []
    for rec in records(logs):
        msg = rec.get("message", "")
        if m := re.match(r"^Protective (?:OCO|stop) resting: order=(\S+)", msg):
            protective_ids.add(m.group(1))
        elif m := re.match(r"^Autonomy signed off order (\S+): sell \S+ (\S+)", msg):
            ts = datetime.fromisoformat(rec["ts"]).astimezone(AEST)
            if ts.date().isoformat() >= since:
                sells.append((ts, m.group(1), m.group(2), ""))
    exits = [s for s in sells if s[1] not in protective_ids]
    prot = [s for s in sells if s[1] in protective_ids]
    print(f"gate-signed sells: {len(sells)} = {len(prot)} protective re-arms", end="")
    print(f" + {len(exits)} market exits")
    for ts, oid, sym, _ in exits:
        print(f"  market exit signed {ts:%d %b %H:%M:%S} {sym} (order {oid})")
    print()

    head = f"{'behaviour':55s} {'lines':>5s} {'days':>4s} {'syms':>4s}"
    print(head + "  first        last         builds")
    for label, _ in BEHAVIOURS:
        h = hits.get(label, [])
        if not h:
            print(
                f"{label:55s} {0:5d}                   (none - code only, as far as the log shows)"
            )
            continue
        days = {t.date() for t, _, _ in h}
        syms = {s for _, s, _ in h if s != "-"}
        builds = sorted({b for _, _, b in h}, key=lambda b: int(b[1:]) if b[1:].isdigit() else 0)
        span = f"{h[0][0]:%d %b %H:%M}  {h[-1][0]:%d %b %H:%M}"
        shown = (
            ",".join(builds) if len(builds) <= 4 else f"{builds[0]}..{builds[-1]} ({len(builds)})"
        )
        print(f"{label:55s} {len(h):5d} {len(days):4d} {len(syms):4d}  {span}  {shown}")


if __name__ == "__main__":
    main(Path(sys.argv[1]), sys.argv[2] if len(sys.argv) > 2 else "0000")

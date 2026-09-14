"""Audit, brief §10: what the regime engine actually did, run by run.

Read-only. Reads qat.log and its rotated files, and risk_decisions.csv and
closed_trades.csv from the data folder; writes nothing.

    python regime_evidence.py <data_dir>

<data_dir> is %LOCALAPPDATA%\\QuantAdvisoryTerminal\\data. Run from PowerShell
(HANDOFF, "THE ONE RULE"): the Bash sandbox serves a stale copy of it.

Sections:
  0. where the retained log is continuous, and any hole between its files;
  1. every run of the regime engine: build, benchmark, seeded window, breadth
     kept, the refit, and each label it published with its VIX and curve;
  2. what the first label after launch did next, and how long it lasted;
  3. the label against the US VIX, for the fusion rule's 15 / 25 thresholds;
  4. how old each FRED observation was when the app read it;
  5. the regime recorded on each risk decision, and on the ledger.

The patterns are the messages in src/qat as of the deployed build (M175),
plus the older wording of the transition line ("Strategies whose suitable
...", replaced by M57c).
"""

from __future__ import annotations

import csv
import json
import re
import statistics
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

AEST = timezone(timedelta(hours=10))

BUILD = re.compile(r"^Build: (M\d+)")
START = re.compile(r"^Regime engine starting: benchmark=(\S+), (\d+) breadth symbols")
SEED = re.compile(
    r"^Regime engine seeded with (\d+) daily bars \((\S+) to (\S+)\), (\d+) breadth symbols"
)
BREADTH = re.compile(r"^Breadth: kept (\d+) symbol\(s\), dropped (\d+)")
NO_BREADTH = re.compile(r"^No breadth symbols cover every benchmark bar")
FLAT = re.compile(r"^Regime features that never moved across (\d+) bars: (.*?)\. A constant")
SPREAD = re.compile(r"^Raw feature spread is led by (\S+) at ([\d.]+)%")
REFIT = re.compile(r"^Refitting the regime HMM on (\d+) bars x (\d+) features")
FIT_FAIL = re.compile(r"^Regime HMM fit FAILED")
NOT_CLASSIFYING = re.compile(r"^REGIME ENGINE NOT CLASSIFYING \((.*?)\)")
TRANSITION = re.compile(r"^REGIME (\S+) -> (\S+) \(exposure scalar ([\d.]+)\)")
TOP = re.compile(r"Top probabilities: (.*?)\.(?: VIX=([\d.]+), curve=(-?[\d.]+))?$")
MACRO = re.compile(r"^Macro (\S+) = (-?[\d.]+) \(as of (\d{4}-\d{2}-\d{2})")
MACRO_FAIL = re.compile(r"^Macro (?:series|history for) (\S+) (?:could not|failed)")


def records(logs: Path):
    """Oldest file first, so each line meets the build that was running."""
    files = sorted(
        logs.glob("qat.log*"), key=lambda p: -int(p.suffix[1:]) if p.suffix[1:].isdigit() else 0
    )
    for path in files:
        yield from _file_records(path)


def local(ts: str) -> datetime:
    return datetime.fromisoformat(ts).astimezone(AEST)


def new_run(ts: datetime, build: str, benchmark: str, breadth: int) -> dict:
    return {
        "start": ts,
        "build": build,
        "benchmark": benchmark,
        "breadth_start": breadth,
        "seed": None,
        "breadth": None,
        "no_breadth": False,
        "flat": [],
        "spread": None,
        "refits": [],
        "fit_fail": 0,
        "not_classifying": [],
        "labels": [],
    }


def read_log(logs: Path):
    runs: list[dict] = []
    macro: list[tuple[datetime, str, float, date]] = []
    macro_fail: list[tuple[datetime, str]] = []
    build = "?"
    run: dict | None = None
    for rec in records(logs):
        msg = rec.get("message", "")
        if m := BUILD.match(msg):
            build = m.group(1)
            continue
        prefixes = ("Regime", "REGIME", "Refitting", "Breadth:", "No breadth", "Raw feature")
        if not msg.startswith((*prefixes, "Macro")):
            continue
        ts = local(rec["ts"])
        if m := START.match(msg):
            run = new_run(ts, build, m.group(1), int(m.group(2)))
            runs.append(run)
        elif m := MACRO.match(msg):
            macro.append((ts, m.group(1), float(m.group(2)), date.fromisoformat(m.group(3))))
        elif m := MACRO_FAIL.match(msg):
            macro_fail.append((ts, m.group(1)))
        elif run is None:
            continue
        elif m := SEED.match(msg):
            run["seed"] = (int(m.group(1)), m.group(2), m.group(3), int(m.group(4)))
        elif m := BREADTH.match(msg):
            run["breadth"] = (int(m.group(1)), int(m.group(2)))
        elif NO_BREADTH.match(msg):
            run["no_breadth"] = True
        elif m := FLAT.match(msg):
            run["flat"].append(m.group(2))
        elif m := SPREAD.match(msg):
            run["spread"] = (m.group(1), float(m.group(2)))
        elif m := REFIT.match(msg):
            run["refits"].append((ts, int(m.group(1)), int(m.group(2))))
        elif FIT_FAIL.match(msg):
            run["fit_fail"] += 1
        elif m := NOT_CLASSIFYING.match(msg):
            run["not_classifying"].append((ts, m.group(1)))
        elif m := TRANSITION.match(msg):
            top = TOP.search(msg)
            run["labels"].append(
                {
                    "ts": ts,
                    "from": m.group(1),
                    "to": m.group(2),
                    "scalar": float(m.group(3)),
                    "top": top.group(1) if top else "",
                    "vix": float(top.group(2)) if top and top.group(2) else None,
                    "curve": float(top.group(3)) if top and top.group(3) else None,
                }
            )
    return runs, macro, macro_fail


def section_runs(runs: list[dict]) -> None:
    print("=== 1. EVERY RUN OF THE REGIME ENGINE (AEST) ===")
    print(f"runs: {len(runs)}  (a run = one 'Regime engine starting' line)")
    by_bench = Counter(r["benchmark"] for r in runs)
    print("by benchmark: " + ", ".join(f"{b} {n}" for b, n in by_bench.items()))
    classified = [r for r in runs if r["labels"]]
    print(f"runs that published a label: {len(classified)}")
    refitted = [r for r in runs if r["refits"]]
    per_run = dict(Counter(len(r["refits"]) for r in refitted))
    print(f"runs with a refit: {len(refitted)}; refits per such run: {per_run}")
    print(f"fit failures: {sum(r['fit_fail'] for r in runs)}")
    print()
    for r in classified:
        seed = r["seed"]
        seed_txt = f"seed {seed[0]} bars {seed[1]}..{seed[2]}, breadth {seed[3]}" if seed else "-"
        refit = r["refits"][0] if r["refits"] else None
        refit_txt = f"refit {refit[1]}x{refit[2]} at {refit[0]:%H:%M}" if refit else "no refit"
        spread = f", raw spread {r['spread'][0]} {r['spread'][1]:.1f}%" if r["spread"] else ""
        extra = "  NO-BREADTH-COVER" if r["no_breadth"] else ""
        extra += f"  FLAT[{'; '.join(r['flat'])}]" if r["flat"] else ""
        print(
            f"{r['start']:%d %b %H:%M} {r['build']:5s} {r['benchmark']:7s} {seed_txt}; "
            f"{refit_txt}{spread}{extra}"
        )
        first = r["labels"][0]["ts"]
        for lab in r["labels"]:
            after = (lab["ts"] - first).total_seconds() / 60
            vix = f"VIX={lab['vix']:.2f} curve={lab['curve']:.2f}" if lab["vix"] is not None else ""
            print(
                f"    {lab['ts']:%H:%M:%S} +{after:5.1f}m  {lab['from']:>9s} -> {lab['to']:9s}"
                f" x{lab['scalar']:.2f}  [{lab['top']}] {vix}"
            )
    print()


def section_first_label(runs: list[dict]) -> None:
    print("=== 2. THE FIRST LABEL AFTER LAUNCH, AND WHAT IT DID NEXT ===")
    first_labels: Counter = Counter()
    followed: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for r in runs:
        if not r["labels"]:
            continue
        head = r["labels"][0]
        first_labels[head["to"]] += 1
        if len(r["labels"]) > 1:
            nxt = r["labels"][1]
            mins = (nxt["ts"] - head["ts"]).total_seconds() / 60
            followed[head["to"]].append((nxt["to"], mins))
    for label, n in first_labels.most_common():
        nxt = followed.get(label, [])
        changed = Counter(t for t, _ in nxt)
        mins = [m for _, m in nxt]
        med = (
            f", median {statistics.median(mins):.1f} min (range {min(mins):.1f}-{max(mins):.1f})"
            if mins
            else ""
        )
        print(
            f"first label {label:9s} {n:3d} runs; changed later in the run {len(nxt):3d}"
            + (f" -> {dict(changed)}{med}" if nxt else "")
        )
    within = Counter(
        (lab["from"], lab["to"]) for r in runs for lab in r["labels"][1:] if lab["from"] != "none"
    )
    listed = ", ".join(f"{a}->{b} {n}" for (a, b), n in within.items())
    print(f"all within-run transitions: {listed}")
    print()


def section_vix(runs: list[dict]) -> None:
    print("=== 3. THE LABEL AGAINST THE US VIX ===")
    print("(fusion.py:163-167: below 15 adds 1.0 to low_vol, above 25 adds 1.0 to high_vol)")
    rows: dict[str, list[float]] = defaultdict(list)
    for r in runs:
        for lab in r["labels"]:
            if lab["vix"] is not None:
                rows[lab["to"]].append(lab["vix"])
    for label, vix in sorted(rows.items()):
        below = sum(1 for v in vix if v < 15)
        above = sum(1 for v in vix if v > 25)
        print(
            f"{label:9s} {len(vix):3d} lines  VIX {min(vix):.2f}-{max(vix):.2f}  "
            f"<15: {below}  15-25: {len(vix) - below - above}  >25: {above}"
        )
    missing = sum(1 for r in runs for lab in r["labels"] if lab["vix"] is None)
    print(f"label lines with no VIX value (not in this table): {missing}")
    print()


def section_macro(macro: list, macro_fail: list) -> None:
    print("=== 4. HOW OLD EACH FRED OBSERVATION WAS WHEN THE APP READ IT (calendar days) ===")
    ages: dict[str, list[int]] = defaultdict(list)
    last_seen: dict[str, tuple[datetime, date, float]] = {}
    for ts, series, value, as_of in macro:
        ages[series].append((ts.date() - as_of).days)
        last_seen[series] = (ts, as_of, value)
    for series, a in sorted(ages.items()):
        ts, as_of, value = last_seen[series]
        print(
            f"{series:7s} {len(a):4d} reads  age median {statistics.median(a):.0f}  "
            f"max {max(a):3d}  last read {ts:%d %b %H:%M}: {value} as of {as_of}"
        )
    fails = Counter(s for _, s in macro_fail)
    print("fetch failures: " + (", ".join(f"{s} {n}" for s, n in fails.items()) or "none"))
    print()


def section_records(data: Path) -> None:
    print("=== 5. THE REGIME ON EACH RISK DECISION, AND ON THE LEDGER ===")
    path = data / "risk_decisions.csv"
    by_label: Counter = Counter()
    approved_by_label: Counter = Counter()
    first_with_label: str | None = None
    # (side, label, scalar) -> the AEST times of the approved rows, for
    # matching an approval against the launch whose first label it carried.
    approved_times: dict[tuple, list[str]] = defaultdict(list)
    rows = 0
    with path.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            rows += 1
            try:
                inputs = json.loads(row.get("inputs") or "{}")
            except json.JSONDecodeError:
                inputs = {}
            # By SIDE first: evaluate_exit (engine.py:371-406) records no regime,
            # because an exit is not sized by it. Without the side, those rows
            # read as entries missing their regime.
            key = (
                str(inputs.get("side", "?")),
                str(inputs.get("regime_label", "<absent>")),
                inputs.get("regime_scalar", "<absent>"),
            )
            by_label[key] += 1
            if row.get("approved", "").lower() == "true":
                approved_by_label[key] += 1
                stamp = local(row["timestamp"]).strftime("%d %b %H:%M:%S")
                approved_times[key].append(f"{row['symbol']} {stamp}")
            if "regime_label" in inputs and first_with_label is None:
                first_with_label = row.get("timestamp")
    print(f"risk_decisions.csv: {rows} rows; first row carrying regime_label: {first_with_label}")
    for (side, label, scalar), n in sorted(by_label.items(), key=lambda kv: (kv[0][0], -kv[1])):
        approved = approved_by_label[(side, label, scalar)]
        print(f"  {side:4s} label {label:9s} scalar {scalar!s:8s} {n:5d} rows, approved {approved}")
        if label == "recovery" and approved:
            print("      approved: " + "; ".join(approved_times[(side, label, scalar)]))
    ledger = data / "closed_trades.csv"
    with ledger.open(encoding="utf-8", newline="") as fh:
        trades = list(csv.DictReader(fh))
    blank = sum(1 for t in trades if not (t.get("regime_at_entry") or "").strip())
    print(f"closed_trades.csv: {len(trades)} rows; regime_at_entry blank on {blank}")


def section_coverage(logs: Path) -> None:
    """Where the retained log is continuous, and where it is not.

    The files are read oldest first. A gap between one file's last line and
    the next file's first line is time the log does not cover at all.
    """
    print("=== 0. LOG COVERAGE (AEST) ===")
    files = sorted(
        logs.glob("qat.log*"), key=lambda p: -int(p.suffix[1:]) if p.suffix[1:].isdigit() else 0
    )
    previous: datetime | None = None
    for path in files:
        stamps = [rec["ts"] for rec in _file_records(path)]
        first, last = local(stamps[0]), local(stamps[-1])
        gap = ""
        if previous is not None and (first - previous) > timedelta(minutes=5):
            minutes = (first - previous).total_seconds() / 60
            gap = f"   <-- GAP of {minutes:.0f} min before this file"
        print(f"{path.name:10s} {first:%d %b %H:%M:%S} to {last:%d %b %H:%M:%S}{gap}")
        previous = last
    print()


def _file_records(path: Path):
    with path.open(encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            if raw.startswith("{"):
                try:
                    yield json.loads(raw)
                except json.JSONDecodeError:
                    continue


def main(data: Path) -> None:
    section_coverage(data / "logs")
    runs, macro, macro_fail = read_log(data / "logs")
    section_runs(runs)
    section_first_label(runs)
    section_vix(runs)
    section_macro(macro, macro_fail)
    section_records(data)


if __name__ == "__main__":
    main(Path(sys.argv[1]))

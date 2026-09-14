"""Audit, brief §7: which rail refused or trimmed what, by day.

Read-only. Reads QAT's record files and prints tables; writes nothing.

    python rails_by_day.py <data_dir>

<data_dir> is QAT's data folder (%LOCALAPPDATA%\\QuantAdvisoryTerminal\\data).
Run it from PowerShell: the Bash sandbox serves a frozen copy of that folder
and does not say so (HANDOFF, "THE ONE RULE").

Every count says what it counts (CE-024): decision ROWS, distinct SYMBOLS,
and distinct symbol-days are printed side by side, because the same candidate
is re-evaluated on every tick while its signal stands.
"""

from __future__ import annotations

import csv
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

AEST = timezone(timedelta(hours=10))

# A reason is classified by its leading text. Order matters: first match wins.
# Each pattern is matched against the reason as the engine wrote it
# (risk_engine/engine.py, governor.py, portfolio_risk.py).
RAILS: list[tuple[str, str]] = [
    ("approved", r"^approved"),
    ("exit approved", r"^exit - closing existing position"),
    ("kill switch", r"kill[- ]switch"),
    ("sizing zero", r"^Sizing produced zero"),
    ("insufficient cash", r"^Insufficient cash"),
    ("position count", r"concurrent positions|position limit|positions? .*cap"),
    ("aggregate risk-at-stop", r"^aggregate risk-at-stop"),
    ("per-share risk", r"per-share risk|risk per share"),
    ("headroom < 1 share", r"headroom"),
    ("single name", r"single[- ]name"),
    ("sector", r"sector"),
    ("cluster", r"cluster|correlat"),
    ("gap budget", r"gap"),
    ("expected shortfall", r"ES|expected shortfall"),
    ("cost-to-risk", r"fees|cost"),
]


def classify(reason: str) -> str:
    for name, pattern in RAILS:
        if re.search(pattern, reason, flags=re.IGNORECASE if name != "expected shortfall" else 0):
            return name
    return "OTHER: " + re.sub(r"[\d.]+", "#", reason)[:70]


def day_of(ts: str) -> str:
    return datetime.fromisoformat(ts).astimezone(AEST).date().isoformat()


def main(data_dir: Path) -> None:
    rows = list(
        csv.DictReader((data_dir / "risk_decisions.csv").open(newline="", encoding="utf-8"))
    )
    print(f"risk_decisions.csv: {len(rows)} rows")
    print(f"  first {rows[0]['timestamp']}   last {rows[-1]['timestamp']}")
    print(f"  markets: {dict(Counter(r['market'] for r in rows))}")
    sides = Counter(json.loads(r["inputs"]).get("side", "?") for r in rows)
    print(f"  sides: {dict(sides)}")

    # ---- 1. every distinct reason shape, so the classifier can be checked by eye
    shapes = Counter(re.sub(r"-?[\d.]+%?", "#", r["reason"]) for r in rows)
    print("\n== reason shapes (numbers replaced by #), rows ==")
    for shape, n in shapes.most_common():
        print(f"{n:6d}  [{classify(shape.replace('#', '1'))}]  {shape[:110]}")

    # ---- 2. by day x rail: rows / symbols
    by_day: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for r in rows:
        # Exits and entries are different questions: a refused exit is a
        # position the app could not close, not an opportunity it declined.
        side = json.loads(r["inputs"]).get("side", "?")
        label = ("EXIT " if side == "sell" else "") + classify(r["reason"])
        by_day[day_of(r["timestamp"])][label].append(r["symbol"])
    rails = sorted({k for d in by_day.values() for k in d}, key=lambda k: (k != "approved", k))
    print("\n== by AEST day: rail -> rows (distinct symbols) ==")
    for day in sorted(by_day):
        cells = by_day[day]
        total = sum(len(v) for v in cells.values())
        syms = len({s for v in cells.values() for s in v})
        parts = [f"{k}: {len(cells[k])} ({len(set(cells[k]))})" for k in rails if k in cells]
        print(f"{day}  total {total} rows, {syms} symbols | " + "; ".join(parts))

    # ---- 3. per rail overall: rows, symbols, symbol-days, days
    print("\n== per rail over the whole file ==")
    print(f"{'rail':26s} {'rows':>6s} {'symbols':>8s} {'sym-days':>9s} {'days':>5s}")
    for k in rails:
        pairs = {(d, s) for d, cells in by_day.items() for s in cells.get(k, [])}
        days = {d for d, _ in pairs}
        syms = {s for _, s in pairs}
        n = sum(len(cells.get(k, [])) for cells in by_day.values())
        print(f"{k:26s} {n:6d} {len(syms):8d} {len(pairs):9d} {len(days):5d}")

    # ---- 4. trims on APPROVED rows (flags the engine records in inputs)
    print("\n== trims recorded on approved rows (rows / distinct symbol-days) ==")
    flags = ["resized_for_stop_budget", "resized_for_cash", "resized_by_governor"]
    approved = [r for r in rows if r["approved"] == "True"]
    for f in flags:
        hit = [r for r in approved if json.loads(r["inputs"]).get(f)]
        sd = {(day_of(r["timestamp"]), r["symbol"]) for r in hit}
        print(f"{f:26s} {len(hit):6d} rows  {len(sd):4d} symbol-days")
    scal = Counter(
        (
            json.loads(r["inputs"]).get("regime_scalar"),
            json.loads(r["inputs"]).get("earnings_event_scalar"),
        )
        for r in approved
    )
    print(f"(regime_scalar, earnings_event_scalar) on approved rows: {dict(scal)}")
    keys = Counter(k for r in rows for k in json.loads(r["inputs"]))
    print(f"\ninput keys seen (rows carrying each): {dict(keys)}")


if __name__ == "__main__":
    main(Path(sys.argv[1]))

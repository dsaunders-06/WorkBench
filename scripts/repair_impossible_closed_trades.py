"""Remove closed trades that closed before they opened. Dry-run by default.

    .\\.venv\\Scripts\\python.exe scripts/repair_impossible_closed_trades.py
    .\\.venv\\Scripts\\python.exe scripts/repair_impossible_closed_trades.py --execute

Written for the 24 August 2026 repair. `closed_trades.csv` gained seven rows
whose `closed_at` precedes their `opened_at` by about an hour - trades that
closed before they existed.

HOW THEY GOT THERE. `absorbed_fills.json` carried a watermark of
2026-08-24T00:38:09Z, set before the application was killed at 14:08 and never
advanced past the session that followed. On restart at 15:18 everything after
10:38 looked unabsorbed, so `recent_fills` handed back the whole afternoon: the
duplicate buys from the M139 incident, the operator's MANUAL remediation sells
at 14:24-14:25, and the app's own current fills. The manual sells were absorbed
as "a resting protective order executed, and this is now a closed trade" and
matched against the lot opened at 15:19:36.

WHY THIS IS FIX-IMMEDIATELY RATHER THAN A CURIOSITY. The promotion gate reads
this file, and below `edge_min_trades` (20) closed trades the sizer sizes real
positions from these results. Seven invented losses attributed to `swing`, worth
-$168.00 that nobody lost, sit in the evidence base the whole experiment rests
on. A defect that corrupts the record is fix-immediately.

WHAT THIS DOES NOT DO. It does not touch the position - TNE.AX 3,051 is real,
correctly bracketed, and belongs in the book. It does not reset the kill switch,
which tripped correctly on the resulting reconciliation mismatch. And it removes
ONLY rows that are impossible on their face; anything merely suspicious is
reported and kept, because a repair that deletes real trades is worse than the
corruption it fixes.
"""

from __future__ import annotations

import argparse
import csv
import shutil
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from qat.config import Settings  # noqa: E402


def _parse(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="write the repaired file")
    args = parser.parse_args()

    ledger = Path(Settings().data_dir) / "closed_trades.csv"
    if not ledger.exists():
        print(f"No ledger at {ledger}")
        return 1

    with ledger.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
        fieldnames = list(rows[0].keys()) if rows else []

    keep: list[dict[str, str]] = []
    drop: list[dict[str, str]] = []
    for row in rows:
        opened, closed = _parse(row.get("opened_at", "")), _parse(row.get("closed_at", ""))
        # The one test applied. An exit stamped BEFORE its entry is not a
        # judgement call about plausibility - it is arithmetic.
        if opened and closed and closed < opened:
            drop.append(row)
        else:
            keep.append(row)

    print(f"ledger      {ledger}")
    print(f"rows        {len(rows)}")
    print(f"impossible  {len(drop)}  (closed_at earlier than opened_at)")
    print(f"keeping     {len(keep)}\n")

    if drop:
        print("=== WOULD REMOVE ===")
        total = 0.0
        for row in drop:
            pnl = float(row.get("gross_pnl") or 0)
            total += pnl
            print(
                f"  {row.get('symbol'):<8} {row.get('strategy'):<7} qty={row.get('quantity'):>8} "
                f"opened {row.get('opened_at')}  closed {row.get('closed_at')}  pnl {pnl:>9,.2f}"
            )
        print(f"  {'':<8} {'':<7} {'':>12} {'fabricated P&L removed:':>46} {total:>9,.2f}\n")

    if not args.execute:
        print("Dry run. Nothing written. Re-run with --execute to repair.")
        return 0

    if not drop:
        print("Nothing to repair.")
        return 0

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = ledger.with_suffix(f".csv.bak-{stamp}-PRE-IMPOSSIBLE-TRADE-REPAIR")
    shutil.copy2(ledger, backup)
    print(f"backed up to {backup.name}")

    with ledger.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(keep)
    print(f"wrote {len(keep)} row(s) to {ledger.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

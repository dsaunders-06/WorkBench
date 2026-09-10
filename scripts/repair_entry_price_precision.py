r"""Restore the precision lost when entry_price was stored at four decimals.

    .\.venv\Scripts\python.exe scripts/repair_entry_price_precision.py
    .\.venv\Scripts\python.exe scripts/repair_entry_price_precision.py --apply

⚠️ RUN IT UNDER POWERSHELL. It builds `Settings()` and writes to the live data
directory. The Bash sandbox serves a frozen snapshot and does not error.

WHAT IS WRONG. `ClosedTrade.gross_pnl` and `net_pnl` are DERIVED properties -
`(exit_price - entry_price) * quantity` - and `from_row` recomputes them on
read, deliberately: *"everything else on this class is derived, and recomputing
it is the point"*. That design is correct, and the SEK.AX repair proves it. When
a ledger is repaired the PRICES are corrected, and an app that trusted a stored
P&L column would carry the old number forever.

But the writer stored `entry_price` as `round(entry_price, 4)`. A derivation is
only as good as what it derives from, and the error scales with SHARE COUNT:

    A2M.AX   9,636 sh   -0.4104
    IAG.AX   6,699 sh   +0.2030
    PNI.AX   2,973 sh   +0.1134
    RHC.AX   1,194 sh   -0.0060

WHY THIS IS RESTORATION AND NOT INVENTION. `gross_pnl` was written from the
FULL-PRECISION price, so the price that produced it is recoverable exactly:

    entry = exit_price - gross_pnl / quantity

Verified against the ledger before any write: the recovered entry reproduces the
stored `gross_pnl` to the cent. Nothing is guessed and no figure is chosen.

⚠️ ONLY `entry_price` IS TOUCHED, and only on rows that fail the check. Every
other column is written back byte-identical, as the string it already was.

Dry run by default: prints the rows it WOULD change and writes nothing.
"""

from __future__ import annotations

import argparse
import csv
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from qat.config import Settings  # noqa: E402

TOLERANCE = 0.005  # half a cent


def _needs_repair(row: dict[str, str]) -> tuple[bool, float, float]:
    quantity = float(row["quantity"])
    entry = float(row["entry_price"])
    exit_price = float(row["exit_price"])
    stored = float(row["gross_pnl"])
    derived = (exit_price - entry) * quantity
    recovered = exit_price - (stored / quantity) if quantity else entry
    return abs(stored - derived) > TOLERANCE, stored - derived, recovered


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write; omit for a dry run")
    args = parser.parse_args()

    path = Path(Settings().data_dir) / "closed_trades.csv"
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)

    print(f"ledger : {path}")
    print(f"rows   : {len(rows)}")
    print()

    changed = 0
    for index, row in enumerate(rows, start=1):
        needs, gap, recovered = _needs_repair(row)
        if not needs:
            continue
        changed += 1
        was = row["entry_price"]
        row["entry_price"] = f"{recovered:.8f}".rstrip("0").rstrip(".")
        after, residual, _ = _needs_repair(row)
        print(
            f"  {index:2} {row['symbol']:<9} qty={float(row['quantity']):<9g} "
            f"entry {was} -> {row['entry_price']}   gap {gap:+.4f} -> {residual:+.4f}"
        )
        if after:
            print("     REFUSED: the repair did not close the gap on this row")
            return 1

    print()
    if not changed:
        print("nothing to repair - every row already derives its stored gross.")
        return 0
    if not args.apply:
        print(f"DRY RUN - {changed} row(s) would change. Nothing written. Re-run with --apply")
        return 0

    backup = path.with_suffix(f".csv.bak-{datetime.now(UTC):%Y%m%d-%H%M%S}-precision")
    shutil.copy2(path, backup)
    print(f"backup : {backup.name}")
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"WROTE  : {changed} row(s) repaired.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

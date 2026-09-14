"""Audit, brief §11: every retained version of the ledger, and what changed.

Read-only. Reads closed_trades.csv and every closed_trades*.bak* file in the
data folder; writes nothing.

    python ledger_versions.py <data_dir> [SYMBOL]

A backup holds the ledger as it stood when the backup was taken, so the
versions in order show each retroactive change: rows added, rows removed, and
rows whose fields changed.

ORDERED BY MODIFIED TIME, NOT BY THE NAME. A copy keeps its source's modified
time, which is the moment the ledger last changed before the copy: the time
of its CONTENT. The stamps in the names are not usable for ordering: they are
in two clocks (the 9 Sep repair backup is stamped 07:18 UTC, the app's own
backups in local time), and ordering by them put 9 Sep's versions out of
sequence. Both are printed. The current file comes last.

With SYMBOL, only that symbol's rows are shown.
"""

from __future__ import annotations

import csv
import re
import sys
from datetime import datetime
from pathlib import Path

STAMP = re.compile(r"(\d{8})-(\d{6})")
KEY_FIELDS = ("symbol", "opened_at", "closed_at")
SHOWN = (
    "quantity",
    "entry_price",
    "exit_price",
    "entry_cost",
    "exit_cost",
    "net_pnl",
    "exit_reason",
    "strategy",
    "order_id",
    "<SURPLUS VALUES>",
)


def content_time(path: Path) -> datetime:
    return datetime.fromtimestamp(path.stat().st_mtime)


def name_stamp(path: Path) -> str:
    m = STAMP.search(path.name)
    return f"{m.group(1)}-{m.group(2)}" if m else "-"


def load(path: Path) -> list[dict[str, str]]:
    """Rows as dicts. A row with MORE values than the header has columns is
    shown, not dropped: csv files the surplus under the key None, which is
    renamed here so it prints as what it is."""
    with path.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    for row in rows:
        if None in row:
            row["<SURPLUS VALUES>"] = "|".join(row.pop(None) or [])  # type: ignore[arg-type]
    return rows


def key(row: dict[str, str]) -> tuple:
    return tuple(row.get(f, "") for f in KEY_FIELDS) + (row.get("quantity", ""),)


def brief(row: dict[str, str]) -> str:
    parts = [f"{f}={row.get(f, '')}" for f in SHOWN if row.get(f, "") != ""]
    span = f"{row.get('opened_at', '')[:19]}->{row.get('closed_at', '')[:19]}"
    return f"{row.get('symbol', '?')} {span} " + " ".join(parts)


def main(data: Path, symbol: str | None) -> None:
    backups = [p for p in data.glob("closed_trades*") if p.name != "closed_trades.csv"]
    versions = sorted(backups, key=content_time) + [data / "closed_trades.csv"]
    previous: list[dict[str, str]] | None = None
    for path in versions:
        rows = load(path)
        if symbol:
            rows = [r for r in rows if r.get("symbol") == symbol]
        # The STORED column. The app recomputes P&L from the prices when it reads
        # a row (trades.py from_row), so a blank or stale stored value is not
        # the figure the app used; blanks are counted and shown.
        net = sum(float(r.get("net_pnl") or 0) for r in rows)
        blank = sum(1 for r in rows if not (r.get("net_pnl") or "").strip())
        print(
            f"=== content {content_time(path):%d %b %H:%M:%S} (name stamp {name_stamp(path)}) "
            f"{path.name}  rows {len(rows)}  stored net_pnl sum {net:,.2f} "
            f"({blank} blank)"
        )
        if previous is None:
            for r in rows:
                print(f"   {brief(r)}")
        else:
            before = {key(r): r for r in previous}
            after = {key(r): r for r in rows}
            for k in before.keys() - after.keys():
                print(f"   - REMOVED {brief(before[k])}")
            for k in after.keys() - before.keys():
                print(f"   + ADDED   {brief(after[k])}")
            for k in before.keys() & after.keys():
                changed = [
                    f"{f}: {before[k].get(f, '')} -> {after[k].get(f, '')}"
                    for f in sorted(set(before[k]) | set(after[k]))
                    if before[k].get(f, "") != after[k].get(f, "")
                ]
                if changed:
                    print(f"   ~ CHANGED {k[0]} {k[1][:19]}: " + "; ".join(changed))
        previous = rows


if __name__ == "__main__":
    main(Path(sys.argv[1]), sys.argv[2] if len(sys.argv) > 2 else None)

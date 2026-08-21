r"""Label the pre-M122 rows in closed_trades.csv with the era they belong to.

    .\.venv\Scripts\python.exe scripts\migrate_ledger_eras.py            # dry run
    .\.venv\Scripts\python.exe scripts\migrate_ledger_eras.py --apply

RUN THIS UNDER POWERSHELL, NEVER BASH. It reads and writes
%LOCALAPPDATA%\QuantAdvisoryTerminal, which the Bash sandbox serves from a
frozen snapshot without erroring.

DO NOT RUN IT WHILE THE APP IS RUNNING. TradeLedger holds this file and appends
to it on every close; rewriting it underneath a live session is how a fill goes
missing. The script refuses if it finds the process.

WHAT IT DOES, AND WHAT IT DELIBERATELY DOES NOT.

It fills in `market` and `currency` on rows that have neither, and nothing else.
Those columns arrived in M122; every row without them was written during the
Alpaca/US period that ended on 19 August 2026, so they are US/USD by
construction rather than by guess.

It does NOT delete rows and it does NOT move them to another file. They
happened, `session_check` tracks this file's sha256, and a ledger that quietly
loses rows is worse than one that mislabels them. Labelling is sufficient
because the readers are scoped now: `closed_trades(strategy, market=...)`,
`EdgeEstimator` pinned to `settings.market`, and `compute_stats` says so out
loud when a total spans two currencies.

It reports - without touching - any row whose exit is close to half its entry
with no strategy and no stop. That is the shape of an unadjusted split recorded
as a stop-out, and MNST in the live file is exactly it. Deciding whether that
row is a loss or an artefact is a judgement, not a migration.
"""

from __future__ import annotations

import argparse
import csv
import os
import shutil
import subprocess  # nosec B404 - fixed argv, no shell, no untrusted input
import sys
from datetime import datetime
from pathlib import Path

LEGACY_MARKET = "US"
CURRENT_MARKET = "ASX"
# The broker migration. The equity curve steps 101,157.17 -> 1,003,733.21
# between 2026-08-18T23:18 and 2026-08-19T23:09 UTC; anything from the 19th
# onward is the IBKR/ASX account. Overridable, because a date baked into a
# migration is a fact about ONE installation.
DEFAULT_CUTOVER = "2026-08-19"
LEGACY_CURRENCY = "USD"


def app_is_running() -> bool:
    try:
        out = subprocess.run(  # nosec B603 B607 - fixed argv
            ["tasklist", "/FI", "IMAGENAME eq QuantAdvisoryTerminal.exe"],
            capture_output=True,
            text=True,
            check=False,
        ).stdout
    except OSError:
        return False
    return "QuantAdvisoryTerminal.exe" in out


def _label_simple(path: Path, ts_column: str, cutover: str, apply: bool) -> None:
    """Backfill `market` on rows that have none, BY DATE (M127).

    Unlike `closed_trades.csv`, these two files span BOTH eras: the equity
    curve records 101,157.17 in an Alpaca account on 18 August and 1,003,733.21
    in an IBKR one on the 19th, in one continuous series. Labelling every
    unlabelled row US - which the first draft of this script did, and the dry
    run caught - would have stamped every ASX sample since the migration with
    the wrong broker, making the file confidently wrong instead of merely
    silent.

    So the cutover decides: strictly before it is US, on or after it is ASX.
    The date is printed with the row counts either side so it can be checked
    against the jump rather than taken on trust.
    """
    if not path.exists():
        print(f"\n{path.name}: not present, nothing to label")
        return

    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)

    if "market" not in fieldnames:
        fieldnames.append("market")

    before = after = 0
    for row in rows:
        if row.get("market"):
            continue
        if (row.get(ts_column) or "") < cutover:
            row["market"] = LEGACY_MARKET
            before += 1
        else:
            row["market"] = CURRENT_MARKET
            after += 1

    print(
        f"\n{path.name}: {len(rows)} row(s) | cutover {cutover} | "
        f"{before} -> {LEGACY_MARKET}, {after} -> {CURRENT_MARKET}"
    )
    if not apply or not (before or after):
        return

    backup = path.with_name(f"{path.name}.bak-{datetime.now():%Y%m%d-%H%M%S}")
    shutil.copy2(path, backup)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    print(f"  written. Backup: {backup.name}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--force", action="store_true", help="skip the running-app check")
    ap.add_argument("--cutover", default=DEFAULT_CUTOVER, help="ISO date the ASX era begins")
    args = ap.parse_args()

    data = Path(os.environ["LOCALAPPDATA"]) / "QuantAdvisoryTerminal" / "data"
    path = data / "closed_trades.csv"
    if not path.exists():
        print(f"NOT FOUND: {path}")
        return 1

    if args.apply and not args.force and app_is_running():
        print("REFUSING: QuantAdvisoryTerminal.exe is running. Close it first.")
        return 1

    # M127. The ledger was not the only file without an era. `equity_curve.csv`
    # runs straight through the broker migration - 101,157.17 on 18 August in
    # an Alpaca account, 1,003,733.21 on the 19th in an IBKR one - and
    # `risk_decisions.csv` holds US refusals that the weekly report quoted as
    # this week's ASX behaviour. Same treatment: label, never delete.
    for extra, ts_column in (("equity_curve.csv", "ts"), ("risk_decisions.csv", "timestamp")):
        _label_simple(data / extra, ts_column, args.cutover, args.apply)

    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)

    for column in ("market", "currency"):
        if column not in fieldnames:
            fieldnames.append(column)

    touched, suspicious = [], []
    for row in rows:
        if not row.get("market") and not row.get("currency"):
            row["market"] = LEGACY_MARKET
            row["currency"] = LEGACY_CURRENCY
            touched.append(row.get("symbol", "?"))
        try:
            entry, exit_ = float(row["entry_price"]), float(row["exit_price"])
        except (KeyError, TypeError, ValueError):
            continue
        halved = entry > 0 and abs(exit_ / entry - 0.5) < 0.05
        if halved and not row.get("strategy") and not row.get("stop_price"):
            suspicious.append((row.get("symbol", "?"), entry, exit_))

    print(f"file    : {path}")
    print(f"rows    : {len(rows)}")
    print(f"labelled: {len(touched)} -> {LEGACY_MARKET}/{LEGACY_CURRENCY} {touched}")
    if suspicious:
        print("\nNOT TOUCHED - these look like unadjusted splits, not trades:")
        for symbol, entry, exit_ in suspicious:
            print(f"    {symbol:8} entry {entry:.4f} -> exit {exit_:.4f} ({exit_ / entry:.1%})")
        print("    Decide these by hand; a migration must not rewrite an outcome.")

    if not args.apply:
        print("\nDRY RUN - nothing written. Re-run with --apply.")
        return 0

    backup = path.with_name(f"closed_trades.csv.bak-{datetime.now():%Y%m%d-%H%M%S}")
    shutil.copy2(path, backup)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nWRITTEN. Backup: {backup}")
    print("closed_trades.csv sha256 will change - that is expected, and session_check")
    print("will report the new value from the next run.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

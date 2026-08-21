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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--force", action="store_true", help="skip the running-app check")
    args = ap.parse_args()

    data = Path(os.environ["LOCALAPPDATA"]) / "QuantAdvisoryTerminal" / "data"
    path = data / "closed_trades.csv"
    if not path.exists():
        print(f"NOT FOUND: {path}")
        return 1

    if args.apply and not args.force and app_is_running():
        print("REFUSING: QuantAdvisoryTerminal.exe is running. Close it first.")
        return 1

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

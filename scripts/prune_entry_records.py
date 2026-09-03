r"""Remove named symbols from `open_position_entries.json`, with a dry run.

    .\.venv\Scripts\python.exe scripts\prune_entry_records.py BHP.AX
    .\.venv\Scripts\python.exe scripts\prune_entry_records.py BHP.AX --apply

⚠️ RUN THIS FROM POWERSHELL. It builds `Settings()`, which loads the live data
directory's .env whether or not this script mentions it.

⚠️ REFUSES WHILE THE APP IS RUNNING. The application rewrites this file from its
own in-memory state, so an edit underneath a live process is silently discarded -
or worse, half-applied.

WHY THIS EXISTS. On 3 September an entry record was written for a BHP.AX order
that TWS staged and never transmitted: the app booked 790 shares the broker never
held (`oms.py:861` records the ORDER's size, not the amount executed). The
reconciliation rail caught the holding itself and the kill switch halted flow -
but the ENTRY RECORD is a separate file, was never rewritten, and survived both
the stand-down and the restart. Ten records against nine positions.

⚠️ IT IS THE LATER HAZARD THAT MATTERS, not the current state. An entry record is
inert while its symbol is not held: reconciliation is authoritative for holdings,
and the trade ledger correctly restored nine lots. But the record carries the
entry PRICE and DATE that the minimum hold, the time stop and the stop re-arm are
all computed from. Buy that symbol again and it inherits a basis nobody paid, on
a clock that started the day of a trade that never happened.

Named symbols rather than a broker diff, deliberately: the operator says what is
wrong and the script shows exactly what it would remove. A script that decides
for itself which records are phantom would need to be right about the broker,
and being wrong there deletes the basis of a real position.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from qat.config import Settings  # noqa: E402


def _app_is_running() -> bool:
    """True if a QuantAdvisoryTerminal process is alive.

    psutil is not a dependency here, so this shells out to the platform's own
    task list rather than adding one for a single check.
    """
    import os
    import subprocess  # nosec B404 - fixed argv, absolute path, no shell, no user input

    # Absolute path, not a bare name: a bare "tasklist" resolves through PATH,
    # and this is the check that decides whether a write to live trading data is
    # safe. The one place a spoofed executable would matter is the one place it
    # must not be possible.
    tasklist = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "tasklist.exe"
    if not tasklist.exists():
        print(f"  could not find {tasklist} - refusing")
        return True

    try:
        out = subprocess.run(  # nosec B603 - absolute path, fixed argv, shell=False
            [str(tasklist), "/FI", "IMAGENAME eq QuantAdvisoryTerminal.exe"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except Exception:  # noqa: BLE001 - a failed check must not silently permit
        print("  could not determine whether the app is running - refusing")
        return True
    return "QuantAdvisoryTerminal.exe" in (out.stdout or "")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("symbols", nargs="+", help="symbols to remove, e.g. BHP.AX")
    parser.add_argument("--apply", action="store_true", help="write the change")
    args = parser.parse_args()

    settings = Settings()
    path = Path(settings.data_dir) / "open_position_entries.json"
    print(f"file    : {path}")
    if not path.exists():
        print("  no entry-records file - nothing to do")
        return 0

    records = json.loads(path.read_text(encoding="utf-8"))
    print(f"records : {len(records)}  ->  {', '.join(sorted(records))}")

    missing = [s for s in args.symbols if s not in records]
    for symbol in missing:
        print(f"  NOT PRESENT: {symbol}")
    present = [s for s in args.symbols if s in records]
    if not present:
        print("\nNothing to remove.")
        return 0

    print("\nWould remove:")
    for symbol in present:
        print(f"  {symbol}: {json.dumps(records[symbol], default=str)}")

    remaining = {k: v for k, v in records.items() if k not in present}
    print(f"\nafter   : {len(remaining)}  ->  {', '.join(sorted(remaining))}")

    if not args.apply:
        print("\nDRY RUN - nothing was changed. Re-run with --apply.")
        return 0

    # ⚠️ The running-app check goes here, not at the top: a dry run is a read and
    # is safe at any time. Only the write needs the app down.
    if _app_is_running():
        print("\n  REFUSED: the app is running. Close it first - it rewrites this")
        print("           file from its own state and would discard the edit.")
        return 1

    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    backup = path.with_suffix(f".json.bak-{stamp}")
    shutil.copy2(path, backup)
    print(f"\nbackup  : {backup}")

    path.write_text(json.dumps(remaining, indent=2, default=str) + "\n", encoding="utf-8")

    # Read back rather than trust the write - the same discipline the deploy
    # script applies to the installed binary.
    verify = json.loads(path.read_text(encoding="utf-8"))
    if any(s in verify for s in present) or len(verify) != len(remaining):
        print("  ⚠️ READ-BACK FAILED. Restore from the backup above.")
        return 1
    print(f"REMOVED {', '.join(present)}. {len(verify)} record(s) remain, verified on disk.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

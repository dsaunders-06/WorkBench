"""Back up the live data directory before a deploy.

**RUN THIS THROUGH THE POWERSHELL TOOL, NEVER THROUGH BASH.** Measured on
13 August: run from Bash, this script copied 20 files, printed success, and
wrote NOTHING to the real filesystem - the whole operation landed in a
sandboxed overlay of `%LOCALAPPDATA%` that only Bash can see. The deploy nearly
proceeded on a backup that did not exist, with the trial's entire evidence base
unprotected.

The sandbox is per-FILE and applies to writes as well as reads, so a script
cannot detect it from the inside: from within the overlay the copy is there.
**Verify the backup from PowerShell afterwards** - file count, and a hash of
`closed_trades.csv` against the live one. That check is the only thing that
distinguishes a backup from a convincing report of one.

    Set-Location "C:\\Claude Programming"
    & ".\\.venv\\Scripts\\python.exe" scripts\\backup_data_dir.py --label PRE-M88-DEPLOY
    & ".\\.venv\\Scripts\\python.exe" scripts\\backup_data_dir.py --label PRE-M88-DEPLOY --apply

**Dry run by default.** It prints what it would copy and stops; `--apply` is
the only thing that writes. Every deploy so far has made this backup by hand,
which is how a step gets skipped on the one night it mattered - and the thing
being copied is the trial's entire evidence base: the closed trades, the entry
records, the decision journal and the risk decisions.

It refuses to run while the application is up. A half-copied ledger is worse
than no copy, because it looks like a backup.

The naming follows the convention the previous deploys used, so the backups
sort chronologically beside each other:

    data-backup-<yyyyMMdd-HHmmss>-<LABEL>
"""

from __future__ import annotations

import argparse
import os
import shutil
from datetime import datetime
from pathlib import Path


def _data_dir() -> Path:
    """The LIVE data directory.

    Deliberately read from the environment rather than from Settings: importing
    the application to find its own data directory would be a heavier
    dependency than a deploy script should carry, and this path has been stable
    since the app was installed.
    """
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        raise RuntimeError("LOCALAPPDATA is not set - run this from a normal Windows session")
    return Path(local) / "QuantAdvisoryTerminal" / "data"


def _app_is_running() -> bool:
    """Whether QuantAdvisoryTerminal has a live process.

    A ledger held open in append mode can be copied mid-write, and the copy
    would be silently short. Checked with `tasklist` rather than psutil to keep
    this script dependency-free.
    """
    import subprocess  # nosec B404 - fixed argv, no user input

    try:
        result = subprocess.run(  # nosec B603 B607
            ["tasklist", "/FI", "IMAGENAME eq QuantAdvisoryTerminal.exe", "/NH"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return "QuantAdvisoryTerminal.exe" in result.stdout


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", required=True, help="e.g. PRE-M88-DEPLOY")
    parser.add_argument("--apply", action="store_true", help="actually copy; omit for a dry run")
    args = parser.parse_args()

    source = _data_dir()
    if not source.is_dir():
        print(f"data directory not found: {source}")
        return 1

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = source.parent / f"data-backup-{stamp}-{args.label}"

    files = sorted(p for p in source.rglob("*") if p.is_file())
    total = sum(p.stat().st_size for p in files)

    print(f"source : {source}")
    print(f"target : {target}")
    print(f"files  : {len(files)}  ({total / 1_048_576:.1f} MB)")
    for name in ("closed_trades.csv", "open_position_entries.json", "decision_journal.csv"):
        candidate = source / name
        mark = f"{candidate.stat().st_size:,} bytes" if candidate.exists() else "ABSENT"
        print(f"    {name:<30} {mark}")

    if _app_is_running():
        print()
        print("REFUSING: QuantAdvisoryTerminal.exe is running. Close it first - the ledger is")
        print("held open in append mode, and a copy taken mid-write is silently short.")
        return 2

    if not args.apply:
        print()
        print("Dry run. Nothing was written. Re-run with --apply to copy.")
        return 0

    shutil.copytree(source, target)
    copied = sorted(p for p in target.rglob("*") if p.is_file())
    print()
    print(f"copied {len(copied)} files to {target}")
    if len(copied) != len(files):
        print(f"WARNING: source had {len(files)} files, backup has {len(copied)}")
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

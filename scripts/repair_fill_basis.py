r"""Rewrite entry prices and costs onto the true fill basis (M175).

    .\.venv\Scripts\python.exe scripts/repair_fill_basis.py            # dry run
    .\.venv\Scripts\python.exe scripts/repair_fill_basis.py --apply    # write

⚠️ POWERSHELL ONLY - it builds Settings() and reads/writes the live data dir.
⚠️ THE APP MUST BE CLOSED, and M175 must be the build launched next: an older
   build's M65 re-inflates the open records at its first startup.

See `qat.domain.performance.fill_basis_repair` for what is changed and on what
evidence. Dry run prints every row and record, before and after, runs the
same `audit_closed_trades` gate `--apply` must pass (on a copy written to a
temp dir OUTSIDE the data dir, then deleted), exits 1 if it fails, and writes
nothing in the data dir.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from qat.config import Settings  # noqa: E402
from qat.domain.backtester.costs import CostModel  # noqa: E402
from qat.domain.performance.fill_basis_repair import (  # noqa: E402
    RowRepair,
    SelfCheckFailed,
    parse_logged_buys,
    parse_m65_corrections,
    prior_repair,
    read_log_messages,
    repair_closed_rows,
    repair_open_records,
)
from qat.domain.performance.trades import _FIELDS, audit_closed_trades  # noqa: E402


def _app_is_running() -> bool:
    """Same check as prune_entry_records.py: absolute tasklist path, and a
    check that cannot run counts as RUNNING."""
    import subprocess  # nosec B404 - fixed argv, absolute path, no shell, no user input

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
    if out.returncode != 0:
        # Empty stdout from a tasklist that FAILED is not "no such process".
        print(f"  tasklist failed (exit {out.returncode}): {(out.stderr or '').strip()} - refusing")
        return True
    return "QuantAdvisoryTerminal.exe" in (out.stdout or "")


def _remove(*paths: Path) -> list[Path]:
    """Delete each path; return the ones that could not be deleted."""
    stuck: list[Path] = []
    for path in paths:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            stuck.append(path)
    return stuck


def _abandon(backups: list[Path], *temps: Path) -> None:
    """Undo a run that stopped BEFORE any original was replaced: its temps and
    its backups go. A backup left behind would make `prior_repair` report a
    repair that never happened, and refuse every later run."""
    stuck = _remove(*temps, *backups)
    if not stuck:
        print("The originals are intact, and this run's backups were removed.")
        return
    print(
        "The originals are intact, but these files could not be deleted - delete these by "
        "hand before re-running (a leftover backup makes the script refuse):"
    )
    for path in stuck:
        print(f"  {path}")


def _partial(ledger: Path, entries: Path, entries_tmp: Path, stamp: str, why: str) -> None:
    print(
        f"PARTIAL: {ledger.name} was replaced but {entries.name} was NOT ({why}). "
        f"The repaired records are in {entries_tmp} - move it over {entries} by hand, "
        f"or restore both files from the .bak-fill-basis-{stamp} backups."
    )


def _write_ledger(path: Path, repairs: list[RowRepair]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(_FIELDS))
        writer.writeheader()
        writer.writerows(r.after.as_row() for r in repairs)


def _dry_run_audit(repairs: list[RowRepair]) -> int:
    """The same audit gate `--apply` passes through, run on a copy written
    OUTSIDE the data dir - so a repair `--apply` would refuse is refused by
    the dry run too, and the data dir is never touched."""
    scratch = Path(tempfile.mkdtemp(prefix="qat-fill-basis-"))
    try:
        probe = scratch / "closed_trades.csv"
        _write_ledger(probe, repairs)
        findings = audit_closed_trades(probe)
    except Exception as exc:  # noqa: BLE001 - a gate that cannot run has not passed
        print(f"\naudit: COULD NOT RUN ({exc!r})")
        print("DRY RUN - nothing written. --apply would not get past this either.")
        return 1
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    if findings:
        print(f"\naudit: FAILED - {len(findings)} finding(s) on the repaired ledger:")
        for line in findings:
            print(f"  {line}")
        print("DRY RUN - nothing written. --apply would refuse on the same audit.")
        return 1
    print("\naudit: clean")
    print("\nDRY RUN - nothing written. Re-run with --apply.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write; omit for a dry run")
    args = parser.parse_args()

    if _app_is_running():
        print("REFUSING: QuantAdvisoryTerminal.exe is running. Close it first.")
        return 1

    settings = Settings()
    data = Path(settings.data_dir)
    ledger = data / "closed_trades.csv"
    entries = data / "open_position_entries.json"

    already = prior_repair(data)
    if already is not None:
        print(f"REFUSING: {already}.")
        print(
            "This script runs ONCE. A second run would corrupt the fragment rows (their "
            "evidence no longer matches, so they would be charged whole floors) and "
            "re-deflate prices that are already fills. Nothing written."
        )
        return 1

    costs = CostModel.from_settings(settings)
    print(f"data    : {data}")
    print(
        f"profile : {costs.commission_bps} bp, floor {costs.min_commission}, "
        f"third-party {costs.third_party_bps} bp"
    )

    messages = read_log_messages(data / "logs")
    corrections = parse_m65_corrections(messages)
    buys = parse_logged_buys(messages, settings.market)
    print(f"evidence: {len(corrections)} symbol(s) with M65 lines, {len(buys)} logged buy order(s)")

    with ledger.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    records = json.loads(entries.read_text(encoding="utf-8"))

    try:
        repairs = repair_closed_rows(rows, corrections, buys, costs)
        repaired_records, changes, left_for_m65 = repair_open_records(
            records, corrections, buys, costs
        )
    except SelfCheckFailed as exc:
        print(f"\nSELF-CHECK FAILED - nothing written.\n  {exc}")
        return 1
    except ValueError as exc:
        # An unparseable row, or one lot carrying two entry prices: the ledger
        # is not in a shape this repair can reason about.
        print(f"\nREFUSING - nothing written.\n  {exc}")
        return 1

    print(f"\n=== closed_trades.csv: {len(repairs)} row(s) ===")
    print(
        f"{'#':>2} {'symbol':7} {'qty':>7} {'entry before':>13} {'entry after':>13} "
        f"{'costs before':>12} {'costs after':>11} {'net before':>11} {'net after':>11} "
        f"{'R before':>8} {'R after':>8} {'slip after':>10}  evidence"
    )
    for r in repairs:
        b, a = r.before, r.after
        ev = r.evidence.source if r.evidence else "NO M65 LINE - price kept"
        flag = "  [FRAGMENT: no floor]" if r.fragment else ""
        slip = f"{a.entry_slippage:+.4f}" if a.entry_slippage is not None else "-"
        rb = f"{b.r_multiple:.4f}" if b.r_multiple is not None else "-"
        ra = f"{a.r_multiple:.4f}" if a.r_multiple is not None else "-"
        print(
            f"{r.index + 2:>2} {b.symbol:7} {b.quantity:>7g} {b.entry_price:>13.8f} "
            f"{a.entry_price:>13.8f} {b.costs:>12.2f} {a.costs:>11.2f} {b.net_pnl:>11.2f} "
            f"{a.net_pnl:>11.2f} {rb:>8} {ra:>8} {slip:>10}  {ev}{flag}"
        )
    print(
        f"   net P&L, all rows: {sum(r.before.net_pnl for r in repairs):,.2f} -> "
        f"{sum(r.after.net_pnl for r in repairs):,.2f}"
    )

    print(f"\n=== open_position_entries.json: {len(records)} record(s) ===")
    print(f" corrected from a logged fill, stamped \"fill\" ({len(changes)}):")
    for c in changes:
        print(f"   {c.symbol:7} {c.before:>13.8f} -> {c.after:>13.8f}  {c.evidence.source}")
    print(
        f" left for M65 at launch - no logged fill, so NOT changed here; the M175 build "
        f"derives these from the broker's real quantity ({len(left_for_m65)}):"
    )
    for c in left_for_m65:
        print(f"   {c.symbol:7} {c.before:>13.8f}  kept (the formula alone would give {c.after:.8f})")
    untouched = sorted(set(records) - {c.symbol for c in (*changes, *left_for_m65)})
    print(f" unchanged - no M65 line ({len(untouched)}):")
    for symbol in untouched:
        print(f"   {symbol:7}")

    if not args.apply:
        return _dry_run_audit(repairs)

    # Both files are written to temps beside the originals and the ledger temp
    # is audited BEFORE either original is touched: nothing is replaced unless
    # everything is ready to be. The backups are taken after that and before
    # the first replace - so a backup still exists before anything changes,
    # and a run that fails here leaves no backup behind for `prior_repair` to
    # misread as a completed repair.
    ledger_tmp = ledger.with_name(f"{ledger.name}.tmp-{os.getpid()}")
    entries_tmp = entries.with_name(f"{entries.name}.tmp-{os.getpid()}")
    try:
        _write_ledger(ledger_tmp, repairs)
        entries_tmp.write_text(json.dumps(repaired_records, indent=2), encoding="utf-8")
        findings = audit_closed_trades(ledger_tmp)
    except Exception as exc:  # noqa: BLE001 - any failure here must replace nothing
        _remove(ledger_tmp, entries_tmp)
        print(f"WRITE FAILED - nothing replaced: {exc!r}")
        return 1
    if findings:
        _remove(ledger_tmp, entries_tmp)
        print("AUDIT FAILED on the rewritten ledger - nothing replaced:")
        for line in findings:
            print(f"  {line}")
        return 1

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    # Every backup this run MAY have created, listed before its copy starts: a
    # half-written backup is this run's too, and must not outlive a failure.
    backups: list[Path] = []
    undoing = False  # set once this run is KNOWN to have replaced nothing
    try:
        try:
            for path in (ledger, entries):
                backup = path.with_name(f"{path.name}.bak-fill-basis-{stamp}")
                backups.append(backup)
                shutil.copy2(path, backup)
                print(f"backup  : {backup}")
        except Exception as exc:  # noqa: BLE001 - no backup, no replace
            undoing = True
            print(f"BACKUP FAILED - nothing replaced: {exc!r}")
            _abandon(backups, ledger_tmp, entries_tmp)
            return 1
        try:
            os.replace(ledger_tmp, ledger)
        except OSError as exc:
            undoing = True
            print(f"REPLACE FAILED - nothing replaced: {exc!r}")
            _abandon(backups, ledger_tmp, entries_tmp)
            return 1
    except KeyboardInterrupt:
        # `os.replace` is atomic: while the ledger temp still exists, no
        # original has been touched and this run can be undone completely.
        # (`undoing`: an interrupt inside `_abandon` may land after the temp
        # is gone, and must not be read as a replace that happened.)
        if undoing or ledger_tmp.exists():
            print("\nINTERRUPTED - nothing replaced.")
            _abandon(backups, ledger_tmp, entries_tmp)
        else:
            _partial(ledger, entries, entries_tmp, stamp, "interrupted")
        raise
    try:
        os.replace(entries_tmp, entries)
    except OSError as exc:
        _partial(ledger, entries, entries_tmp, stamp, repr(exc))
        return 1
    print(
        f"\nWRITTEN. {len(repairs)} row(s) rewritten, {len(changes)} record(s) corrected, "
        f"{len(left_for_m65)} left for M65 at launch."
    )
    print("Deploy M175 BEFORE launching - an older build re-inflates the records.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

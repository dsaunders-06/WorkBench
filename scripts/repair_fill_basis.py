r"""Rewrite entry prices and costs onto the true fill basis (M175).

    .\.venv\Scripts\python.exe scripts/repair_fill_basis.py            # dry run
    .\.venv\Scripts\python.exe scripts/repair_fill_basis.py --apply    # write

⚠️ POWERSHELL ONLY - it builds Settings() and reads/writes the live data dir.
⚠️ THE APP MUST BE CLOSED, and M175 must be the build launched next: an older
   build's M65 re-inflates the open records at its first startup.

See `qat.domain.performance.fill_basis_repair` for what is changed and on what
evidence. Dry run prints every row and record, before and after, and writes
nothing.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from qat.config import Settings  # noqa: E402
from qat.domain.backtester.costs import CostModel  # noqa: E402
from qat.domain.performance.fill_basis_repair import (  # noqa: E402
    SelfCheckFailed,
    parse_logged_buys,
    parse_m65_corrections,
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
    return "QuantAdvisoryTerminal.exe" in (out.stdout or "")


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
        repaired_records, changes = repair_open_records(records, corrections, buys, costs)
    except SelfCheckFailed as exc:
        print(f"\nSELF-CHECK FAILED - nothing written.\n  {exc}")
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

    print(f"\n=== open_position_entries.json: {len(changes)} of {len(records)} record(s) ===")
    for c in changes:
        print(f"   {c.symbol:7} {c.before:>13.8f} -> {c.after:>13.8f}  {c.evidence.source}")
    for symbol in sorted(set(records) - {c.symbol for c in changes}):
        print(f"   {symbol:7} unchanged - no M65 line")

    if not args.apply:
        print("\nDRY RUN - nothing written. Re-run with --apply.")
        return 0

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    for path in (ledger, entries):
        backup = path.with_name(f"{path.name}.bak-fill-basis-{stamp}")
        shutil.copy2(path, backup)
        print(f"backup  : {backup}")

    tmp = ledger.with_name(f"{ledger.name}.tmp-{os.getpid()}")
    with tmp.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(_FIELDS))
        writer.writeheader()
        writer.writerows(r.after.as_row() for r in repairs)
    findings = audit_closed_trades(tmp)
    if findings:
        tmp.unlink()
        print("AUDIT FAILED on the rewritten ledger - nothing replaced:")
        for line in findings:
            print(f"  {line}")
        return 1
    os.replace(tmp, ledger)
    entries.write_text(json.dumps(repaired_records, indent=2), encoding="utf-8")
    print(f"\nWRITTEN. {len(repairs)} row(s) rewritten, {len(changes)} record(s) corrected.")
    print("Deploy M175 BEFORE launching - an older build re-inflates the records.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

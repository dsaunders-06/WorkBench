"""Repair the 26 August LOV.AX exit that only 374 of 3,217 shares reached.

    Set-Location "C:\\Claude Programming"
    & ".\\.venv\\Scripts\\python.exe" scripts\\repair_lov_partial_absorb.py            # DRY RUN
    & ".\\.venv\\Scripts\\python.exe" scripts\\repair_lov_partial_absorb.py --apply    # writes

**RUN THROUGH POWERSHELL, NEVER BASH.** It reads the live data directory, and
the Bash sandbox serves a frozen snapshot without erroring.

## What happened

LOV.AX order 1216552509 filled 3,217 shares in 183 executions on 26 August.
`from_ib_fill` supplied `execution.shares` (per-execution) while
`OMS._is_foreign_unrecorded` compared it against a stored CUMULATIVE, so only
executions setting a new running maximum were absorbed: 10, 15, 26, 323 = 374.
The remaining 2,843 shares never reached `closed_trades.csv`, and the kill
switch tripped on `tracked=2843 broker=0`.

## ⚠️ PREFER THE AUTOMATIC PATH. This script is the FALLBACK.

Once the absorb fix is deployed, a restart re-reads the executions, finds
`prior.quantity` 374 against a cumulative 3,217, and absorbs the 2,843 delta
through the REAL code path - producing a properly derived row rather than one
this script computed. That is strictly better evidence.

**But it only works while IBKR still returns the executions, and retention was
MEASURED on 26 August at 13:14 as SAME-DAY ONLY** - `reqExecutions` returned
183 executions, all from 26 August, and none of the 25 August orders still
listed in `absorbed_fills.json`. So the automatic path must be taken by
restarting on the SAME DAY as the fill. After that it is gone and this script
is the only route.

## ⚠️ THE APP MUST BE STOPPED

`OMS._save_fill_state()` rewrites `absorbed_fills.json` after every absorb
pass. Editing it under a running app is overwritten within 300 seconds.

## What it writes, and why both halves are required

1. One row appended to `closed_trades.csv` for the unabsorbed 2,843 shares.
2. `absorbed_fills.json`'s record for order 1216552509 set to quantity 3217.

Half 2 is what makes this IDEMPOTENT. Without it, a later absorb pass sees
`prior.quantity` 374 against a cumulative 3,217 and books the 2,843 a SECOND
time - a duplicate closed trade, which is the failure mode `_save_fill_state`'s
own comment calls worse than the one it replaced, because a duplicate is what
trips the kill switch.

Backs both files up before touching them.
"""

from __future__ import annotations

import argparse
import csv
import json
import pathlib
import shutil
import sys
from datetime import datetime

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from qat.config import Settings  # noqa: E402

ORDER_ID = "1216552509"
SYMBOL = "LOV.AX"
FILLED_TOTAL = 3217.0
EXIT_PRICE = 28.45
STAMP = datetime.now().strftime("%Y%m%d-%H%M%S")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write; otherwise dry run")
    args = parser.parse_args()

    data = pathlib.Path(Settings().data_dir)
    trades_path = data / "closed_trades.csv"
    absorbed_path = data / "absorbed_fills.json"
    print(f"data dir: {data}")
    print(f"mode    : {'APPLY - WILL WRITE' if args.apply else 'DRY RUN - writes nothing'}\n")

    rows = list(csv.DictReader(trades_path.open(encoding="utf-8")))
    lov = [r for r in rows if r["symbol"] == SYMBOL]
    booked = sum(float(r["quantity"]) for r in lov)
    missing = FILLED_TOTAL - booked

    print(f"{SYMBOL} rows in closed_trades.csv : {len(lov)}")
    print(f"shares already booked             : {booked:,.0f}")
    print(f"shares actually filled            : {FILLED_TOTAL:,.0f}")
    print(f"MISSING                           : {missing:,.0f}")

    if missing <= 0.5:
        print("\nNothing to repair - the ledger already carries the full quantity.")
        return 0

    absorbed = json.loads(absorbed_path.read_text(encoding="utf-8"))
    record = absorbed.get("absorbed", {}).get(ORDER_ID)
    print(f"\nabsorbed_fills[{ORDER_ID}].quantity : {record and record.get('quantity')}")

    if not lov:
        print("\nNo LOV row to model the repair on - refusing to invent one.")
        return 1

    # Model the new row on the LARGEST existing one so every derived column
    # (strategy, regime, costs, r_multiple basis) carries the same provenance
    # rather than being invented here.
    template = max(lov, key=lambda r: float(r["quantity"]))
    entry = float(template["entry_price"])
    risk_per_share = float(template["risk_per_share"])
    gross = (EXIT_PRICE - entry) * missing

    new_row = dict(template)
    new_row["quantity"] = f"{missing}"
    new_row["gross_pnl"] = f"{gross:.2f}"
    # Costs are NOT scaled from the template: the template's entry_cost and
    # exit_cost are that fill's own commissions, and IBKR's commission for the
    # unabsorbed portion is not knowable from here. Left at the template's
    # values would understate them; zeroed would overstate net P&L. Recorded as
    # empty so the row is honestly incomplete rather than confidently wrong.
    new_row["entry_cost"] = ""
    new_row["exit_cost"] = ""
    new_row["net_pnl"] = ""
    new_row["r_multiple"] = ""
    new_row["exit_reason"] = "target (ledger repair 26 Aug - unabsorbed remainder)"

    print("\nrow that WOULD be appended:")
    for key in (
        "opened_at",
        "closed_at",
        "symbol",
        "quantity",
        "entry_price",
        "exit_price",
        "gross_pnl",
        "exit_reason",
    ):
        print(f"   {key:<14} {new_row.get(key)}")
    print(
        f"\n   gross P&L on the repair : {gross:,.2f} "
        f"({missing:,.0f} x ({EXIT_PRICE} - {entry:.4f}))"
    )
    print(f"   risk_per_share on file  : {risk_per_share}")

    print(
        f"\nabsorbed_fills[{ORDER_ID}].quantity would become {FILLED_TOTAL:,.0f} "
        "(so a later pass finds no delta and cannot double-count)"
    )

    if not args.apply:
        print("\nDRY RUN - nothing written. Re-run with --apply to write.")
        print(
            "⚠️ STOP THE APP FIRST: _save_fill_state() rewrites absorbed_fills.json "
            "after every absorb pass."
        )
        return 0

    shutil.copy2(trades_path, trades_path.with_suffix(f".csv.bak-{STAMP}-PRE-LOV-REPAIR"))
    shutil.copy2(absorbed_path, absorbed_path.with_suffix(f".json.bak-{STAMP}-PRE-LOV-REPAIR"))

    with trades_path.open("a", newline="", encoding="utf-8") as handle:
        csv.DictWriter(handle, fieldnames=rows[0].keys()).writerow(new_row)

    absorbed.setdefault("absorbed", {}).setdefault(ORDER_ID, {})
    absorbed["absorbed"][ORDER_ID]["quantity"] = FILLED_TOTAL
    absorbed["absorbed"][ORDER_ID]["quantity_known"] = True
    absorbed_path.write_text(json.dumps(absorbed, indent=2), encoding="utf-8")

    print("\nWRITTEN. Backups kept alongside both files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

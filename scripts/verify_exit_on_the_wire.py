"""Does the ledger's exit price match what IBKR actually executed? (item 55/M147)

    Set-Location "C:\\Claude Programming"
    & ".\\.venv\\Scripts\\python.exe" scripts\\verify_exit_on_the_wire.py --symbol LOV.AX
    & ".\\.venv\\Scripts\\python.exe" scripts\\verify_exit_on_the_wire.py          # every symbol

**RUN THROUGH POWERSHELL, NEVER BASH.** It constructs `Settings()`, which loads
the `.env` under `%LOCALAPPDATA%\\QuantAdvisoryTerminal` whether or not this
docstring mentions it, and the Bash sandbox serves a frozen snapshot without
erroring.

## Why this exists

M147 made `from_ib_fill` carry the order's CUMULATIVE quantity AND its
cumulative average price, after 179 of 183 executions on the first-ever exit
never reached the ledger. The QUANTITY half has been confirmed - the LOV repair
recovered all 3,217 shares. **The PRICE half has never been confirmed against a
real wire**, because every one of those 183 executions filled at exactly 28.45,
so a blended average and a single price are the same number and the two
readings are indistinguishable. Precisely the condition that hid the quantity
bug for months.

The first exit that fills at more than one price is the first real test, and
this is the cross-check to run against it.

⚠️⚠️ **RUN IT THE SAME DAY. IBKR EXECUTION RETENTION IS SAME-DAY ONLY, and that
is measured rather than assumed** - at 13:14 on 26 August
`reqExecutions(ExecutionFilter())` returned 183 executions, every one from that
day, and none of the 25 August orders `absorbed_fills.json` still listed. **The
wire evidence for an exit is unrecoverable after the close.** Confirmed again on
27 August, when this script was first run and correctly returned nothing for the
previous day's LOV exit.

## What it does, and what it refuses to do

Reads IBKR's own execution records read-only on `PROBE_CLIENT_ID`, groups them
by `permId`, and prints three numbers per order that should agree:

* **VWAP** - `sum(shares x price) / sum(shares)`, derived here from the
  individual executions;
* **IBKR's own `avgPrice`** - the cumulative average on the LAST execution,
  which is what `from_ib_fill` now carries;
* **the ledger's `exit_price`** - what `closed_trades.csv` recorded.

The first two are two independent derivations of the same quantity. If THEY
disagree, this script's arithmetic is wrong and nothing below it should be
believed - which is why both are printed rather than one.

**It writes nothing, anywhere.** `Settings(data_dir=...)` is pointed at a
throwaway directory so that is structural rather than a promise, exactly as
`ibkr_probe` does it, and the ledger is opened for reading only. It connects
with `readonly=True` on a clientId of its own, so it cannot displace the running
application off its Gateway.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import sys
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from qat.config import Settings  # noqa: E402
from qat.data.broker.ib_probe import check_paper_account, connection_target  # noqa: E402

# Two prices this far apart or closer are the same price. An ASX tick is half a
# cent, so this is below one tick and cannot absorb a real disagreement.
_TOLERANCE = 0.001


def _connection_settings() -> Settings:
    """The operator's real host/port, with `data_dir` pointed somewhere harmless.

    `Settings().data_dir` is the LIVE data directory and `conftest` protects
    only tests. Passing a throwaway directory is what makes "this script writes
    nothing there" a property of the code rather than a claim in a docstring.
    """
    return Settings(data_dir=tempfile.mkdtemp(prefix="qat-wire-"))


def _ledger_rows(symbol: str | None) -> list[dict[str, str]]:
    """The recorded exits, READ ONLY.

    A second `Settings()` deliberately, and only for the path: the connection
    above must not be able to reach the live directory even by accident, and
    one object serving both purposes is how that guarantee gets lost later.
    """
    path = Path(Settings().data_dir) / "closed_trades.csv"
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if symbol:
        rows = [row for row in rows if row.get("symbol") == symbol]
    return rows


def _report(executions: list[Any], rows: list[dict[str, str]]) -> str:
    """`Any` deliberately: these are ib_async `Fill`/`Execution` objects, which
    are not imported at module scope so the script stays importable without a
    Gateway. Typing them as `object` and reaching through `type: ignore` on
    every attribute was worse - it suppressed the very errors that would catch
    a renamed field."""
    by_order: dict[str, list[Any]] = defaultdict(list)
    for fill in executions:
        execution = fill.execution
        by_order[str(execution.permId)].append(execution)

    out: list[str] = []
    if not by_order:
        out.append("no executions returned - nothing to check")
        out.append("")
        out.append(
            "⚠️ This is NOT evidence that nothing filled. IBKR retains executions "
            "for a bounded window and a filter can exclude them, so an empty "
            "result means THIS QUERY saw none, not that none exist."
        )
        return "\n".join(out)

    for perm_id, group in sorted(by_order.items()):
        group.sort(key=lambda e: (e.time, e.execId))
        symbol = group[0].contract.symbol if hasattr(group[0], "contract") else "?"
        shares = sum(float(e.shares) for e in group)
        notional = sum(float(e.shares) * float(e.price) for e in group)
        vwap = notional / shares if shares else 0.0
        last = group[-1]
        ib_avg = float(last.avgPrice)
        cum_qty = float(last.cumQty)
        distinct = sorted({round(float(e.price), 4) for e in group})

        out.append(f"order permId {perm_id}  {symbol}  {group[0].side}")
        out.append(f"  executions            : {len(group)}")
        out.append(f"  distinct prices       : {len(distinct)}  {distinct[:8]}")
        out.append(f"  shares summed         : {shares:,.0f}")
        out.append(f"  IBKR final cumQty     : {cum_qty:,.0f}")
        out.append(f"  VWAP (derived here)   : {vwap:.6f}")
        out.append(f"  IBKR avgPrice (last)  : {ib_avg:.6f}")

        if abs(shares - cum_qty) > 1e-6:
            out.append(
                f"  ⚠️ SHARES DISAGREE with cumQty by {shares - cum_qty:+,.0f} - "
                f"this query did not see every execution of the order, so the "
                f"price comparison below is measuring a SUBSET and must not be quoted"
            )
        if abs(vwap - ib_avg) > _TOLERANCE:
            out.append(
                f"  ⚠️ THE TWO DERIVATIONS DISAGREE by {vwap - ib_avg:+.6f} - "
                f"this script's arithmetic is wrong, stop here"
            )

        if len(distinct) == 1:
            out.append(
                "  ⚠️ ONE price across every execution, so a blended average and a "
                "single price are the SAME NUMBER here. This order CANNOT "
                "distinguish M147's cumulative price from a per-execution one - "
                "it is the LOV condition again, not a confirmation."
            )

        # IBKR's contract symbol is the BASE - "LOV" - and the ledger records
        # the qualified "LOV.AX". Comparing them directly finds nothing and
        # reports "no closed_trades row" for a symbol that has one, which is the
        # silent-blindness failure this whole script exists to avoid.
        matched = [r for r in rows if (r.get("symbol") or "").split(".")[0] == symbol]
        if not matched:
            out.append("  ledger                : no closed_trades row for this symbol yet")
        for row in matched:
            recorded = (row.get("exit_price") or "").strip()
            out.append(
                f"  ledger row            : qty {row.get('quantity')} "
                f"exit_price {recorded or '(empty)'} reason {row.get('exit_reason')}"
            )
            if not recorded:
                out.append("     (empty exit price - a repair row carries no wire to check)")
                continue
            delta = float(recorded) - vwap
            verdict = "MATCHES the wire" if abs(delta) <= _TOLERANCE else "DISAGREES"
            out.append(f"     recorded - VWAP    : {delta:+.6f}   {verdict}")
        out.append("")
    return "\n".join(out)


async def _run(symbol: str | None) -> int:
    from ib_async import IB, ExecutionFilter

    host, port, client_id = connection_target(_connection_settings())
    ib = IB()
    print(f"connecting read-only to {host}:{port} as clientId={client_id} ...")
    await ib.connectAsync(host, port, clientId=client_id, readonly=True, timeout=15)
    try:
        accounts = ib.managedAccounts()
        check_paper_account(accounts)
        print(f"connected: {accounts}")
        executions = await ib.reqExecutionsAsync(ExecutionFilter())
    finally:
        ib.disconnect()

    if symbol:
        base = symbol.split(".")[0]
        executions = [f for f in executions if f.contract.symbol == base]

    print()
    print(_report(list(executions), _ledger_rows(symbol)))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", default=None, help="e.g. LOV.AX; omit for every symbol")
    args = parser.parse_args()
    return asyncio.run(_run(args.symbol))


if __name__ == "__main__":
    raise SystemExit(main())

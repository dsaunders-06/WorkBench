"""Sell every open position to zero. Dry-run by default.

    .\\.venv\\Scripts\\python.exe scripts/flatten_positions.py            # report only
    .\\.venv\\Scripts\\python.exe scripts/flatten_positions.py --execute  # actually sell

Written for the 24 August 2026 remediation. `AutonomousExecutor.retry_pending`
re-transmitted two already-transmitted orders every sixty seconds (M139), and
the paper account was left holding 68,268 DXS against an intended 17,067 and
8,587 TNE against 3,076 - about $679k, roughly four times what was meant, with
NO protective stops resting and no position record in the application at all.

Those positions exist only because of a defect. Nobody decided to hold them, and
the application cannot manage them: it has no entry basis, so the minimum hold
and the time stop cannot be computed, and no recorded stop to re-arm.

**ONE ORDER PER SYMBOL, NO RETRY LOOP.** That is deliberate and it is the whole
point: the incident this remediates was caused by something that re-sent orders
on a timer. This script sends once, reports what happened, and stops. If a sell
does not fill, that is a fact to look at rather than something to paper over
with another order.

Guards, all of them refusing rather than warning:

* a LIVE port in paper mode is refused (`connection_target`, W1.4's rule);
* a non-`DU` account is refused after connecting (`check_paper_account`) -
  the port being right does not prove the Gateway is on the paper session;
* nothing is sold without `--execute`, and the dry run prints exactly what the
  execute pass would send.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from qat.config import Settings  # noqa: E402
from qat.data.broker.ib_probe import check_paper_account, connection_target  # noqa: E402


def _settings() -> Settings:
    """The operator's real host/port, with `data_dir` pointed elsewhere.

    Same reasoning as `ibkr_probe._settings`: `Settings(_env_file=None).data_dir`
    is the LIVE data directory. This script writes nothing there, and passing
    its own keeps that structural rather than incidental.
    """
    return Settings(data_dir=tempfile.mkdtemp(prefix="qat-flatten-"))


async def _run(execute: bool) -> int:
    from ib_async import IB, MarketOrder, Stock

    settings = _settings()
    host, port, client_id = connection_target(settings)
    ib = IB()
    # readonly=False only when actually selling. A dry run has no business
    # holding a read-write session open.
    await ib.connectAsync(host, port, clientId=client_id, readonly=not execute, timeout=15)
    try:
        accounts = list(ib.managedAccounts())
        check_paper_account(accounts)
        await asyncio.sleep(2)

        positions = [p for p in ib.positions() if p.position]
        if not positions:
            print("No open positions. Nothing to do.")
            return 0

        print(f"account {accounts[0]}   mode={'EXECUTE' if execute else 'DRY RUN'}\n")
        print("=== WOULD SELL ===" if not execute else "=== SELLING ===")
        total = 0.0
        for p in positions:
            value = p.position * p.avgCost
            total += value
            side = "SELL" if p.position > 0 else "BUY (short)"
            print(
                f"  {side:<11} {abs(p.position):>12,.0f} {p.contract.symbol:<6} "
                f"@ avg {p.avgCost:>9,.4f}   value {value:>14,.2f}"
            )
        print(f"  {'TOTAL':<11} {'':>12} {'':<6}   {'':>15} {total:>14,.2f}\n")

        if not execute:
            print("Dry run. Nothing sent. Re-run with --execute to sell.")
            return 0

        trades = []
        for p in positions:
            contract = Stock(p.contract.symbol, "SMART", p.contract.currency)
            contract.primaryExchange = p.contract.exchange
            await ib.qualifyContractsAsync(contract)
            action = "SELL" if p.position > 0 else "BUY"
            order = MarketOrder(action, abs(p.position))
            trades.append((p.contract.symbol, ib.placeOrder(contract, order)))
            print(f"  sent {action} {abs(p.position):,.0f} {p.contract.symbol}")

        print("\nwaiting for fills (30s)...")
        for _ in range(30):
            await asyncio.sleep(1)
            if all(t.isDone() for _, t in trades):
                break

        print("\n=== RESULT ===")
        for symbol, trade in trades:
            status = trade.orderStatus
            print(
                f"  {symbol:<6} {status.status:<12} filled {status.filled:>12,.0f} "
                f"@ {status.avgFillPrice or 0:,.4f}"
            )

        await asyncio.sleep(2)
        remaining = [p for p in ib.positions() if p.position]
        print("\n=== POSITIONS AFTER ===")
        if not remaining:
            print("  FLAT - no open positions")
        else:
            for p in remaining:
                print(f"  {p.contract.symbol:<6} {p.position:>12,.0f}  STILL HELD")
        return 0 if not remaining else 1
    finally:
        ib.disconnect()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="actually place the sell orders; without it this only reports",
    )
    args = parser.parse_args()
    return asyncio.run(_run(args.execute))


if __name__ == "__main__":
    raise SystemExit(main())

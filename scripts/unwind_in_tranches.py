"""Cancel a stuck order and sell the remainder in tranches. Dry-run by default.

    .\\.venv\\Scripts\\python.exe scripts/unwind_in_tranches.py SYMBOL
    .\\.venv\\Scripts\\python.exe scripts/unwind_in_tranches.py SYMBOL --execute

Written for the 24 August 2026 remediation, after `flatten_positions.py` sold
TNE.AX cleanly and left DXS.AX parked. One market order for 68,268 shares of a
$5.86 stock filled 13,825 and then sat at `PreSubmitted` for ten minutes without
moving another share, having thrown "Order TIF was set to DAY based on order
preset" and "Order held while securities are located" on the way in. That is a
parked order, not a slow one, and more waiting does not fix it.

**CANCEL FIRST, THEN ONE TRANCHE AT A TIME, EACH WAITING FOR THE ONE BEFORE.**

The cancel is not tidiness. The discipline this whole afternoon has been "never
send an order while another is working" - because the incident being remediated
(M139) was caused by exactly that, an order re-transmitted every sixty seconds
while its predecessor was still live. Sending tranches on top of a working
order would repeat the shape of the defect while cleaning up after it. Cancelling
ends that condition honestly, and then each tranche is the only live order.

A tranche that does not fill STOPS the run rather than triggering another. If
the book will not take 12,000 shares, sending a second 12,000 will not help, and
the right answer is a smaller size chosen by a human looking at the depth.
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

# Slightly under what TNE.AX absorbed in one go this afternoon. Not a measured
# depth figure - a deliberately cautious size for an unwind nobody wants.
DEFAULT_TRANCHE = 12_000
# How long one tranche gets before the run stops and reports.
TRANCHE_TIMEOUT_SECONDS = 90


async def _run(symbol: str, tranche: int, execute: bool) -> int:
    from ib_async import IB, MarketOrder, Stock

    settings = _settings()
    host, port, client_id = connection_target(settings)
    ib = IB()
    await ib.connectAsync(host, port, clientId=client_id, readonly=not execute, timeout=15)
    try:
        check_paper_account(list(ib.managedAccounts()))
        await asyncio.sleep(2)

        held = next((p for p in ib.positions() if p.contract.symbol == symbol and p.position), None)
        if held is None:
            print(f"No open position in {symbol}. Nothing to do.")
            return 0

        working = [t for t in ib.openTrades() if t.contract.symbol == symbol]
        quantity = abs(held.position)
        tranches = -(-int(quantity) // tranche)
        print(f"account {ib.managedAccounts()[0]}   mode={'EXECUTE' if execute else 'DRY RUN'}\n")
        print(f"  position        {symbol} {held.position:,.0f}")
        print(f"  working orders  {len(working)}")
        for t in working:
            print(
                f"      {t.order.action} {t.order.totalQuantity:,.0f} status={t.orderStatus.status}"
            )
        print(
            f"  plan            cancel the above, then {tranches} tranche(s) of up to {tranche:,}"
        )

        if not execute:
            print("\nDry run. Nothing cancelled, nothing sent.")
            return 0

        for t in working:
            ib.cancelOrder(t.order)
            print(f"\n  cancelled {t.order.action} {t.order.totalQuantity:,.0f} {symbol}")
        if working:
            await asyncio.sleep(5)

        contract = Stock(symbol, "SMART", held.contract.currency)
        contract.primaryExchange = held.contract.exchange
        await ib.qualifyContractsAsync(contract)

        sold = 0.0
        while True:
            await asyncio.sleep(2)
            current = next(
                (p for p in ib.positions() if p.contract.symbol == symbol and p.position), None
            )
            if current is None:
                print(f"\n  {symbol} is FLAT")
                break
            remaining = abs(current.position)
            size = min(tranche, int(remaining))
            print(f"\n  remaining {remaining:,.0f} - selling {size:,}")
            trade = ib.placeOrder(contract, MarketOrder("SELL", size))

            for _ in range(TRANCHE_TIMEOUT_SECONDS):
                await asyncio.sleep(1)
                if trade.isDone():
                    break
            status = trade.orderStatus
            price = status.avgFillPrice or 0
            print(f"      {status.status} filled {status.filled:,.0f} @ {price:,.4f}")
            sold += status.filled

            if status.filled <= 0:
                # STOPS. A tranche that moved nothing means the book will not
                # take this size, and sending another identical one is the
                # behaviour this whole remediation exists to correct.
                print("\n  ⚠️ tranche filled NOTHING - stopping rather than sending another.")
                print("     Cancel it by hand, look at the depth, and choose a smaller size.")
                return 1

        print(f"\n  total sold this run: {sold:,.0f}")
        return 0
    finally:
        ib.disconnect()


def _settings() -> Settings:
    """Real host/port, `data_dir` pointed elsewhere - this writes nothing there."""
    return Settings(data_dir=tempfile.mkdtemp(prefix="qat-unwind-"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("symbol")
    parser.add_argument("--tranche", type=int, default=DEFAULT_TRANCHE)
    parser.add_argument("--execute", action="store_true", help="cancel and sell for real")
    args = parser.parse_args()
    return asyncio.run(_run(args.symbol, args.tranche, args.execute))


if __name__ == "__main__":
    raise SystemExit(main())

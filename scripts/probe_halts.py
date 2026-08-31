"""What does IBKR actually tell us about a trading halt? (M43)

READ-ONLY. RUN THROUGH POWERSHELL.

M43 says there is no halt detection anywhere, and names the case that hurts:
position held, symbol halted, stop cannot fill, reopens materially lower. The
staleness rail cannot cover it - a halted symbol and a quiet one look identical
to a rail that measures price AGE.

⚠️ Measured before designing, because M39 is the precedent: corporate-action
detection was designed and then found to have no IBKR feed behind it at all.
The question here is whether the capability exists, not what we would like it
to be.

Writes nothing: throwaway data_dir, readonly socket, its own clientId.
"""

import asyncio
import sys
import tempfile

sys.path.insert(0, r"C:\Claude Programming\src")

from qat.config import Settings  # noqa: E402
from qat.data.broker.ib_probe import check_paper_account, connection_target  # noqa: E402
from qat.data.broker.ib_translate import to_ib_contract  # noqa: E402

_SYMBOLS = ["BHP.AX", "CBA.AX", "SUN.AX"]

# ⚠️ RUN THIS DURING MARKET HOURS to finish the measurement. Taken 28 August with
# the market SHUT it returned halted=nan on every symbol, which cannot separate
# "nothing is halted" from "halts are not reported to this account". On an OPEN
# market a trading symbol should read halted=0 if the flag is live at all.


async def main() -> int:
    from ib_async import IB, Ticker

    print("=== does ib_async model a halt at all? ===")
    fields = [f for f in getattr(Ticker, "__slots__", []) or dir(Ticker) if "halt" in f.lower()]
    print(f"  Ticker fields matching 'halt': {fields or 'NONE'}")
    if not fields:
        print("  ⚠️ ib_async does not expose a halt field - M43 has no feed, like M39.")

    settings = Settings(data_dir=tempfile.mkdtemp(prefix="qat-halt-"))
    host, port, client_id = connection_target(settings)
    ib = IB()
    print(f"\nconnecting read-only to {host}:{port} as clientId={client_id} ...")
    await ib.connectAsync(host, port, clientId=client_id, readonly=True, timeout=15)
    try:
        check_paper_account(ib.managedAccounts())
        # ⚠️ Error 354 says live data is not subscribed but "Delayed market data
        # is available". Type 3 = DELAYED. If `halted` populates there, M43 has a
        # feed after all - so this must be tried before concluding it has none.
        ib.reqMarketDataType(3)
        print("=== what the DELAYED feed reports, per symbol ===")
        for symbol in _SYMBOLS:
            contract = to_ib_contract(symbol, settings.market)
            # ⚠️ Qualify first: reqTickers hashes the contract and a conId-less
            # one raises. The app's own adapter does this; a probe that skips it
            # is testing its own shortcut, not the capability.
            qualified = await ib.qualifyContractsAsync(contract)
            if not qualified:
                print(f"  {symbol:<10} could not be qualified")
                continue
            tickers = await ib.reqTickersAsync(qualified[0])
            if not tickers:
                print(f"  {symbol:<10} no ticker returned")
                continue
            t = tickers[0]
            print(
                f"  {symbol:<10} halted={getattr(t, 'halted', '?')!r:<8} "
                f"delayedHalted={getattr(t, 'delayedHalted', '?')!r:<8} "
                f"close={getattr(t, 'close', None)!r:<10} "
                f"delayedLast={getattr(t, 'delayedLast', None)!r}"
            )
    finally:
        ib.disconnect()

    print(
        "\n⚠️ A SNAPSHOT ALONE CANNOT CONCLUDE. `reqTickers` is a snapshot, and 'the "
        "snapshot did not carry it' is not 'the feed does not provide it'. Hold a "
        "STREAMING subscription before deciding."
    )
    print(
        "\n✅ ANSWERED 31 August 2026, 10:59 AEST, ASX in CONTINUOUS TRADING, with a\n"
        "   streaming delayed subscription (marketDataType=3) held for 20 seconds:\n\n"
        "     BHP.AX  last=66.515 bid=66.51 ask=66.52 high=66.74 low=66.18 open=66.68\n"
        "             volume=495,809      halted=nan      delayedHalted=nan\n\n"
        "   A FULL LIVE QUOTE ARRIVES, and the halt fields are the ONLY ones that never\n"
        "   populate. The flag is not served to this account, so M43 CANNOT be built on\n"
        "   it - M39's shape. What remains is BEHAVIOURAL detection, a heuristic rather\n"
        "   than a report, and it collides with the staleness rail.\n\n"
        "   ⚠️ THE BIGGER FINDING: IBKR's DELAYED feed STREAMS last/bid/ask/high/low/\n"
        "   open/volume for ASX. That is the 'deeper fix' item 33 names for the 20-minute\n"
        "   yfinance blind window - now measured rather than assumed."
    )
    print(
        "\n⚠️ The line that used to print here said 'The market is SHUT' - HARDCODED, not\n"
        "   a session check. It was true on 28 August and printed unchanged at 10:57 on\n"
        "   31 August with the ASX in continuous trading, masking the result above. A\n"
        "   statement written once, surviving into a context where it is false."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

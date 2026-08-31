"""Does a STREAMING delayed subscription ever deliver a halt flag?

probe_halts.py uses reqTickers - a snapshot. "The snapshot did not carry it" is
not the same as "the feed does not provide it", and M39 was designed against a
feed that did not exist. This holds a live subscription open and reports what
actually arrives. Read only.
"""

from __future__ import annotations

import asyncio
import sys
import tempfile

sys.path.insert(0, r"C:\Claude Programming\src")
from qat.config import Settings
from qat.data.broker.ib_probe import connection_target
from qat.data.broker.ib_translate import to_ib_contract

SYMBOLS = ["BHP.AX", "CBA.AX", "SUN.AX"]
HOLD_SECONDS = 20


async def main() -> None:
    from ib_async import IB

    settings = Settings(data_dir=tempfile.mkdtemp(prefix="qat-halt2-"))
    host, port, client_id = connection_target(settings)
    ib = IB()
    await ib.connectAsync(host, port, clientId=client_id, readonly=True, timeout=15)
    try:
        ib.reqMarketDataType(3)  # delayed
        tickers = {}
        for sym in SYMBOLS:
            # ⚠️ market, or to_ib_contract defaults to SMART/USD and ASX symbols
            # fail with error 200 - the M96 defect, reproduced by omitting it.
            c = to_ib_contract(sym, settings.market)
            q = await ib.qualifyContractsAsync(c)
            if not q or q[0] is None:
                print(f"  {sym}: could not qualify")
                continue
            tickers[sym] = ib.reqMktData(q[0], "", False, False)

        print(f"holding a STREAMING delayed subscription for {HOLD_SECONDS}s ...")
        for _ in range(HOLD_SECONDS):
            await asyncio.sleep(1)

        print("\n=== after streaming ===")
        for sym, t in tickers.items():
            print(
                f"  {sym:<9} halted={getattr(t,'halted','?')!r:<7} "
                f"delayedHalted={getattr(t,'delayedHalted','?')!r:<7} "
                f"last={getattr(t, 'last', None)!r:<9} "
                f"delayedLast={getattr(t, 'delayedLast', None)!r:<9} "
                f"bid={getattr(t,'bid',None)!r:<9} close={getattr(t,'close',None)!r}"
            )
        print("\n=== every non-empty ticker field, BHP ===")
        t = tickers.get("BHP.AX")
        if t is not None:
            for f in sorted(set(dir(t))):
                if f.startswith("_"):
                    continue
                try:
                    v = getattr(t, f)
                except Exception:
                    continue
                if callable(v) or v is None:
                    continue
                sv = repr(v)
                if sv in ("nan", "[]", "{}", "''"):
                    continue
                if len(sv) < 60:
                    print(f"    {f:<22} {sv}")
    finally:
        ib.disconnect()


asyncio.run(main())

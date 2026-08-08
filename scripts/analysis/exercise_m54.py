"""M54, exercised against a REAL broker failure for the first time.

M54 has been deployed since 6 August and has never once run: it only fires when
Alpaca actually errors, and it has not errored since. Its tests use fakes that
raise on command, which proves the handler catches an exception - not that the
real SDK's real failure is the shape the handler expects.

So this drives the genuine path: a real `TradingClient` with deliberately wrong
credentials, hitting the real endpoint, producing whatever the SDK really
raises. Then it asserts the three things M54 promises:

  1. No exception escapes - the signal is refused, not thrown.
  2. A REJECTED order exists.
  3. The decision journal on disk carries a reason.

Writes to a scratch data directory, never the live one. Bad credentials mean
nothing can reach the account even in principle, and OMS.sign_off is the only
path to the broker regardless - so no order can be placed by this script.
"""

from __future__ import annotations

import asyncio
import csv
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, r"C:\Claude Programming\src")

from alpaca.trading.client import TradingClient  # noqa: E402

from qat.config import Settings  # noqa: E402
from qat.data.broker.alpaca_adapter import AlpacaAdapter  # noqa: E402
from qat.domain.bus import EventBus  # noqa: E402
from qat.domain.decision_journal import DecisionJournal  # noqa: E402
from qat.domain.oms.oms import OMS  # noqa: E402
from qat.domain.oms.signal_bridge import SignalToOrderBridge  # noqa: E402
from qat.domain.risk_engine.engine import RiskEngine  # noqa: E402
from qat.domain.risk_engine.kill_switch import KillSwitch  # noqa: E402

SCRATCH = Path(__file__).parent / "m54-data"
SCRATCH.mkdir(exist_ok=True)


def _bars() -> pd.DataFrame:
    """Enough real-shaped history for sizing to reach the account fetch."""
    index = pd.date_range("2026-06-01", periods=60, freq="D", tz="UTC")
    close = pd.Series([100.0 + (i % 7) - 3 for i in range(60)], index=index)
    return pd.DataFrame(
        {
            "open": close,
            "high": close + 1.5,
            "low": close - 1.5,
            "close": close,
            "volume": [1_000_000] * 60,
        },
        index=index,
    )


async def main() -> int:
    settings = Settings(_env_file=None, data_dir=str(SCRATCH))
    bus = EventBus()
    switch = KillSwitch()

    # A REAL client against the REAL endpoint, with credentials that cannot
    # work. Whatever alpaca-py raises here is what it would raise in a live
    # outage, which a hand-written fake cannot promise.
    broken = TradingClient(
        api_key="AKDELIBERATELYINVALID000",
        secret_key="deliberately-invalid-secret-for-m54-exercise",
        paper=True,
    )
    adapter = AlpacaAdapter(settings=settings, client=broken)

    journal = DecisionJournal(SCRATCH)
    oms = OMS(
        adapter,
        RiskEngine(bus, switch, settings=settings),
        switch,
        settings=settings,
        journal=journal,
    )
    bridge = SignalToOrderBridge(bus=bus, oms=oms, settings=settings)

    print("=" * 72)
    print("Confirming the real client really does fail")
    print("=" * 72)
    try:
        await adapter.account()
    except Exception as exc:  # noqa: BLE001 - that is the point
        print(f"  broker.account() raised {type(exc).__name__}: {str(exc)[:140]}")
    else:
        print("  NO FAILURE - credentials were accepted. This exercise is invalid.")
        return 1

    print()
    print("=" * 72)
    print("Driving the M54 path")
    print("=" * 72)
    try:
        await bridge._submit_sized(
            symbol="MNST",
            side="buy",
            bars=_bars(),
            price=100.0,
            positions=[],
            strategy="swing",
            stop_price=94.0,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"  FAILED (1): the exception ESCAPED - {type(exc).__name__}: {exc}")
        print("  This is exactly the 6 August behaviour M54 was built to remove.")
        return 1
    print("  PASSED (1): no exception escaped")

    rejected = [o for o in oms._orders.values() if o.status == "rejected"]
    if not rejected:
        print("  FAILED (2): no rejected order was recorded - the signal vanished")
        return 1
    print(f"  PASSED (2): {len(rejected)} rejected order(s): ", end="")
    print(", ".join(f"{o.symbol} {o.side} qty={o.quantity:g}" for o in rejected))

    path = SCRATCH / "decision_journal.csv"
    if not path.exists():
        print("  FAILED (3): no decision journal was written")
        return 1
    with path.open(newline="", encoding="utf-8") as handle:
        rows = [r for r in csv.DictReader(handle) if r["symbol"] == "MNST"]
    if not rows:
        print("  FAILED (3): journal exists but carries no MNST row")
        return 1
    print("  PASSED (3): journal on disk says:")
    for row in rows:
        print(f"      outcome={row['outcome']!r}  reason={row['reason']!r}")

    print()
    print("All three M54 promises hold against a real broker failure.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

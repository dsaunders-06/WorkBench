r"""Does a null `strategy` in the entry record cost a closed trade its
attribution? (held-over question from 11 August)

`open_position_entries.json` carries `"strategy": null` for nine of the ten held
positions. The handoff reads that as "every closed trade from a currently-held
position is unattributed, and counts towards no promotion gate" - which would
mean the trial has been collecting evidence that credits nothing.

M49 anticipated exactly this: `restore_open_lots` passes
`entry.strategy or self._sole_deployed_strategy()`, and the fallback resolves
from what is actually deployed. So the answer depends on a config value, not on
the file. This probe runs the app's own path over a COPY of the live record and
prints what the ledger actually ends up holding, because the last claim about
this record was reasoned rather than measured and was wrong.

Run under the PowerShell tool, not Bash: the live data directory is only
visible there.

    .\.venv\Scripts\python.exe scripts\analysis\probe_entry_strategy_attribution.py
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from qat.config import Settings
from qat.data.broker.adapter import Position
from qat.domain.bus import EventBus
from qat.domain.events import OrderFilledEvent
from qat.domain.oms.oms import OMS
from qat.domain.oms.signal_bridge import SignalToOrderBridge
from qat.domain.performance.trades import TradeLedger
from qat.domain.risk_engine.engine import RiskEngine
from qat.domain.risk_engine.kill_switch import KillSwitch

LIVE_ENTRIES = (
    Path(os.environ["LOCALAPPDATA"])
    / "QuantAdvisoryTerminal"
    / "data"
    / "open_position_entries.json"
)


class _Broker:
    """Holds exactly what the entry record names, at the recorded price. The
    quantity is irrelevant to attribution and is 1 for every symbol."""

    def __init__(self, entries: dict[str, dict]) -> None:
        self._entries = entries

    async def positions(self) -> list[Position]:
        return [
            Position(symbol=symbol, quantity=1.0, avg_price=float(row["price"]))
            for symbol, row in self._entries.items()
        ]

    async def resting_stops(self) -> dict[str, float]:
        return {}

    async def recent_fills(self, since):  # noqa: ANN001, ANN201
        return []


async def _restore(data_dir: Path, entries: dict[str, dict], deployed: str):
    settings = Settings(
        _env_file=None,
        data_dir=str(data_dir),
        deployed_strategies=deployed,
    )
    bus = EventBus()
    switch = KillSwitch()
    oms = OMS(
        _Broker(entries),
        RiskEngine(bus, switch, settings=settings),
        switch,
        bus=bus,
        settings=settings,
    )
    ledger = TradeLedger(bus, data_dir, settings=settings)
    bridge = SignalToOrderBridge(bus=bus, oms=oms, settings=settings, trade_ledger=ledger)
    restored = await bridge.restore_open_lots()
    return ledger, bridge, restored


async def main() -> None:
    raw = LIVE_ENTRIES.read_text(encoding="utf-8")
    entries = json.loads(raw)

    print(f"Live record: {LIVE_ENTRIES}")
    print(f"  {len(entries)} positions, {LIVE_ENTRIES.stat().st_size} bytes")
    nulls = sorted(s for s, r in entries.items() if r.get("strategy") is None)
    named = {s: r["strategy"] for s, r in entries.items() if r.get("strategy")}
    print(f"  strategy null   : {len(nulls)} - {', '.join(nulls)}")
    print(f"  strategy named  : {len(named)} - {named}")

    for deployed in ("swing", "swing,price_action"):
        work = Path(tempfile.mkdtemp(prefix="qat-attrib-"))
        try:
            # Its OWN data_dir, and the live file is COPIED into it. Nothing in
            # this probe can write to the live record.
            shutil.copy2(LIVE_ENTRIES, work / "open_position_entries.json")
            ledger, _bridge, restored = await _restore(work, entries, deployed)

            print()
            print(f"=== QAT_DEPLOYED_STRATEGIES={deployed} ===")
            print(f"  restored {len(restored)} lot(s)")
            attributed = {}
            for symbol in sorted(entries):
                lots = ledger.open_lots(symbol)
                attributed[symbol] = lots[0].strategy if lots else "NO LOT"
            for symbol, strategy in attributed.items():
                flag = "" if strategy not in (None, "NO LOT") else "   <-- unattributed"
                print(f"    {symbol:<6} strategy={strategy!r}{flag}")

            # End to end: close a position whose record says null, and read the
            # closed trade the promotion gate would count.
            # A null one while any remain, so the probe keeps exercising the
            # case it was written for. Once the record is healed there are none,
            # and any symbol demonstrates the same thing.
            probe_symbol = nulls[0] if nulls else sorted(entries)[0]
            await ledger._on_fill(
                OrderFilledEvent(
                    order_id="probe-exit",
                    symbol=probe_symbol,
                    side="sell",
                    quantity=1.0,
                    price=float(entries[probe_symbol]["price"]) * 1.05,
                    operator="probe",
                    exit_reason="target",
                    ts=datetime.now(UTC),
                )
            )
            closed = ledger.closed_trades()
            said = "null" if probe_symbol in nulls else repr(entries[probe_symbol]["strategy"])
            print(f"  closed {probe_symbol} (record said {said}):")
            for trade in closed:
                print(f"    strategy={trade.strategy!r}  r_multiple={trade.r_multiple}")
            print(f"  ledger.strategies() -> {ledger.strategies()}")
        finally:
            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(main())

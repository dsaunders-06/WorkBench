"""Generate legacy receipts using the real pre-Task-2 production stack.

Run with the base revision's src on PYTHONPATH and an empty output directory
as the only argument. The source hashes reject accidental use of current code.
"""

from __future__ import annotations

import asyncio
import hashlib
import shutil
import sys
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from qat.config import Settings
from qat.data.broker.adapter import BrokerFill
from qat.data.broker.mock_broker import MockBroker
from qat.domain.bus import EventBus
from qat.domain.events import BrokerOrderIdResolvedEvent, OrderFilledEvent
from qat.domain.oms.oms import OMS
from qat.domain.oms.signal_bridge import SignalToOrderBridge
from qat.domain.performance.trades import TradeLedger
from qat.domain.risk_engine.engine import RiskEngine
from qat.domain.risk_engine.kill_switch import KillSwitch


class LateBroker(MockBroker):
    async def place_order(self, order):
        return replace(order, status="transmitted", filled_quantity=0.0, filled_price=None)


async def main(destination: Path) -> None:
    for module, expected in {
        "qat.domain.oms.oms": "cf8c77e28d9c701e17606980024dd5e18998a381",
        "qat.domain.oms.signal_bridge": "75170719b296639670b33e32b2203aef08e28ed4",
        "qat.domain.performance.trades": "7e35281ce967c214800374a3e34ede75bcb53e52",
    }.items():
        source = Path(sys.modules[module].__file__).read_bytes().replace(b"\r\n", b"\n")
        blob = b"blob " + str(len(source)).encode() + b"\0" + source
        assert hashlib.sha1(blob).hexdigest() == expected, f"Wrong base source: {module}"
    destination.mkdir(parents=True, exist_ok=False)
    data = destination / "producer"
    settings = Settings(_env_file=None, data_dir=str(data))
    bus, broker, switch = EventBus(), LateBroker(seed=1), KillSwitch()
    stamp = datetime(2026, 9, 25, 12, tzinfo=UTC)
    oms = OMS(
        broker,
        RiskEngine(bus, switch, settings=settings),
        switch,
        bus=bus,
        settings=settings,
        clock=lambda: stamp,
    )
    bridge = SignalToOrderBridge(bus, oms, settings=settings)
    ledger = TradeLedger(bus, data, settings=settings)
    await ledger.start()
    bus.subscribe(OrderFilledEvent, bridge._on_fill, critical=True)
    bus.subscribe(BrokerOrderIdResolvedEvent, bridge._on_order_id_resolved)
    order = oms._new_pending_order("WOW.AX", "buy", 10.0, 100.0, "swing")
    app_id = order.order_id
    await oms.sign_off(app_id, "operator")
    broker._broker_fills[:] = [BrokerFill(app_id, "WOW.AX", "buy", 4.0, 101.0, stamp)]
    await oms.absorb_broker_fills()
    await bus.publish(BrokerOrderIdResolvedEvent(order_id="998877", app_order_id=app_id))
    assert oms._save_fill_state()
    assert bridge.position_entries()["WOW.AX"].order_id == "998877"

    def snapshot(name: str) -> None:
        target = destination / name
        target.mkdir()
        for filename in (
            "absorbed_fills.json",
            "inflight_orders.json",
            "open_position_entries.json",
        ):
            shutil.copyfile(data / filename, target / filename)

    snapshot("settled")

    async def fail(_event):
        raise OSError("critical sibling unavailable after durable entry write")

    bus.subscribe(OrderFilledEvent, fail, critical=True)
    broker._broker_fills[:] = [
        BrokerFill("998877", "WOW.AX", "buy", 10.0, 102.0, stamp + timedelta(seconds=1))
    ]
    await oms.absorb_broker_fills()
    assert bridge.position_entries()["WOW.AX"].quantity == 10.0
    assert "998877|WOW.AX|buy|10" in oms._pending_fill_deliveries
    snapshot("pending")
    print(f"Generated base-version settled and pending receipts in {destination}")


if __name__ == "__main__":
    asyncio.run(main(Path(sys.argv[1])))

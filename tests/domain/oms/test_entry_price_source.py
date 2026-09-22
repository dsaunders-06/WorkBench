"""Where an entry record's price came from (M175).

M65 overwrote an OBSERVED fill with IBKR's commission-inclusive average cost at
every restart - JHX.AX on 31 August, COH.AX on 10 September - because the record
could not say that its price had already been corrected to the fill.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from qat.config import Settings
from qat.data.broker.adapter import BrokerFill, Order, Position
from qat.data.broker.mock_broker import MockBroker
from qat.domain.bus import EventBus
from qat.domain.events import EntryPriceCorrectedEvent, OrderFilledEvent
from qat.domain.oms.oms import OMS
from qat.domain.oms.signal_bridge import SignalToOrderBridge
from qat.domain.risk_engine.engine import RiskEngine
from qat.domain.risk_engine.kill_switch import KillSwitch

_WHEN = datetime(2026, 9, 10, 0, 29, tzinfo=UTC)


def _bridge(tmp_path) -> SignalToOrderBridge:
    settings = Settings(_env_file=None, data_dir=str(tmp_path))
    bus = EventBus()
    switch = KillSwitch()
    oms = OMS(
        MockBroker(seed=1), RiskEngine(bus, switch, settings=settings), switch, settings=settings
    )
    return SignalToOrderBridge(bus=bus, oms=oms, settings=settings)


def _buy(price: float, price_is_fill: bool) -> OrderFilledEvent:
    return OrderFilledEvent(
        order_id="coh-1",
        symbol="COH.AX",
        side="buy",
        quantity=363,
        price=price,
        strategy="swing",
        stop_price=126.09,
        reference_price=136.54,
        price_is_fill=price_is_fill,
        ts=_WHEN,
    )


@pytest.mark.asyncio
async def test_the_announcement_says_whether_its_price_is_a_fill(tmp_path):
    settings = Settings(_env_file=None, data_dir=str(tmp_path))
    bus = EventBus()
    switch = KillSwitch()
    oms = OMS(
        MockBroker(seed=1),
        RiskEngine(bus, switch, settings=settings),
        switch,
        bus=bus,
        settings=settings,
    )
    seen: list[OrderFilledEvent] = []

    async def grab(event: OrderFilledEvent) -> None:
        seen.append(event)

    bus.subscribe(OrderFilledEvent, grab)
    transmitted = Order(
        symbol="COH.AX",
        side="buy",
        quantity=363,
        order_id="a",
        status="transmitted",
        reference_price=136.54,
    )
    filled = Order(
        symbol="COH.AX",
        side="buy",
        quantity=363,
        order_id="b",
        status="filled",
        filled_price=135.736,
        filled_quantity=363,
        reference_price=136.54,
    )

    await oms._announce_fill(transmitted, "test")
    await oms._announce_fill(filled, "test")

    assert [(e.price, e.price_is_fill) for e in seen] == [(135.736, True)]


@pytest.mark.asyncio
async def test_an_entry_announced_at_its_fill_is_stamped_fill(tmp_path):
    bridge = _bridge(tmp_path)
    await bridge._on_fill(_buy(135.736, price_is_fill=True))
    assert bridge._entries["COH.AX"].price_source == "fill"


@pytest.mark.asyncio
async def test_an_entry_announced_at_its_reference_is_stamped_reference(tmp_path):
    bridge = _bridge(tmp_path)
    await bridge._on_fill(_buy(136.54, price_is_fill=False))
    assert bridge._entries["COH.AX"].price_source == "reference"


@pytest.mark.asyncio
async def test_the_live_correction_stamps_the_record_as_a_fill(tmp_path):
    bridge = _bridge(tmp_path)
    await bridge._on_fill(_buy(136.54, price_is_fill=False))

    await bridge._on_entry_price_corrected(
        EntryPriceCorrectedEvent(
            order_id="coh-1", symbol="COH.AX", price=135.736, announced_price=136.54
        )
    )

    entry = bridge._entries["COH.AX"]
    assert (entry.price, entry.price_source) == (135.736, "fill")


@pytest.mark.asyncio
async def test_the_stamp_survives_a_restart(tmp_path):
    bridge = _bridge(tmp_path)
    await bridge._on_fill(_buy(135.736, price_is_fill=True))

    assert _bridge(tmp_path)._entries["COH.AX"].price_source == "fill"


@pytest.mark.asyncio
async def test_an_absorbed_broker_buy_is_stamped_fill(tmp_path):
    """A position opened at the broker (a hand-placed buy) arrives through
    the absorb path at IBKR's execution avgPrice - an OBSERVED fill, which the
    M175 build's M65 must then never overwrite with a derived figure."""
    settings = Settings(_env_file=None, data_dir=str(tmp_path))
    bus = EventBus()
    switch = KillSwitch()
    broker = MockBroker(seed=1)
    broker._positions["MNST"] = Position(symbol="MNST", quantity=8.0, avg_price=91.18375)
    broker._broker_fills.append(
        BrokerFill(
            order_id="35010615",
            symbol="MNST",
            side="buy",
            quantity=8.0,
            price=91.18375,
            filled_at=datetime(2026, 8, 10, 13, 30, tzinfo=UTC),
        )
    )
    oms = OMS(
        broker, RiskEngine(bus, switch, settings=settings), switch, bus=bus, settings=settings
    )
    bridge = SignalToOrderBridge(bus=bus, oms=oms, settings=settings)
    bus.subscribe(OrderFilledEvent, bridge._on_fill)
    await oms.adopt_broker_positions()
    oms._last_fill_scan = datetime(2026, 8, 8, 9, 0, tzinfo=UTC)  # else the fill is filtered out

    absorbed = await oms.absorb_broker_fills(record_only=True)

    assert [f.symbol for f in absorbed] == ["MNST"], "nothing absorbed - the test is vacuous"
    entry = bridge._entries["MNST"]
    assert (entry.price, entry.price_source) == (91.18375, "fill")


def test_a_pre_m175_record_loads_with_no_stamp(tmp_path):
    (tmp_path / "open_position_entries.json").write_text(
        json.dumps(
            {
                "BOQ.AX": {
                    "opened_at": "2026-08-25T00:30:04.620473+00:00",
                    "price": 6.3856144,
                    "stop_price": 6.07,
                    "target_price": 7.05,
                    "strategy": "swing",
                    "reference_price": None,
                }
            }
        ),
        encoding="utf-8",
    )
    assert _bridge(tmp_path)._entries["BOQ.AX"].price_source is None

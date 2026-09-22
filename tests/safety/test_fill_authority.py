"""A broker acknowledgement cannot create an executable position or cost basis."""

from datetime import UTC, datetime

import pytest

from qat.config import Settings
from qat.data.broker.adapter import BrokerFill, Position
from qat.data.broker.mock_broker import MockBroker
from qat.domain.bus import EventBus
from qat.domain.events import OrderFilledEvent, OrderRejectedEvent
from qat.domain.oms.oms import OMS
from qat.domain.oms.signal_bridge import SignalToOrderBridge
from qat.domain.performance.trades import TradeLedger
from qat.domain.risk_engine.engine import RiskEngine
from qat.domain.risk_engine.kill_switch import KillSwitch


class DeferredBroker(MockBroker):
    async def place_order(self, order):
        order.status = "transmitted"
        order.filled_quantity = 0.0
        self._orders[order.order_id] = order
        return order

    def execute(self, order, quantity, price):
        fill = BrokerFill(
            order.order_id, order.symbol, order.side, quantity, price, datetime.now(UTC)
        )
        self._broker_fills = [fill]
        self._positions[order.symbol] = Position(order.symbol, quantity, price)
        return fill


async def stack(tmp_path):
    bus = EventBus()
    settings = Settings(_env_file=None, data_dir=str(tmp_path))
    broker = DeferredBroker(seed=1)
    switch = KillSwitch()
    oms = OMS(
        broker, RiskEngine(bus, switch, settings=settings), switch, bus=bus, settings=settings
    )
    ledger = TradeLedger(bus, str(tmp_path))
    await ledger.start()
    events = []

    async def observe(event):
        events.append(event)

    bus.subscribe(OrderFilledEvent, observe)
    order = oms._new_pending_order("AAA", "buy", 100.0, 100.0, "swing", stop_price=90.0)
    await oms.sign_off(order.order_id, "operator")
    return broker, oms, ledger, events, order


@pytest.mark.asyncio
async def test_transmission_does_not_create_holdings_lots_or_fill_events(tmp_path):
    _, oms, ledger, events, _ = await stack(tmp_path)
    assert oms.filled_quantities().get("AAA", 0.0) == 0.0
    assert ledger.open_lots() == []
    assert events == []


@pytest.mark.asyncio
async def test_partial_executions_add_only_real_quantity_and_cost_basis(tmp_path):
    broker, oms, ledger, events, order = await stack(tmp_path)
    first = broker.execute(order, 40.0, 101.0)
    await oms.absorb_broker_fills()
    assert oms.filled_quantities()["AAA"] == 40.0
    assert sum(lot.quantity for lot in ledger.open_lots()) == 40.0
    assert events[-1].price == 101.0
    assert events[-1].strategy == "swing"
    broker.execute(order, 100.0, 102.2)
    # Cumulative final price implies the second 60 shares executed at 103.
    broker._broker_fills.append(first)
    await oms.absorb_broker_fills()
    await oms.absorb_broker_fills()
    assert [event.quantity for event in events] == [40.0, 60.0]
    assert [event.price for event in events] == pytest.approx([101.0, 103.0])
    assert oms.filled_quantities()["AAA"] == 100.0
    assert sum(lot.quantity * lot.price for lot in ledger.open_lots()) == 10220.0


@pytest.mark.asyncio
async def test_rejection_preserves_only_confirmed_partial_fill(tmp_path):
    broker, oms, ledger, _, order = await stack(tmp_path)
    broker.execute(order, 40.0, 101.0)
    await oms.absorb_broker_fills()
    await oms.bus.publish(
        OrderRejectedEvent(
            order_id=order.order_id,
            symbol="AAA",
            side="buy",
            booked_quantity=100.0,
            executed_quantity=40.0,
            reason="remainder rejected",
        )
    )
    assert oms.filled_quantities()["AAA"] == 40.0
    assert sum(lot.quantity for lot in ledger.open_lots()) == 40.0


@pytest.mark.asyncio
async def test_reconciliation_does_not_subtract_unfilled_buy_remainder(tmp_path):
    broker, oms, _, _, order = await stack(tmp_path)
    broker.execute(order, 40.0, 101.0)
    assert await oms.check_reconciliation() is False
    assert oms.filled_quantities()["AAA"] == 40.0


@pytest.mark.asyncio
@pytest.mark.parametrize("terminal", ["rejected", "cancelled"])
async def test_exit_remainder_refusal_still_accounts_confirmed_execution(tmp_path, terminal):
    class PartialExitBroker(DeferredBroker):
        async def place_order(self, order):
            order.status = terminal
            order.filled_quantity = 40.0
            order.filled_price = 110.0
            self._positions["AAA"] = Position("AAA", 60.0, 100.0)
            return order

    bus = EventBus()
    settings = Settings(_env_file=None, data_dir=str(tmp_path))
    broker = PartialExitBroker(seed=1)
    broker._positions["AAA"] = Position("AAA", 100.0, 100.0)
    switch = KillSwitch()
    oms = OMS(
        broker, RiskEngine(bus, switch, settings=settings), switch, bus=bus, settings=settings
    )
    ledger = TradeLedger(bus, str(tmp_path))
    await ledger.start()
    ledger.restore_open_lot("AAA", 100.0, 100.0, 90.0, "swing", datetime(2026, 1, 1, tzinfo=UTC))
    await oms.adopt_broker_positions()
    order = await oms.submit_exit_order("AAA", 100.0, 110.0)
    await oms.sign_off(order.order_id, "operator")
    assert oms.filled_quantities()["AAA"] == 60.0
    assert sum(t.quantity for t in ledger.closed_trades()) == 40.0


@pytest.mark.asyncio
@pytest.mark.parametrize("quantity,price", [(None, 100.0), (100.0, None)])
async def test_incomplete_execution_acknowledgement_halts_without_inventing_a_lot(
    tmp_path, quantity, price
):
    broker, oms, ledger, events, order = await stack(tmp_path)
    order.status = "filled"
    order.filled_quantity = quantity
    order.filled_price = price
    await oms._announce_fill(order, "operator")
    assert oms.kill_switch.tripped
    assert ledger.open_lots() == []
    assert events == []


@pytest.mark.asyncio
async def test_restart_does_not_restore_the_missed_buy_twice(tmp_path):
    broker, oms, _, _, order = await stack(tmp_path)
    bridge = SignalToOrderBridge(bus=oms.bus, oms=oms, settings=oms.settings)
    oms.bus.subscribe(OrderFilledEvent, bridge._on_fill)
    broker.execute(order, 40.0, 101.0)
    await oms.absorb_broker_fills()
    broker.execute(order, 100.0, 102.2)

    bus = EventBus()
    settings = Settings(_env_file=None, data_dir=str(tmp_path))
    switch = KillSwitch()
    restarted = OMS(
        broker, RiskEngine(bus, switch, settings=settings), switch, bus=bus, settings=settings
    )
    ledger = TradeLedger(bus, str(tmp_path), settings=settings)
    await ledger.start()
    restored = SignalToOrderBridge(bus=bus, oms=restarted, settings=settings, trade_ledger=ledger)
    bus.subscribe(OrderFilledEvent, restored._on_fill)
    await restarted.adopt_broker_positions()
    # The current production startup order, excluding timers and re-arming.
    await restored.restore_open_lots()
    await restored.replay_missed_exits()
    assert restarted.filled_quantities()["AAA"] == 100.0
    assert sum(lot.quantity for lot in ledger.open_lots("AAA")) == 100.0
    assert sum(lot.quantity * lot.price for lot in ledger.open_lots("AAA")) == pytest.approx(
        10220.0
    )
    entry = restored.position_entries()["AAA"]
    assert entry.quantity == 100.0
    assert entry.price == pytest.approx(102.2)
    reloaded = SignalToOrderBridge(bus=bus, oms=restarted, settings=settings)
    assert reloaded.position_entries()["AAA"] == entry


@pytest.mark.asyncio
async def test_partial_sell_keeps_accounted_entry_when_broker_is_already_flat(tmp_path):
    broker, oms, _, _, order = await stack(tmp_path)
    bridge = SignalToOrderBridge(bus=oms.bus, oms=oms, settings=oms.settings)
    oms.bus.subscribe(OrderFilledEvent, bridge._on_fill)
    broker.execute(order, 100.0, 101.0)
    await oms.absorb_broker_fills()
    broker._positions.clear()
    broker._broker_fills = [BrokerFill("exit", "AAA", "sell", 40.0, 99.0, datetime.now(UTC))]
    await oms.absorb_broker_fills()
    assert bridge.position_entries()["AAA"].quantity == 60.0
    broker._broker_fills = [BrokerFill("exit", "AAA", "sell", 100.0, 99.0, datetime.now(UTC))]
    await oms.absorb_broker_fills()
    assert "AAA" not in bridge.position_entries()


@pytest.mark.asyncio
@pytest.mark.parametrize("sold", [40.0, 100.0])
async def test_restart_restores_accounted_quantity_before_offline_sell(tmp_path, sold):
    broker, oms, _, _, order = await stack(tmp_path)
    bridge = SignalToOrderBridge(bus=oms.bus, oms=oms, settings=oms.settings)
    oms.bus.subscribe(OrderFilledEvent, bridge._on_fill)
    broker.execute(order, 100.0, 101.0)
    await oms.absorb_broker_fills()
    broker._positions["AAA"] = Position("AAA", 100.0 - sold, 101.0)
    broker._broker_fills = [BrokerFill("exit", "AAA", "sell", sold, 99.0, datetime.now(UTC))]
    bus = EventBus()
    switch = KillSwitch()
    restarted = OMS(
        broker,
        RiskEngine(bus, switch, settings=oms.settings),
        switch,
        bus=bus,
        settings=oms.settings,
    )
    ledger = TradeLedger(bus, str(tmp_path), settings=oms.settings)
    await ledger.start()
    restored = SignalToOrderBridge(
        bus=bus, oms=restarted, settings=oms.settings, trade_ledger=ledger
    )
    bus.subscribe(OrderFilledEvent, restored._on_fill)
    await restarted.adopt_broker_positions()
    await restored.restore_open_lots()
    await restored.replay_missed_exits()
    assert sum(lot.quantity for lot in ledger.open_lots("AAA")) == 100.0 - sold
    assert not switch.tripped

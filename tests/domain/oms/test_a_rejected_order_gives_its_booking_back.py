"""Rejection must never reverse shares supported by confirmed executions."""

import pytest

from qat.config import Settings
from qat.data.broker.adapter import Position
from qat.data.broker.mock_broker import MockBroker
from qat.domain.bus import EventBus
from qat.domain.events import OrderRejectedEvent
from qat.domain.oms.oms import OMS
from qat.domain.risk_engine.engine import RiskEngine
from qat.domain.risk_engine.kill_switch import KillSwitch


class PartialBroker(MockBroker):
    def __init__(self, executed):
        super().__init__(seed=1)
        self.executed = executed

    async def place_order(self, order):
        order.status = "transmitted"
        order.filled_quantity = self.executed
        order.filled_price = 100.0 if self.executed else None
        return order


@pytest.mark.asyncio
@pytest.mark.parametrize("side", ["buy", "sell"])
@pytest.mark.parametrize("executed", [0.0, 400.0, 790.0])
@pytest.mark.parametrize("reported", [None, 0.0, 400.0])
async def test_rejection_cannot_change_confirmed_quantity(side, executed, reported):
    broker = PartialBroker(executed)
    if side == "sell":
        broker._positions["AAA"] = Position("AAA", 790.0, 100.0)
    bus = EventBus()
    switch = KillSwitch()
    settings = Settings(_env_file=None)
    oms = OMS(broker, RiskEngine(bus, switch, settings=settings), switch, bus=bus)
    await oms.adopt_broker_positions()
    order = oms._new_pending_order("AAA", side, 790.0, 100.0)
    await oms.sign_off(order.order_id, "operator")
    expected = executed if side == "buy" else 790.0 - executed
    assert oms.filled_quantities().get("AAA", 0.0) == expected
    await bus.publish(
        OrderRejectedEvent(
            order_id=order.order_id,
            symbol="AAA",
            side=side,
            booked_quantity=790.0,
            executed_quantity=reported,
            reason="remainder rejected",
        )
    )
    assert oms.filled_quantities().get("AAA", 0.0) == expected


@pytest.mark.asyncio
async def test_unknown_rejection_cannot_create_a_position():
    broker = PartialBroker(0.0)
    bus = EventBus()
    switch = KillSwitch()
    settings = Settings(_env_file=None)
    oms = OMS(broker, RiskEngine(bus, switch, settings=settings), switch, bus=bus)
    await bus.publish(
        OrderRejectedEvent(
            order_id="unknown",
            symbol="AAA",
            side="sell",
            booked_quantity=100.0,
            executed_quantity=40.0,
            reason="unknown order",
        )
    )
    assert oms.filled_quantities() == {}

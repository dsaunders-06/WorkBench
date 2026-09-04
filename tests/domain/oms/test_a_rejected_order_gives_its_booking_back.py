"""A rejected order kept its optimistic booking, and reconciliation paid for it.

3 September: TWS staged a 790-share BHP.AX order on a precautionary size limit.
Sign-off booked 790 - correctly, under a design that books optimistically and
lets reconciliation catch divergence. IBKR then said Error 383, nothing read it,
and the booking stood. `tracked=790 broker=0` tripped the kill switch every five
minutes for two hours, and the phantom counted toward the position cap, refusing
NST.AX with "already at the 10-position limit" against a book of nine.
"""

from __future__ import annotations

import pytest

from qat.config import Settings
from qat.data.broker.adapter import Order
from qat.data.broker.mock_broker import MockBroker
from qat.domain.bus import EventBus
from qat.domain.events import OrderRejectedEvent
from qat.domain.oms.oms import OMS
from qat.domain.risk_engine.engine import RiskEngine
from qat.domain.risk_engine.kill_switch import KillSwitch


@pytest.fixture
def oms() -> OMS:
    bus = EventBus()
    switch = KillSwitch()
    settings = Settings(_env_file=None)
    return OMS(MockBroker(seed=1), RiskEngine(bus, switch, settings=settings), switch, bus=bus)


async def _sign_off_a_buy(oms: OMS, *, symbol: str, quantity: float) -> Order:
    """Drives the REAL sign-off path, not a shortcut into `_filled_quantities`.

    `MockBroker.place_order` fills synchronously and completely, so this books
    exactly what a live sign-off books an instant before a broker rejection
    would arrive - the state Error 383 landed on top of on 3 September.
    """
    order = oms._new_pending_order(symbol, "buy", quantity)
    return await oms.sign_off(order.order_id, operator="test")


async def _reject(oms: OMS, *, symbol: str, booked: float, executed: float | None) -> None:
    """Publishes the same event `_on_ib_error` publishes for REJECT/HALT, so
    the OMS's own subscribed handler does the reversal - not a test double
    that pokes `_filled_quantities` directly."""
    assert oms.bus is not None
    await oms.bus.publish(
        OrderRejectedEvent(
            symbol=symbol,
            order_id="ib-test-order",
            booked_quantity=booked,
            executed_quantity=executed,
            reason="test rejection",
        )
    )


@pytest.mark.asyncio
async def test_a_rejection_takes_the_whole_booking_back(oms):
    """Nothing executed, so nothing should remain booked."""
    await _sign_off_a_buy(oms, symbol="BHP.AX", quantity=790.0)
    assert oms._filled_quantities["BHP.AX"] == 790.0

    await _reject(oms, symbol="BHP.AX", booked=790.0, executed=0.0)

    assert oms._filled_quantities.get("BHP.AX", 0.0) == 0.0


@pytest.mark.asyncio
async def test_a_partially_filled_rejection_leaves_what_executed(oms):
    """⚠️ Reversing the FULL booking here would create a phantom short - the
    reverted Task 3's defect in the other direction."""
    await _sign_off_a_buy(oms, symbol="BHP.AX", quantity=790.0)

    await _reject(oms, symbol="BHP.AX", booked=790.0, executed=400.0)

    assert oms._filled_quantities["BHP.AX"] == 400.0


@pytest.mark.asyncio
async def test_an_unknown_executed_quantity_reverses_nothing(oms):
    """`executed_quantity is None` means the adapter did not say. Reversing on a
    guess could invent a short; leaving it lets reconciliation settle it, which
    is the path that caught 3 September in four minutes."""
    await _sign_off_a_buy(oms, symbol="BHP.AX", quantity=790.0)

    await _reject(oms, symbol="BHP.AX", booked=790.0, executed=None)

    assert oms._filled_quantities["BHP.AX"] == 790.0


@pytest.mark.asyncio
async def test_a_rejection_for_an_unknown_symbol_changes_nothing(oms):
    await _reject(oms, symbol="NEVER.AX", booked=100.0, executed=0.0)

    assert "NEVER.AX" not in oms._filled_quantities

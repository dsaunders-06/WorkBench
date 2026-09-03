"""Shared fixtures for IBAdapter tests that need an order already on the wire
(Task 5, `errorEvent` consumption).

`adapter` and `order_on_the_wire` build the adapter and register an order
through the REAL `place_order` path - the same construction already
established in test_ib_adapter.py and test_ib_order_identity.py (a
FakeIBClient duck-typing IBClientProtocol, plus a bus) - rather than poking
`_orders`/`_ib_orders` by hand.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from types import SimpleNamespace
from typing import Any

import pytest
from ib_async.order import OrderStatus, Trade

from qat.config import Settings
from qat.data.broker.adapter import Order
from qat.data.broker.ib_adapter import IBAdapter


class FakeErrorEvent:
    """Minimal double for ib_async/eventkit's `errorEvent` - just enough to
    prove `connect()` subscribed the handler with `+=`, which is eventkit's
    own subscribe mechanism (`Event.__iadd__`), not a real dispatcher. No
    `emit` - nothing here fires a listener, it only records that one was
    attached, which is all `test_connect_subscribes_the_error_handler` needs.
    """

    def __init__(self) -> None:
        self.listeners: list[Any] = []

    def __iadd__(self, listener: Any) -> FakeErrorEvent:
        self.listeners.append(listener)
        return self


class FakeIBClient:
    """Enough of ib_async's IB for `place_order` to register an order that a
    later `errorEvent` can be reported against.

    `placeOrder` assigns `.orderId` synchronously and unconditionally, the way
    the real `IB.placeOrder` does (`orderId = order.orderId or
    self.client.getReqId()`, ib_async's ib.py:790) - it is the id IBKR's error
    report names as `reqId`, and the only one available at the instant a
    rejection can arrive. `permId` (M99) is assigned later still, if ever, and
    is left at 0 here to match the realistic ordering the rest of this suite
    already settled on - existing FakeIBClients in this directory never set
    `orderId` because nothing before this needed to match on it.
    """

    def __init__(self) -> None:
        self._next_order_id = 476  # the real reqId from the 3 September log
        self.placed_orders: list[tuple[Any, Any]] = []
        self.errorEvent = FakeErrorEvent()

    def isConnected(self) -> bool:
        return True

    async def connectAsync(self, *args: Any, **kwargs: Any) -> None:
        return None

    def disconnect(self) -> None:
        return None

    async def reqCurrentTimeAsync(self) -> datetime:
        return datetime.now()

    def placeOrder(self, contract: Any, order: Any) -> Trade:
        order.orderId = self._next_order_id
        self._next_order_id += 1
        self.placed_orders.append((contract, order))
        status = OrderStatus(
            status="Submitted",
            avgFillPrice=0.0,
            filled=0,
            remaining=order.totalQuantity,
            permId=0,
        )
        return Trade(contract=contract, order=order, orderStatus=status)


class RecordingBus:
    """A bus double that records a `publish` the instant it is called.

    `_on_ib_error` runs synchronously - it is invoked directly from
    ib_async/eventkit's own callback dispatch, with no `await` anywhere on the
    way in - so it schedules its publish with `asyncio.ensure_future` exactly
    as eventkit itself schedules an async listener's result: fire-and-forget
    onto whatever loop is current (see eventkit's `Slots.__call__`). In the
    running application that loop is the one already driving ib_async, and the
    task runs moments later. A plain test function drives no loop at all, so
    nothing would ever pick the task up - this records the call synchronously,
    before handing `ensure_future` an already-trivial awaitable to hold.
    """

    def __init__(self) -> None:
        self.published: list[object] = []

    def publish(self, event: object) -> Any:
        self.published.append(event)
        return asyncio.sleep(0)


@pytest.fixture
def adapter() -> IBAdapter:
    client = FakeIBClient()
    bus = RecordingBus()
    settings = Settings(_env_file=None, market="ASX", ibkr_permid_wait_seconds=0)
    return IBAdapter(client, bus, settings=settings)  # type: ignore[arg-type]


@pytest.fixture
def published(adapter: IBAdapter) -> list[object]:
    return adapter.bus.published  # type: ignore[attr-defined, no-any-return]


@pytest.fixture
async def order_on_the_wire(adapter: IBAdapter) -> SimpleNamespace:
    """An order this app has transmitted and is waiting on: a plain
    (non-bracket) buy, the same shape as the 790-share BHP.AX order TWS held
    on 3 September - registered via the real `place_order`, not invented."""
    order = Order(symbol="BHP.AX", side="buy", quantity=790, order_id="app-order-1")
    placed = await adapter.place_order(order)
    ib_order = adapter._ib_orders[placed.order_id]
    return SimpleNamespace(app_id=placed.order_id, req_id=ib_order.orderId)  # type: ignore[attr-defined]


@pytest.fixture
async def bracket_on_the_wire(adapter: IBAdapter) -> SimpleNamespace:
    """A bracket entry plus its protective legs, on the wire (Task 5 CRITICAL
    fix): registers parent, stop and target under `_ib_groups`, which is the
    branch `_order_for_req_id` searches when a rejection names a CHILD's
    orderId rather than the primary's - the "IBKR cancels the OCA sibling
    itself when the other leg fills" shape a 202 arrives as.
    """
    order = Order(
        symbol="BHP.AX",
        side="buy",
        quantity=790,
        order_id="app-bracket-1",
        stop_price=40.0,
        take_profit_price=45.0,
    )
    placed = await adapter.place_order(order)
    group = adapter._ib_groups[placed.order_id]
    stop_leg = next(leg for leg in group if getattr(leg, "orderType", None) == "STP")
    target_leg = next(leg for leg in group if getattr(leg, "orderType", None) == "LMT")
    return SimpleNamespace(
        app_id=placed.order_id,
        stop_req_id=stop_leg.orderId,  # type: ignore[attr-defined]
        target_req_id=target_leg.orderId,  # type: ignore[attr-defined]
    )

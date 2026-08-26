"""place_order must learn the permId TWS sends moments after acknowledgement.

`IB.placeOrder` returns a live Trade before TWS has acknowledged, so permId is
0 at that instant. Returning then leaves the app's own UUID as the order's id,
and the execution later arrives keyed on the permId - which is the 26 August
double-count.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from ib_async.order import OrderStatus, Trade

from qat.config import Settings
from qat.data.broker.adapter import Order
from qat.data.broker.ib_adapter import IBAdapter
from qat.domain.bus import EventBus


def _order(order_id: str) -> Order:
    return Order(symbol="WOW.AX", side="buy", quantity=100, order_id=order_id)


class _LatePermIdClient:
    """A Gateway that acknowledges an order from a task the event loop runs,
    the way real TWS actually behaves: `placeOrder` returns a LIVE `Trade`
    with `permId=0`, and the real id is stamped on a LATER loop iteration.

    Setting `permId` synchronously inside `placeOrder` would prove nothing -
    the entire defect is that the value is ABSENT at the instant `placeOrder`
    returns, and only a scheduled task reproduces that.
    """

    def __init__(self, perm_id: int, delay: float = 0.03) -> None:
        self.perm_id = perm_id
        self.delay = delay
        self.placed_orders: list[object] = []

    def placeOrder(self, contract: object, order: object) -> Trade:
        order.permId = 0  # type: ignore[attr-defined]
        status = OrderStatus(status="PreSubmitted", permId=0)
        trade = Trade(contract=contract, order=order, orderStatus=status)
        self.placed_orders.append(order)
        # `placeOrder` itself stays synchronous, as real ib_async's is - the
        # acknowledgement is scheduled onto the running loop rather than
        # awaited here, so it genuinely lands after this call returns.
        asyncio.ensure_future(self._acknowledge(order, status))
        return trade

    async def _acknowledge(self, order: object, status: OrderStatus) -> None:
        await asyncio.sleep(self.delay)
        order.permId = self.perm_id  # type: ignore[attr-defined]
        status.permId = self.perm_id

    def cancelOrder(self, order: object, manualCancelOrderTime: str = "") -> None:
        return None


class _SilentClient:
    """A Gateway that places the order and never acknowledges it - TWS gone
    quiet, or an ack that never arrives within the process's lifetime."""

    def __init__(self) -> None:
        self.placed_orders: list[object] = []

    def placeOrder(self, contract: object, order: object) -> Trade:
        order.permId = 0  # type: ignore[attr-defined]
        status = OrderStatus(status="PreSubmitted", permId=0)
        self.placed_orders.append(order)
        return Trade(contract=contract, order=order, orderStatus=status)

    def cancelOrder(self, order: object, manualCancelOrderTime: str = "") -> None:
        return None


@pytest.fixture
def adapter_with_late_permid():
    client = _LatePermIdClient(perm_id=550634674)
    settings = Settings(_env_file=None, ibkr_permid_wait_seconds=2.0)
    adapter = IBAdapter(client, EventBus(), settings=settings)
    order = _order(str(uuid.uuid4()))
    return adapter, order


@pytest.fixture
def adapter_whose_permid_never_arrives():
    client = _SilentClient()
    settings = Settings(_env_file=None, ibkr_permid_wait_seconds=0.2)
    adapter = IBAdapter(client, EventBus(), settings=settings)
    app_id = str(uuid.uuid4())
    order = _order(app_id)
    return adapter, order, app_id


@pytest.mark.asyncio
async def test_the_permid_is_picked_up_when_it_arrives_late(adapter_with_late_permid):
    """permId is 0 at placeOrder and set shortly after, as TWS really behaves."""
    adapter, order = adapter_with_late_permid

    result = await adapter.place_order(order)

    assert result.order_id == "550634674", (
        f"order_id is {result.order_id!r} - the app kept its own id and will not "
        "recognise its own fill"
    )


@pytest.mark.asyncio
async def test_a_permid_that_never_arrives_keeps_our_id_and_says_so(
    adapter_whose_permid_never_arrives, caplog
):
    """Degrade to today's behaviour, but LOUDLY.

    Writing 0 as an id would collide every unacknowledged order with every
    other, so keeping our own id is right. Doing it silently is what let this
    run since 1 August.
    """
    import logging

    adapter, order, app_id = adapter_whose_permid_never_arrives

    with caplog.at_level(logging.WARNING):
        result = await adapter.place_order(order)

    assert result.order_id == app_id
    assert "permId" in caplog.text, caplog.text


@pytest.mark.asyncio
async def test_the_wait_is_bounded(adapter_whose_permid_never_arrives):
    """A broker that never answers must not hold the order path open."""
    adapter, order, _ = adapter_whose_permid_never_arrives
    adapter.settings.ibkr_permid_wait_seconds = 0.2

    started = asyncio.get_running_loop().time()
    await adapter.place_order(order)
    elapsed = asyncio.get_running_loop().time() - started

    assert elapsed < 2.0, f"place_order took {elapsed:.1f}s - the wait is not bounded"

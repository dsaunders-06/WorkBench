"""M99: an order the BROKER knows must be modifiable and cancellable.

Found by the Task 4 live check on 19 August, and it is the clearest example
this project has produced of a fake agreeing with production because both were
wrong in the same direction.

**The sequence.** Real IBKR returns `permId=0` from `placeOrder` - TWS has not
acknowledged yet. `from_ib_trade` correctly leaves the app's own id in place
(Task 3 reasoned about exactly this). So `place_order`'s dual registration,
guarded by `if result.order_id != app_order_id`, **never fires on the normal
path**. Moments later the broker reports the order under its permId, which is
what `resting_stop_orders` correctly returns - and:

    place_order returned order_id: app-1
    resting_stop_orders order_id:  893739455
    modify_order('893739455') -> KeyError
    cancel_order('893739455') -> KeyError

**A protective stop found by the protection scan could not be re-priced or
cancelled.** That is M39's corporate-action path - the MNST repair - failing on
the id the scan itself hands you.

**Why fifteen tests and fourteen killed mutations all missed it:** every fake
in the suite stamped `permId` synchronously inside `placeOrder`, so the dual
registration always fired in tests and never fired in production. The tests
agreed with each other because they shared one wrong assumption about timing.

The fix resolves an unknown id against the broker rather than tightening the
placement timing, because that also reaches orders **this app never placed** -
an adopted position's protective stop has no local handle at all, and was
equally unreachable.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest
from ib_async import Contract
from ib_async.order import Order as IBOrder
from ib_async.order import OrderStatus, Trade

from qat.config import Settings
from qat.data.broker.adapter import Order
from qat.data.broker.ib_adapter import IBAdapter
from qat.domain.bus import EventBus

APP_CLIENT_ID = 1
PERM_ID = 893739455


class AcknowledgingIB:
    """IBKR's real timing: `permId` is 0 when `placeOrder` returns, and TWS
    stamps it before the order next appears in `reqAllOpenOrders`."""

    def __init__(self, adopted: list[Trade] | None = None) -> None:
        self.placed: list[IBOrder] = []
        self.cancelled: list[IBOrder] = []
        self._trades: list[Trade] = list(adopted or [])
        self._next_order_id = 3

    def isConnected(self) -> bool:
        return True

    async def connectAsync(self, *a: Any, **k: Any) -> None:
        return None

    def disconnect(self) -> None:
        return None

    async def reqCurrentTimeAsync(self) -> Any:
        return None

    def placeOrder(self, contract: Contract, order: IBOrder) -> Trade:
        if not order.orderId:
            order.orderId = self._next_order_id
            self._next_order_id += 1
        order.permId = 0  # <- TWS has not acknowledged yet. This is the point.
        order.clientId = APP_CLIENT_ID
        self.placed.append(order)
        trade = Trade(
            contract=contract,
            order=order,
            orderStatus=OrderStatus(orderId=order.orderId, status="PreSubmitted", permId=0),
        )
        self._trades.append(trade)
        return trade

    def cancelOrder(self, order: IBOrder, manualCancelOrderTime: str = "") -> Trade | None:
        self.cancelled.append(order)
        self._trades = [t for t in self._trades if t.order is not order]
        return None

    async def reqAllOpenOrdersAsync(self) -> list[Trade]:
        # Acknowledgement has happened by the time the broker is asked.
        for trade in self._trades:
            if not trade.order.permId:
                trade.order.permId = PERM_ID
                trade.orderStatus.permId = PERM_ID
                trade.orderStatus.whyHeld = "trigger"
        return list(self._trades)

    def positions(self, account: str = "") -> list[Any]:
        return []

    def accountSummary(self, account: str = "") -> list[Any]:
        return []


def _adopted_stop(perm_id: int = 777000777, client_id: int = 9) -> Trade:
    """A protective stop this application never placed - the adopted-position
    case, which has no local handle at all."""
    order = IBOrder(
        orderId=41,
        clientId=client_id,
        permId=perm_id,
        action="SELL",
        totalQuantity=5,
        orderType="STP",
        auxPrice=50.0,
        tif="GTC",
    )
    return Trade(
        contract=Contract(symbol="CBA", secType="STK", exchange="ASX", currency="AUD"),
        order=order,
        orderStatus=OrderStatus(orderId=41, status="PreSubmitted", permId=perm_id),
    )


def _adapter(client: AcknowledgingIB) -> IBAdapter:
    return IBAdapter(
        client,
        EventBus(),
        settings=Settings(
            _env_file=None, trading_mode="paper", market="ASX", ibkr_client_id=APP_CLIENT_ID
        ),
    )


def _protective() -> Order:
    return Order(
        symbol="BHP.AX",
        side="buy",
        quantity=1,
        order_id="app-1",
        stop_price=95.0,
        order_type="stop",
    )


async def test_the_scan_returns_an_id_the_app_did_not_register() -> None:
    """The precondition, asserted so the rest of this file cannot pass for the
    wrong reason. If placement ever starts registering the permId, this test
    fails and says so rather than leaving the others testing nothing."""
    client = AcknowledgingIB()
    adapter = _adapter(client)
    placed = await adapter.place_order(_protective())

    scanned = (await adapter.resting_stop_orders())["BHP.AX"]

    assert placed.order_id == "app-1"
    assert scanned.order_id == str(PERM_ID)


async def test_a_stop_found_by_the_scan_can_be_repriced() -> None:
    """M39's corporate-action path: read the resting stop, re-price it through
    a split. It called modify_order with the scan's id and got a KeyError."""
    client = AcknowledgingIB()
    adapter = _adapter(client)
    await adapter.place_order(_protective())
    scanned = (await adapter.resting_stop_orders())["BHP.AX"]

    await adapter.modify_order(scanned.order_id, stop_price=90.0)

    assert client.placed[-1].auxPrice == 90.0


async def test_a_stop_found_by_the_scan_can_be_cancelled() -> None:
    client = AcknowledgingIB()
    adapter = _adapter(client)
    await adapter.place_order(_protective())
    scanned = (await adapter.resting_stop_orders())["BHP.AX"]

    await adapter.cancel_order(scanned.order_id)

    assert client.cancelled, "the resting stop was never cancelled at the broker"


async def test_a_stop_this_app_never_placed_can_be_cancelled() -> None:
    """An adopted position carries protective orders with no local handle at
    all. Resolving against the broker reaches them; tightening the placement
    timing would not have."""
    client = AcknowledgingIB(adopted=[_adopted_stop()])
    adapter = _adapter(client)

    await adapter.cancel_order("777000777")

    assert client.cancelled, "an adopted position's stop stayed unreachable"


async def test_an_id_the_broker_does_not_know_still_fails() -> None:
    """Resolving must not become 'succeed quietly'. An id nobody has heard of
    is a bug in the caller, and swallowing it would leave the app believing it
    had cancelled something."""
    client = AcknowledgingIB()
    adapter = _adapter(client)

    with pytest.raises(KeyError):
        await adapter.cancel_order("no-such-order")


async def test_an_order_owned_by_another_client_is_flagged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Measured 19 August: a cancel from a different clientId fails with error
    10147 while reqAllOpenOrders() still shows the order and the local object
    reports PendingCancel. The attempt is still made - IBKR is the authority -
    but it must not fail silently in the log."""
    client = AcknowledgingIB(adopted=[_adopted_stop(client_id=9)])
    adapter = _adapter(client)

    with caplog.at_level(logging.WARNING):
        await adapter.cancel_order("777000777")

    assert any("clientId" in record.message for record in caplog.records), [
        r.message for r in caplog.records
    ]

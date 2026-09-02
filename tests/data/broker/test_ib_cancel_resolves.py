"""Task 1: `IBAdapter.cancel_order` must never claim a cancel it did not
perform.

`_ib_orders` and `_ib_groups` are empty for every order placed in a previous
session, because the live ib_async Order objects they hold do not survive a
restart - only the app-level `Order` does (loaded from persisted state, and
pre-registered directly in `_orders` below to model that). The old code took
that emptiness as "nothing to cancel" and reported success without ever
reaching the broker. These tests pin the fix: fall back to what the live
client still reports (`openTrades`, matched on permId - the id that DOES
survive a restart), and raise rather than lie when even that comes up empty.
"""

from __future__ import annotations

from typing import Any

import pytest
from ib_async import Contract
from ib_async.order import Order as IBOrder
from ib_async.order import OrderStatus, Trade

from qat.config import Settings
from qat.data.broker.adapter import Order
from qat.data.broker.ib_adapter import CancelNotResolvedError, IBAdapter
from qat.domain.bus import EventBus


class _RecordingIB:
    """Enough of `IBClientProtocol` to construct an `IBAdapter` and answer
    `cancel_order`'s live-client fallback. Modeled on `RecordingIB` in
    `test_ib_brackets.py`: `cancelOrder` pops the cancelled order out of what
    `openTrades()` reports, so the group-cancel's own still-resting re-check
    does not see a just-cancelled leg and cancel it a second time.
    """

    def __init__(self, resting: list[Trade] | None = None) -> None:
        self._resting: dict[int, Trade] = {t.order.orderId: t for t in resting or []}
        self.cancelled_perm_ids: list[int] = []

    def isConnected(self) -> bool:
        return True

    async def connectAsync(self, *args: Any, **kwargs: Any) -> None:
        return None

    def disconnect(self) -> None:
        return None

    async def reqCurrentTimeAsync(self) -> Any:
        return None

    def placeOrder(self, contract: Contract, order: IBOrder) -> Trade:
        raise NotImplementedError("not exercised by these tests")

    def cancelOrder(self, order: IBOrder, manualCancelOrderTime: str = "") -> Trade | None:
        self.cancelled_perm_ids.append(int(order.permId))
        return self._resting.pop(order.orderId, None)

    def openTrades(self) -> list[Trade]:
        return list(self._resting.values())

    def positions(self, account: str = "") -> list[Any]:
        return []

    def accountSummary(self, account: str = "") -> list[Any]:
        return []


def _settings() -> Settings:
    return Settings(_env_file=None, trading_mode="paper")


def _previous_session_order(order_id: str) -> Order:
    """The app `Order` for a permId this process never placed - the shape a
    restart leaves behind."""
    return Order(
        symbol="BHP",
        side="sell",
        quantity=10,
        order_id=order_id,
        stop_price=58.00,
    )


@pytest.fixture
def adapter_with_empty_maps() -> IBAdapter:
    """A previous-session leg the client has nothing to offer either: no
    `_ib_orders`/`_ib_groups` entry, and `openTrades()` reports it resting
    nowhere. There is genuinely no live order to resolve to."""
    adapter = IBAdapter(_RecordingIB(), EventBus(), settings=_settings())
    order = _previous_session_order("1216552518")
    adapter._orders[order.order_id] = order
    return adapter


@pytest.fixture
def adapter_with_live_trade() -> tuple[IBAdapter, _RecordingIB]:
    """Same previous-session shape, but this permId IS still resting at the
    broker - `reqAllOpenOrders`/`openTrades` is how a permId this session
    never placed becomes reachable again."""
    ib_order = IBOrder(
        orderId=501,
        permId=1216552518,
        action="SELL",
        orderType="STP",
        totalQuantity=10,
        auxPrice=58.00,
    )
    trade = Trade(
        contract=Contract(symbol="BHP"),
        order=ib_order,
        orderStatus=OrderStatus(orderId=501, status="PreSubmitted", permId=1216552518),
    )
    client = _RecordingIB(resting=[trade])
    adapter = IBAdapter(client, EventBus(), settings=_settings())
    order = _previous_session_order(str(ib_order.permId))
    adapter._orders[order.order_id] = order
    return adapter, client


@pytest.mark.asyncio
async def test_cancel_raises_when_the_order_cannot_be_resolved(adapter_with_empty_maps):
    """A cancel that reaches no broker must NOT report success.

    Before this, a leg from a previous session took the `if not group:` branch,
    was marked cancelled locally, and returned an Order with status
    "cancelled" - so a caller would go on to sell while both OCA legs were
    still resting, and be put short.
    """
    adapter = adapter_with_empty_maps
    with pytest.raises(CancelNotResolvedError) as excinfo:
        await adapter.cancel_order("1216552518")
    assert "1216552518" in str(excinfo.value)


@pytest.mark.asyncio
async def test_cancel_resolves_a_previous_session_order_from_the_live_client(
    adapter_with_live_trade,
):
    """reqAllOpenOrders populates the client's open trades, so a permId this
    session never placed is still resolvable - and must be cancelled for real."""
    adapter, client = adapter_with_live_trade
    result = await adapter.cancel_order("1216552518")
    assert result.status == "cancelled"
    assert client.cancelled_perm_ids == [1216552518]

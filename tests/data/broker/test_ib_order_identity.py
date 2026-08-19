"""The IBKR order-identity bridge (Task 3 of the IBKR move plan).

`from_ib_trade` used to update only `status` and `filled_price`. Alpaca's
adapter overwrites `order.order_id` with the broker's own id at transmit,
which is what lets `OMS._order_the_broker_calls` resolve an incoming fill
back to the order that produced it - IBAdapter did none of that, so on IBKR
that lookup could never match. `_correct_announced_price` (M70/M71) would
therefore return early on every IBKR fill, silently, and the app would keep
recording entry and exit prices it never paid.

Which id: `permId`, not `orderId`. ib_async's `Order.orderId` is the
CLIENT-side id, scoped to (clientId, session) - reused across restarts and
never sent back on an execution. `Execution.permId` (and `OrderStatus.permId`,
which mirrors it) is TWS-assigned, permanent and unique, which is what a
record meant to outlive the process needs. NOT YET CONFIRMED: the IBKR move
plan's Task 1 must verify permId survives a Gateway restart against the real
paper account - see `from_ib_trade`'s docstring.

Two internal dicts in IBAdapter are keyed by the app's OWN id at insertion -
`self._orders[order.order_id]` and `self._ib_orders[order.order_id]` - and
`modify_order`/`cancel_order` look up `self._ib_orders[order_id]`. Overwriting
`order.order_id` with the broker's id without also registering the order
under that new id means a caller holding the RETURNED order (the only id it
has after transmit) gets a KeyError on cancel - a protective order that
cannot be cancelled. `test_cancel_order_by_the_post_transmit_id_still_works`
is the test for that hazard.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from ib_async.order import OrderStatus, Trade

from qat.config import Settings
from qat.data.broker.adapter import BrokerFill, Order
from qat.data.broker.ib_adapter import IBAdapter
from qat.domain.bus import EventBus
from qat.domain.events import EntryPriceCorrectedEvent, ExitPriceCorrectedEvent
from qat.domain.oms.oms import OMS
from qat.domain.risk_engine.engine import RiskEngine
from qat.domain.risk_engine.kill_switch import KillSwitch


class FakeIBClient:
    """Enough of ib_async's IB for the identity bridge: `placeOrder` returns a
    real `Trade` carrying a configurable `permId`, `cancelOrder` is recorded,
    and nothing else is implemented - `get_market_data`'s AttributeError-and-
    fall-back-to-reference-price path (already exercised for Alpaca, since it
    never serves quotes either) covers the gap for `_costing_price`.

    `status` defaults to "Submitted" rather than "Filled": M70/M71 exist for
    exactly the case where IBKR acknowledges before it fills, and
    `from_ib_trade` leaves an unmapped intermediate status alone by design.
    """

    def __init__(self, perm_ids: list[int] | None = None, status: str = "Submitted") -> None:
        self._perm_ids = list(perm_ids or [])
        self._status = status
        self.placed_orders: list[tuple[Any, Any]] = []
        self.cancelled_orders: list[Any] = []

    def isConnected(self) -> bool:
        return True

    async def connectAsync(self, *args: Any, **kwargs: Any) -> None:
        return None

    def disconnect(self) -> None:
        return None

    async def reqCurrentTimeAsync(self) -> datetime:
        return datetime.now()

    def placeOrder(self, contract: Any, order: Any) -> Trade:
        self.placed_orders.append((contract, order))
        perm_id = self._perm_ids.pop(0) if self._perm_ids else 0
        order.permId = perm_id
        order_status = OrderStatus(
            status=self._status,
            avgFillPrice=0.0,
            filled=0,
            remaining=order.totalQuantity,
            permId=perm_id,
        )
        return Trade(contract=contract, order=order, orderStatus=order_status)

    def cancelOrder(self, order: Any, manualCancelOrderTime: str = "") -> Trade | None:
        self.cancelled_orders.append(order)
        return None

    def accountSummary(self, account: str = "") -> list[Any]:
        # Enough cash that the buy-side sign-off cost check never refuses -
        # this suite is about identity, not sizing.
        from ib_async import AccountValue

        return [
            AccountValue(
                account="DU1",
                tag="TotalCashValue",
                value="1000000",
                currency="USD",
                modelCode="",
            )
        ]

    def positions(self, account: str = "") -> list[Any]:
        return []


def _order(symbol: str = "AAPL", side: str = "buy", order_id: str = "app-order-1") -> Order:
    return Order(symbol=symbol, side=side, quantity=10, order_id=order_id)


def _oms(tmp_path, client: FakeIBClient) -> OMS:
    settings = Settings(_env_file=None, data_dir=str(tmp_path))
    bus = EventBus()
    switch = KillSwitch()
    adapter = IBAdapter(client, bus, settings=settings)
    return OMS(
        adapter, RiskEngine(bus, switch, settings=settings), switch, bus=bus, settings=settings
    )


# --- the hazard: cancellation after the id changes -----------------------------


@pytest.mark.asyncio
async def test_cancel_order_by_the_post_transmit_id_still_works(tmp_path):
    """The identifier a caller actually has after transmit is the RETURNED
    order's `order_id` - which is now the broker's permId, not the app's
    original id. Cancelling by it must not raise KeyError."""
    client = FakeIBClient(perm_ids=[555111222])
    adapter = IBAdapter(
        client, EventBus(), settings=Settings(_env_file=None, data_dir=str(tmp_path))
    )

    placed = await adapter.place_order(_order())
    assert placed.order_id == "555111222", "the id a post-transmit caller would hold"

    cancelled = await adapter.cancel_order(placed.order_id)

    assert cancelled.status == "cancelled"
    assert len(client.cancelled_orders) == 1


@pytest.mark.asyncio
async def test_modify_order_by_the_post_transmit_id_still_works(tmp_path):
    """Same hazard, the other lookup site."""
    client = FakeIBClient(perm_ids=[555111222])
    adapter = IBAdapter(
        client, EventBus(), settings=Settings(_env_file=None, data_dir=str(tmp_path))
    )

    placed = await adapter.place_order(_order())
    modified = await adapter.modify_order(placed.order_id, limit_price=101.5)

    assert modified.limit_price == 101.5


@pytest.mark.asyncio
async def test_cancel_order_by_the_original_app_id_still_works_too(tmp_path):
    """OMS's own bookkeeping never learns the new id - `_sign_off_locked` keys
    `self._orders` by the id it minted before transmit and never re-keys it -
    so `OMS.cancel_order` always calls the broker back with that original id.
    Both callers have to be served from the same registration."""
    client = FakeIBClient(perm_ids=[555111222])
    adapter = IBAdapter(
        client, EventBus(), settings=Settings(_env_file=None, data_dir=str(tmp_path))
    )

    placed = await adapter.place_order(_order(order_id="app-order-1"))
    assert placed.order_id != "app-order-1"

    cancelled = await adapter.cancel_order("app-order-1")

    assert cancelled.status == "cancelled"
    assert len(client.cancelled_orders) == 1


# --- the translation itself -----------------------------------------------------


@pytest.mark.asyncio
async def test_place_order_writes_the_perm_id_as_the_order_id(tmp_path):
    client = FakeIBClient(perm_ids=[42])
    adapter = IBAdapter(
        client, EventBus(), settings=Settings(_env_file=None, data_dir=str(tmp_path))
    )

    placed = await adapter.place_order(_order())

    assert placed.order_id == "42"


@pytest.mark.asyncio
async def test_a_missing_perm_id_does_not_write_a_junk_identifier(tmp_path):
    """permId is 0 until IBKR acknowledges, which `placeOrder` does not wait
    for - the id must not become the string "0"."""
    client = FakeIBClient(perm_ids=[])  # nothing queued -> permId stays 0
    adapter = IBAdapter(
        client, EventBus(), settings=Settings(_env_file=None, data_dir=str(tmp_path))
    )

    placed = await adapter.place_order(_order(order_id="app-order-1"))

    assert placed.order_id == "app-order-1"
    assert placed.order_id != "0"


@pytest.mark.asyncio
async def test_a_zero_perm_id_order_can_still_be_cancelled_by_its_original_id(tmp_path):
    client = FakeIBClient(perm_ids=[])
    adapter = IBAdapter(
        client, EventBus(), settings=Settings(_env_file=None, data_dir=str(tmp_path))
    )
    placed = await adapter.place_order(_order(order_id="app-order-1"))

    cancelled = await adapter.cancel_order(placed.order_id)

    assert cancelled.status == "cancelled"


# --- the acceptance test: resolution through OMS --------------------------------


@pytest.mark.asyncio
async def test_ibkr_fill_resolves_back_to_the_order_that_produced_it(tmp_path):
    """The whole point. An incoming fill carrying IBKR's own identity must
    resolve, through `OMS._order_the_broker_calls`, to the very order object
    that produced it - not merely to a field that looks right."""
    client = FakeIBClient(perm_ids=[987654321])
    oms = _oms(tmp_path, client)
    order = oms._new_pending_order("AAPL", "buy", 10, reference_price=100.0)

    signed = await oms.sign_off(order.order_id, "operator")
    assert signed.order_id == "987654321"

    resolved = oms._order_the_broker_calls("987654321")

    assert resolved is signed


@pytest.mark.asyncio
async def test_an_unknown_broker_id_resolves_to_nothing(tmp_path):
    client = FakeIBClient(perm_ids=[987654321])
    oms = _oms(tmp_path, client)
    order = oms._new_pending_order("AAPL", "buy", 10, reference_price=100.0)
    await oms.sign_off(order.order_id, "operator")

    assert oms._order_the_broker_calls("some-other-broker-id") is None


# --- M70/M71 actually wake up on the IBKR path -----------------------------------


@pytest.mark.asyncio
async def test_m70_entry_price_correction_wakes_up_through_the_ibkr_path(tmp_path):
    """Without the identity bridge, `_order_the_broker_calls` never matches an
    IBKR fill and this returns having done nothing - the exact silent
    regression the IBKR move plan calls out. `recent_fills` (Task 2) is not
    implemented yet, so this drives `_correct_announced_price` directly with a
    fill shaped exactly as a future `recent_fills` would report it - the
    resolution mechanism under test is identical either way."""
    client = FakeIBClient(perm_ids=[111000111])
    oms = _oms(tmp_path, client)
    bus = oms.bus
    received: list[EntryPriceCorrectedEvent] = []

    async def _capture(event: EntryPriceCorrectedEvent) -> None:
        received.append(event)

    bus.subscribe(EntryPriceCorrectedEvent, _capture)

    order = oms._new_pending_order("AAPL", "buy", 10, reference_price=100.0)
    signed = await oms.sign_off(order.order_id, "operator")
    # IBKR's "Submitted" is not in `_IB_STATUS_MAP` - it maps only terminal
    # states - so nothing here has a fill price yet. That absence is the M70
    # window: `_announce_fill` has already published the reference price.
    assert signed.filled_price is None

    fill = BrokerFill(
        order_id="111000111",
        symbol="AAPL",
        side="buy",
        quantity=10,
        price=101.41,
        filled_at=datetime.now(UTC),
    )
    await oms._correct_announced_price(fill)

    assert signed.filled_price == pytest.approx(101.41)
    assert len(received) == 1
    assert received[0].symbol == "AAPL"
    assert received[0].price == pytest.approx(101.41)
    assert received[0].announced_price == pytest.approx(100.0)


@pytest.mark.asyncio
async def test_m71_exit_price_correction_wakes_up_through_the_ibkr_path(tmp_path):
    """The sell-side twin. A resting exit acknowledged by IBKR, then filled at
    a price different from the one announced at transmit."""
    client = FakeIBClient(perm_ids=[222000222])
    oms = _oms(tmp_path, client)
    bus = oms.bus
    received: list[ExitPriceCorrectedEvent] = []

    async def _capture(event: ExitPriceCorrectedEvent) -> None:
        received.append(event)

    bus.subscribe(ExitPriceCorrectedEvent, _capture)

    order = oms._new_pending_order("AAPL", "sell", 10, reference_price=100.0)
    signed = await oms.sign_off(order.order_id, "operator")
    assert signed.filled_price is None

    fill = BrokerFill(
        order_id="222000222",
        symbol="AAPL",
        side="sell",
        quantity=10,
        price=98.55,
        filled_at=datetime.now(UTC),
    )
    await oms._correct_announced_price(fill)

    assert signed.filled_price == pytest.approx(98.55)
    assert len(received) == 1
    assert received[0].price == pytest.approx(98.55)

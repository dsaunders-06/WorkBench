"""M95 Stage B: transmitting protection that comes in more than one order.

Stage A made `to_ib_order` refuse a bracketed entry and a stop carrying a
target, because one `IBOrder` cannot express either. This transmits them.

**IBKR brackets are ORDERED, and the ordering is the trap.** Parent and
take-profit go with `transmit=False`; only the final leg carries
`transmit=True`, and that is what releases the whole group. A bracket sent
without that final flag sits at IBKR untransmitted - protection that exists in
our records and not at the broker. Same failure class as the defect Stage A
fixed, one level down, which is why
`test_only_the_final_leg_transmits` exists.

**One app Order now maps to THREE IBKR orders**, so the bookkeeping is the
real work rather than the translation. `modify_order` repricing a stop must
reach the STOP LEG - repricing the parent would edit the entry and report
success, which is M39's corporate-action path failing quietly.

**Cancellation is verified, not assumed.** IBKR cascades a parent cancel to
its children, and on 19 August a cancel reported `PendingCancel` while being
rejected outright (error 10147, wrong clientId). An orphaned stop resting
against a position that no longer exists is worth the extra read.
"""

from __future__ import annotations

from typing import Any

from ib_async import Contract
from ib_async.order import Order as IBOrder
from ib_async.order import OrderStatus, Trade

from qat.config import Settings
from qat.data.broker.adapter import Order
from qat.data.broker.ib_adapter import IBAdapter
from qat.domain.bus import EventBus


class RecordingIB:
    """A Gateway that assigns order ids and remembers what rests.

    `placeOrder` assigns `orderId` when unset, because **real ib_async does**
    (`IB.placeOrder`: `if not order.orderId: order.orderId =
    self.client.getReqId()`). The adapter relies on that to learn the parent's
    id before building children, which is what lets it avoid reaching through
    `IBClientProtocol` for `client.getReqId()`. If ib_async ever stops doing
    it, this fake is where the assumption is written down.
    """

    def __init__(self, cascade_cancel: bool = True, flaky_child_cancel: bool = False) -> None:
        self._next_id = 100
        self._next_perm = 5000
        self.cascade_cancel = cascade_cancel
        # First cancel attempt on a child is silently ignored. Models the
        # 19 August observation that a cancel can report progress while
        # achieving nothing - the reason the group cancel re-reads.
        self.flaky_child_cancel = flaky_child_cancel
        self._child_cancel_attempts: set[int] = set()
        self.placed: list[IBOrder] = []
        self.cancelled: list[IBOrder] = []
        self._resting: dict[int, Trade] = {}

    def isConnected(self) -> bool:
        return True

    async def connectAsync(self, *args: Any, **kwargs: Any) -> None:
        return None

    def disconnect(self) -> None:
        return None

    async def reqCurrentTimeAsync(self) -> Any:
        return None

    def placeOrder(self, contract: Contract, order: IBOrder) -> Trade:
        if not order.orderId:
            order.orderId = self._next_id
            self._next_id += 1
        if not order.permId:
            order.permId = self._next_perm
            self._next_perm += 1
        self.placed.append(order)
        trade = Trade(
            contract=contract,
            order=order,
            orderStatus=OrderStatus(
                orderId=order.orderId, status="PreSubmitted", permId=order.permId
            ),
        )
        self._resting[order.orderId] = trade
        return trade

    def cancelOrder(self, order: IBOrder, manualCancelOrderTime: str = "") -> Trade | None:
        self.cancelled.append(order)
        if self.flaky_child_cancel and order.parentId:
            if order.orderId not in self._child_cancel_attempts:
                self._child_cancel_attempts.add(order.orderId)
                return None
        trade = self._resting.pop(order.orderId, None)
        if self.cascade_cancel:
            for oid, resting in list(self._resting.items()):
                if resting.order.parentId == order.orderId:
                    self._resting.pop(oid)
        return trade

    def openTrades(self) -> list[Trade]:
        return list(self._resting.values())

    def positions(self, account: str = "") -> list[Any]:
        return []

    def accountSummary(self, account: str = "") -> list[Any]:
        return []


def _adapter(client: RecordingIB) -> IBAdapter:
    return IBAdapter(client, EventBus(), settings=Settings(_env_file=None, trading_mode="paper"))


def _bracketed_entry(**overrides: Any) -> Order:
    fields: dict[str, Any] = {
        "symbol": "BHP",
        "side": "buy",
        "quantity": 10,
        "order_id": "app-entry",
        "stop_price": 58.00,
        "take_profit_price": 70.00,
    }
    fields.update(overrides)
    return Order(**fields)


def _by_type(placed: list[IBOrder], order_type: str) -> list[IBOrder]:
    return [o for o in placed if o.orderType == order_type]


async def test_a_bracketed_entry_transmits_three_orders() -> None:
    client = RecordingIB()

    await _adapter(client).place_order(_bracketed_entry())

    assert len(client.placed) == 3, [o.orderType for o in client.placed]
    assert len(_by_type(client.placed, "MKT")) == 1
    assert len(_by_type(client.placed, "LMT")) == 1
    assert len(_by_type(client.placed, "STP")) == 1


async def test_only_the_final_leg_transmits() -> None:
    """The trap. IBKR holds a bracket until a leg arrives with transmit=True;
    without it the whole group sits untransmitted and the app believes the
    position is protected while nothing rests at the broker."""
    client = RecordingIB()

    await _adapter(client).place_order(_bracketed_entry())

    assert [o.transmit for o in client.placed] == [False, False, True], [
        (o.orderType, o.transmit) for o in client.placed
    ]


async def test_the_protective_legs_reference_the_parent() -> None:
    client = RecordingIB()

    await _adapter(client).place_order(_bracketed_entry())

    parent, *legs = client.placed
    assert parent.orderId, "the parent was never assigned an order id"
    assert parent.parentId == 0
    for leg in legs:
        assert leg.parentId == parent.orderId, (
            "a protective leg is not attached to its entry - it would activate "
            "immediately instead of on the fill"
        )


async def test_the_protective_legs_are_gtc() -> None:
    """M31b. DAY killed every stop this system ever placed."""
    client = RecordingIB()

    await _adapter(client).place_order(_bracketed_entry())

    for leg in client.placed[1:]:
        assert leg.tif == "GTC", (leg.orderType, leg.tif)


async def test_the_protective_legs_reverse_the_entry_side() -> None:
    """Legs that repeat the entry's side would double the position rather than
    close it."""
    client = RecordingIB()

    await _adapter(client).place_order(_bracketed_entry(side="buy"))

    assert client.placed[0].action == "BUY"
    assert [leg.action for leg in client.placed[1:]] == ["SELL", "SELL"]


async def test_the_legs_carry_their_prices() -> None:
    client = RecordingIB()

    await _adapter(client).place_order(_bracketed_entry(stop_price=58.0, take_profit_price=70.0))

    assert _by_type(client.placed, "LMT")[0].lmtPrice == 70.0
    assert _by_type(client.placed, "STP")[0].auxPrice == 58.0


async def test_a_standalone_stop_with_a_target_transmits_as_an_oca_pair() -> None:
    """M33: a resting stop and a resting limit for the same shares are not
    independent. If price runs to the target and later gaps back through the
    stop, both fill and a protected long becomes an accidental short. OCA is
    what makes them mutually exclusive AT THE BROKER."""
    client = RecordingIB()
    protective = Order(
        symbol="BHP",
        side="sell",
        quantity=10,
        order_id="app-oco",
        stop_price=58.00,
        take_profit_price=70.00,
        order_type="stop",
    )

    await _adapter(client).place_order(protective)

    assert len(client.placed) == 2, [o.orderType for o in client.placed]
    groups = {o.ocaGroup for o in client.placed}
    assert len(groups) == 1 and groups != {""}, [o.ocaGroup for o in client.placed]
    assert all(o.ocaType for o in client.placed)
    assert {o.orderType for o in client.placed} == {"STP", "LMT"}
    assert all(o.parentId == 0 for o in client.placed), (
        "a standalone protective pair has no entry to attach to - a parentId "
        "would make both legs wait for a fill that never comes"
    )


async def test_cancelling_a_bracket_cancels_every_leg() -> None:
    client = RecordingIB()
    adapter = _adapter(client)
    placed = await adapter.place_order(_bracketed_entry())

    await adapter.cancel_order(placed.order_id)

    assert client.openTrades() == [], [t.order.orderType for t in client.openTrades()]


async def test_a_leg_surviving_the_parent_cancel_is_cancelled_individually() -> None:
    """IBKR normally cascades a parent cancel to its children. 'Normally' is
    not a guarantee this project accepts: on 19 August a cancel reported
    PendingCancel while being rejected outright. An orphaned stop resting
    against a position that no longer exists is what this prevents."""
    client = RecordingIB(cascade_cancel=False)
    adapter = _adapter(client)
    placed = await adapter.place_order(_bracketed_entry())

    await adapter.cancel_order(placed.order_id)

    assert client.openTrades() == [], (
        "legs survived the parent cancel and were not cleaned up - the cascade "
        "was assumed rather than verified"
    )
    assert len(client.cancelled) == 3


async def test_modify_reprices_the_stop_leg_not_the_parent() -> None:
    """M39 re-prices a resting stop through a corporate action. Repricing the
    parent would edit the entry order and report success, leaving the
    protective level exactly where it was - the MNST shape."""
    client = RecordingIB()
    adapter = _adapter(client)
    placed = await adapter.place_order(_bracketed_entry())
    parent = client.placed[0]

    await adapter.modify_order(placed.order_id, stop_price=61.50)

    stop_leg = _by_type(client.placed, "STP")[0]
    assert stop_leg.auxPrice == 61.50
    assert (
        parent.orderType == "MKT" and parent.auxPrice != 61.50
    ), "the entry order was repriced instead of the stop leg"


async def test_modify_reprices_the_take_profit_leg() -> None:
    client = RecordingIB()
    adapter = _adapter(client)
    placed = await adapter.place_order(_bracketed_entry())

    await adapter.modify_order(placed.order_id, take_profit_price=75.00)

    assert _by_type(client.placed, "LMT")[0].lmtPrice == 75.00


async def test_every_leg_is_asked_to_cancel_not_just_the_parent() -> None:
    """Separated from the cascade, deliberately. With IBKR cascading, an
    assertion on what RESTS afterwards passes even if only the parent was
    ever cancelled - so it cannot tell the two mechanisms apart. This asserts
    the requests themselves."""
    client = RecordingIB(cascade_cancel=True)
    adapter = _adapter(client)
    placed = await adapter.place_order(_bracketed_entry())

    await adapter.cancel_order(placed.order_id)

    assert len(client.cancelled) == 3, [o.orderType for o in client.cancelled]


async def test_a_cancel_that_silently_achieves_nothing_is_retried() -> None:
    """The 19 August observation, as a test: a cancel reported PendingCancel
    while being rejected outright. Cancelling is not the same as CANCELLED,
    and only a re-read can tell the difference."""
    client = RecordingIB(cascade_cancel=False, flaky_child_cancel=True)
    adapter = _adapter(client)
    placed = await adapter.place_order(_bracketed_entry())

    await adapter.cancel_order(placed.order_id)

    assert client.openTrades() == [], (
        "legs whose first cancel silently failed are still resting - the "
        "cancellation was announced rather than confirmed"
    )

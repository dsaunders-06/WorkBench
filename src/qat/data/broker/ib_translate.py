"""Pure translation between our BrokerAdapter types (Order/Position/
AccountSummary - qat.data.broker.adapter) and ib_async's Contract/Order/
Trade/Position/AccountValue. No I/O here, just data-shape conversion -
testable with real ib_async data classes, which are plain constructible
objects requiring no network connection.
"""

from __future__ import annotations

from ib_async import AccountValue, Contract, Stock
from ib_async import Position as IBPosition
from ib_async.order import LimitOrder, MarketOrder, Trade
from ib_async.order import Order as IBOrder

from qat.data.broker.adapter import AccountSummary, Order, OrderStatus, Position

_ACCOUNT_TAGS = ("NetLiquidation", "TotalCashValue", "BuyingPower")

_IB_STATUS_MAP: dict[str, OrderStatus] = {
    "Filled": "filled",
    "Cancelled": "cancelled",
    "ApiCancelled": "cancelled",
    "Inactive": "rejected",
}


def to_ib_contract(symbol: str, exchange: str = "SMART", currency: str = "USD") -> Contract:
    return Stock(symbol, exchange, currency)


def to_ib_order(order: Order) -> IBOrder:
    action = "BUY" if order.side == "buy" else "SELL"
    if order.limit_price is not None:
        return LimitOrder(action, order.quantity, order.limit_price)
    return MarketOrder(action, order.quantity)


def from_ib_trade(trade: Trade, our_order: Order) -> Order:
    """Updates our Order's status/fill fields from an ib_async Trade, and
    carries the broker's own order identity onto `our_order.order_id` -
    mirroring what AlpacaAdapter does at transmit (three sites).
    Intermediate IBKR states (Submitted/PreSubmitted/PendingSubmit) aren't
    in the map - they leave our own already-set "transmitted" status alone
    rather than guessing at a mapping.

    The identity bridge (IBKR move plan, Task 3): `OMS._order_the_broker_calls`
    resolves an incoming fill by comparing `order.order_id` against the raw
    fill's `order_id`. Without this, that comparison could never succeed for
    an IBKR fill, so `_correct_announced_price` (M70/M71) went dormant
    without erroring - the app kept recording entry and exit prices it never
    paid.

    `permId`, not `orderId`. ib_async's `Order.orderId` is IBKR's CLIENT-side
    id: scoped to (clientId, session), reused across restarts, and never
    reported back on an `Execution`. `Execution.permId` (mirrored here on
    `OrderStatus.permId` and `Order.permId`) is TWS-assigned, permanent and
    unique - the property a record meant to outlive the session needs.
    **NOT YET CONFIRMED**: the IBKR move plan's Task 1 must verify permId
    actually survives a Gateway restart against the real paper account
    before this is relied on beyond a single session.

    permId can be legitimately absent (0) here: `IB.placeOrder` returns a
    `Trade` before TWS has acknowledged the order, so `trade.order.permId`
    is frequently still unset at this exact call. Writing "0" as an id would
    make every such order collide with every other unacknowledged order, so
    an absent/zero permId leaves `our_order.order_id` exactly as it was
    (the app's own id) rather than write a junk identifier.
    """
    mapped = _IB_STATUS_MAP.get(trade.orderStatus.status)
    if mapped is not None:
        our_order.status = mapped
    if trade.orderStatus.avgFillPrice:
        our_order.filled_price = trade.orderStatus.avgFillPrice
    perm_id = trade.order.permId or trade.orderStatus.permId
    if perm_id:
        our_order.order_id = str(perm_id)
    return our_order


def from_ib_position(position: IBPosition) -> Position:
    return Position(
        symbol=position.contract.symbol,
        quantity=position.position,
        avg_price=position.avgCost,
    )


def from_ib_account_values(values: list[AccountValue]) -> AccountSummary:
    by_tag: dict[str, float] = {}
    for value in values:
        if value.tag in _ACCOUNT_TAGS:
            try:
                by_tag[value.tag] = float(value.value)
            except ValueError:
                continue
    return AccountSummary(
        net_liquidation=by_tag.get("NetLiquidation", 0.0),
        cash=by_tag.get("TotalCashValue", 0.0),
        buying_power=by_tag.get("BuyingPower", 0.0),
    )

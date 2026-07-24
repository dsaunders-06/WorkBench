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
    """Updates our Order's status/fill fields from an ib_async Trade.
    Intermediate IBKR states (Submitted/PreSubmitted/PendingSubmit) aren't
    in the map - they leave our own already-set "transmitted" status alone
    rather than guessing at a mapping."""
    mapped = _IB_STATUS_MAP.get(trade.orderStatus.status)
    if mapped is not None:
        our_order.status = mapped
    if trade.orderStatus.avgFillPrice:
        our_order.filled_price = trade.orderStatus.avgFillPrice
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

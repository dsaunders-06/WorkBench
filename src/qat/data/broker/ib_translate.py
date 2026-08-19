"""Pure translation between our BrokerAdapter types (Order/Position/
AccountSummary - qat.data.broker.adapter) and ib_async's Contract/Order/
Trade/Position/AccountValue. No I/O here, just data-shape conversion -
testable with real ib_async data classes, which are plain constructible
objects requiring no network connection.
"""

from __future__ import annotations

from ib_async import AccountValue, Contract, Stock
from ib_async import Position as IBPosition
from ib_async.order import LimitOrder, MarketOrder, StopOrder, Trade
from ib_async.order import Order as IBOrder

from qat.data.broker.adapter import AccountSummary, Order, OrderStatus, Position


class UnrepresentableOrderError(ValueError):
    """Raised when `to_ib_order` cannot faithfully express an app Order."""


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
    """Translate an app Order, or refuse - never approximate it (M95).

    This branched on `limit_price` alone, so a protective stop
    (`order_type="stop"`, `stop_price` set, `limit_price=None`) fell through
    to `MarketOrder`. A market sell does not protect a position, it closes it
    at whatever the book offers - the `Order` dataclass warns about exactly
    that, in M31d's comment: "submitting it as one would liquidate the
    position it was meant to protect."

    The refusals matter as much as the branches. An order this cannot express
    must raise, because the failure it replaces was silent: a plausible order
    went to the broker and nothing anywhere said the intent had been lost.
    """
    action = "BUY" if order.side == "buy" else "SELL"

    if order.order_type == "stop":
        if order.stop_price is None:
            raise UnrepresentableOrderError(f"stop order for {order.symbol} has no stop price")
        if order.take_profit_price is not None:
            # A stop that also carries a target is ONE OCO, never two
            # independent orders (M33). A resting stop and a resting limit for
            # the same shares are not independent: if price runs to the target
            # and later gaps back through the stop, BOTH fill and a protected
            # long becomes an accidental short. Returning the stop alone would
            # keep the protection and silently discard the target - and
            # `is_bracket` is False for `order_type="stop"`, so the guard
            # below never sees this case. Refused until Stage B.
            raise UnrepresentableOrderError(
                f"protective order for {order.symbol} carries a take-profit "
                f"({order.take_profit_price}) and must be transmitted as one OCO; "
                "IBKR OCA transmission is not implemented - refusing rather than "
                "dropping the target leg"
            )
        # GTC unconditionally, mirroring AlpacaAdapter. DAY killed every stop
        # this system ever placed: on 31 July six positions filled with
        # brackets attached, the take-profit legs expired at the close, the
        # paired stops were cancelled with them as OCO does, and about $36,000
        # sat through a three-day weekend with no protection at the broker.
        # A stop meant to outlive the application must outlive the session.
        return StopOrder(action, order.quantity, order.stop_price, tif="GTC")

    if order.is_bracket:
        # An entry whose protection rides along as bracket legs. One IBOrder
        # cannot carry them - IBKR wants a parent and two children in an OCA
        # group - so returning a bare order here would place the entry and
        # silently drop the protection, opening a position the app believes
        # is protected. Refused until M95 Stage B can transmit the legs: a
        # rejected entry is recoverable, an unprotected position is the MNST
        # failure.
        raise UnrepresentableOrderError(
            f"entry for {order.symbol} carries protective legs (stop="
            f"{order.stop_price}, target={order.take_profit_price}) and IBKR "
            "bracket transmission is not implemented - refusing rather than "
            "placing it unprotected"
        )

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
    **CONFIRMED 19 August** against paper account DUQ200898: a GTC stop was
    left resting, IB Gateway restarted, and the order re-read - permId
    828725903 was unchanged. (`orderId` also happened to survive, which is
    not a reason to prefer it: its hazard was never mutation but REUSE for a
    different order in a later session.) See
    `docs/superpowers/specs/2026-08-19-ibkr-capability-measurement.md`.

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

"""Pure translation between our BrokerAdapter types (Order/Position/
AccountSummary - qat.data.broker.adapter) and ib_async's Contract/Order/
Trade/Position/AccountValue. No I/O here, just data-shape conversion -
testable with real ib_async data classes, which are plain constructible
objects requiring no network connection.
"""

from __future__ import annotations

import logging

from ib_async import AccountValue, Contract, Fill, Stock
from ib_async import Position as IBPosition
from ib_async.order import LimitOrder, MarketOrder, StopOrder, Trade
from ib_async.order import Order as IBOrder

from qat.data.broker.adapter import (
    AccountSummary,
    BrokerFill,
    Order,
    OrderStatus,
    Position,
    RestingOrder,
    RestingStopOrder,
)
from qat.data.symbols import from_ibkr, to_ibkr

logger = logging.getLogger(__name__)


class UnrepresentableOrderError(ValueError):
    """Raised when `to_ib_order` cannot faithfully express an app Order."""


# GrossPositionValue since M133: exposure means the market value of what is
# HELD, and deriving it from `equity - cash` counted AccruedCash as though it
# were invested.
_ACCOUNT_TAGS = ("NetLiquidation", "TotalCashValue", "BuyingPower", "GrossPositionValue")

# ⚠️ THE WORKING STATES WERE MISSING, and their absence transmitted four
# positions on 24 August 2026 instead of one.
#
# IBKR reports a live order as PendingSubmit -> PreSubmitted -> Submitted.
# None of those was here, so `_IB_STATUS_MAP.get(...)` returned None,
# `from_ib_order` left the status ALONE, and an order that had just been
# transmitted came back still carrying `pending_signoff`. `OMS.pending_orders`
# filters on exactly that value, so `AutonomousExecutor.retry_pending` found it
# again sixty seconds later, the gate allowed it again, and it was transmitted
# again - four times for TNE.AX and DXS.AX before the session was stopped,
# leaving 4x the intended quantity at the broker and no position record at all.
#
# The comment at the OMS sign-off site was right in principle - "the returned
# order carries the broker's own status, mapped by the adapter; setting it
# ourselves would overwrite the one authoritative answer with a guess". It was
# defeated by a map with four entries, so nobody set it at all.
#
# DEFAULTS TO "transmitted", never to leaving the caller's value. This mirrors
# `alpaca_adapter._STATUS_MAP`, whose own note says "anything unrecognised maps
# to transmitted rather than a terminal state" - the sibling that had this right
# all along. After a place_order that did NOT raise, the broker has the order;
# the only safe unknown is "live at the broker", never "still needs signing".
_IB_STATUS_MAP: dict[str, OrderStatus] = {
    "Filled": "filled",
    "Cancelled": "cancelled",
    "ApiCancelled": "cancelled",
    "Inactive": "rejected",
    # Working states. A partial fill reports Submitted with a non-zero filled
    # quantity, so "transmitted" is right for it too - it is live at the broker
    # and must not be re-signed.
    "PendingSubmit": "transmitted",
    "PreSubmitted": "transmitted",
    "Submitted": "transmitted",
    "ApiPending": "transmitted",
    "PendingCancel": "transmitted",
}


# What a market means to IBKR: (currency, primaryExchange). SMART routes in
# both cases; `primaryExchange` is what disambiguates a symbol listed on more
# than one venue. Keyed on `Settings.market`, which already exists as
# Literal["US", "ASX"] and which the universe and cost profiles key off too -
# a third market is added here deliberately, not inferred (M96).
_MARKET_CONTRACT: dict[str, tuple[str, str]] = {
    "US": ("USD", ""),
    "ASX": ("AUD", "ASX"),
}


def to_ib_contract(symbol: str, market: str = "US") -> Contract:
    """The IBKR contract for one of the app's symbols (M96).

    Took `exchange`/`currency` as defaulted arguments that `place_order` never
    supplied, so every contract was SMART/USD whatever market the application
    was configured for. Measured against the live paper Gateway on 19 August:

    * `Stock("BHP.AX", "SMART", ...)` -> **error 200, no security definition**,
      in AUD as well as USD. Every ASX order rejected outright.
    * `Stock("BHP", "SMART", "USD")` -> conId 4986, NYSE, "BHP GROUP LTD-SPON
      ADR" - a different instrument from conId 4036812 on ASX.

    The suffix is stripped at the vendor boundary (`symbols.to_ibkr`), which is
    M26's pattern rather than a new one.
    """
    currency, primary_exchange = _MARKET_CONTRACT[market]
    base = to_ibkr(symbol)
    if primary_exchange:
        return Stock(base, "SMART", currency, primaryExchange=primary_exchange)
    return Stock(base, "SMART", currency)


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


def to_ib_parent(order: Order) -> IBOrder:
    """The entry leg of a bracket, deliberately NOT transmitted.

    IBKR holds a bracket until a leg arrives with `transmit=True`. Sending the
    parent transmitted would release the entry ahead of its protection, which
    is a naked position for as long as the next two calls take.
    """
    action = "BUY" if order.side == "buy" else "SELL"
    # GTC explicitly, matching AlpacaAdapter's rule that anything CARRYING
    # protective legs is GTC (M31b) - and because leaving it unset does not
    # mean "IBKR's default". Measured live: IBKR answered warning 10349,
    # "Order TIF was set to DAY based on order preset", so a Gateway-side
    # preset chose the TIF instead of this application (M96).
    if order.limit_price is not None:
        return LimitOrder(action, order.quantity, order.limit_price, tif="GTC", transmit=False)
    return MarketOrder(action, order.quantity, tif="GTC", transmit=False)


def to_ib_protective_legs(order: Order, parent_id: int) -> list[IBOrder]:
    """The take-profit and stop legs of a bracket, attached to `parent_id`.

    Ordering is load-bearing. Only the LAST leg carries `transmit=True`, and
    that is what releases the whole group - a bracket sent without it sits at
    IBKR untransmitted, so the app believes the position is protected while
    nothing rests at the broker.

    The legs REVERSE the entry's side: they exist to close the position, and
    a leg repeating the entry's side would double it.

    GTC on both (M31b). DAY killed every stop this system ever placed - on
    31 July six positions filled with brackets attached, the take-profit legs
    expired at the close, the paired stops were cancelled with them as OCA
    does, and about $36,000 sat through a three-day weekend unprotected.
    """
    reverse = "SELL" if order.side == "buy" else "BUY"
    legs: list[IBOrder] = []
    if order.take_profit_price is not None:
        legs.append(
            LimitOrder(
                reverse,
                order.quantity,
                order.take_profit_price,
                parentId=parent_id,
                tif="GTC",
                transmit=False,
            )
        )
    if order.stop_price is not None:
        legs.append(
            StopOrder(
                reverse,
                order.quantity,
                order.stop_price,
                parentId=parent_id,
                tif="GTC",
                transmit=False,
            )
        )
    if legs:
        legs[-1].transmit = True
    return legs


def to_ib_oca_pair(order: Order, oca_group: str) -> list[IBOrder]:
    """A standalone protective stop and target as ONE OCA group (M33).

    A resting stop and a resting limit for the same shares are not
    independent: if price runs to the target and later gaps back through the
    stop, BOTH fill and a protected long becomes an accidental short. The OCA
    group is what makes them mutually exclusive AT THE BROKER, which is the
    property a bracket had before its legs expired.

    No `parentId`: there is no entry to attach to. These protect a position
    already held, and a parentId would leave both legs waiting for a fill that
    never comes.
    """
    if order.stop_price is None or order.take_profit_price is None:
        raise UnrepresentableOrderError(
            f"OCA pair for {order.symbol} needs both a stop and a target "
            f"(stop={order.stop_price}, target={order.take_profit_price})"
        )
    action = "BUY" if order.side == "buy" else "SELL"
    pair = [
        LimitOrder(action, order.quantity, order.take_profit_price, tif="GTC"),
        StopOrder(action, order.quantity, order.stop_price, tif="GTC"),
    ]
    # ocaType 1: cancel the remaining order outright when one fills. Reducing
    # (2 and 3) would leave a partial resting against shares already sold.
    for leg in pair:
        leg.ocaGroup = oca_group
        leg.ocaType = 1
    return pair


def from_ib_trade(trade: Trade, our_order: Order) -> Order:
    """Updates our Order's status/fill fields from an ib_async Trade, and
    carries the broker's own order identity onto `our_order.order_id` -
    mirroring what AlpacaAdapter does at transmit (three sites).
    ⚠️ THAT LAST SENTENCE USED TO READ: "Intermediate IBKR states
    (Submitted/PreSubmitted/PendingSubmit) aren't in the map - they leave our
    own already-set 'transmitted' status alone rather than guessing at a
    mapping." It was true when written and false by 24 August 2026, and the gap
    transmitted four positions instead of one.

    **M31a removed the pre-set.** `OMS._sign_off_locked` used to run
    `order.status = "transmitted"` BEFORE calling `place_order`, and M31a took
    it out for a good reason - when `place_order` raised, the order kept a
    status claiming it was live at the broker. But `place_order` returns
    `from_ib_trade(trade, order)` and never sets the status itself, so with the
    pre-set gone and the working states unmapped, NOBODY set it: a transmitted
    order came back still reading `pending_signoff`, and the retry sweep
    transmitted it again every sixty seconds.

    Two individually correct decisions that combined into a defect - the shape
    this codebase calls "check whether the fix has a sibling". The working
    states are mapped now and the assignment is unconditional, so this function
    no longer depends on any caller having set anything first.

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
    # Unconditional. The old form only assigned when the status was recognised,
    # which meant an unrecognised one silently preserved `pending_signoff` - see
    # the note on _IB_STATUS_MAP.
    our_order.status = _IB_STATUS_MAP.get(trade.orderStatus.status, "transmitted")
    if trade.orderStatus.avgFillPrice:
        our_order.filled_price = trade.orderStatus.avgFillPrice
    perm_id = trade.order.permId or trade.orderStatus.permId
    if perm_id:
        our_order.order_id = str(perm_id)
    return our_order


# IBKR reports an execution's direction as BOT/SLD, not buy/sell. Strict on
# purpose: anything unrecognised is DROPPED rather than defaulted, because a
# fill entering the ledger pointing the wrong way is a realised P&L with the
# sign reversed - and the promotion gate reads those.
_IB_EXECUTION_SIDE: dict[str, str] = {"BOT": "buy", "SLD": "sell"}


def from_ib_fill(fill: Fill, market: str = "US") -> BrokerFill | None:
    """One IBKR execution as a `BrokerFill`, or None if it cannot be trusted.

    **The identity is `permId`**, matching what `from_ib_trade` writes onto
    `order.order_id` (Task 3). `OMS._order_the_broker_calls` compares those two
    strings, so using `orderId` here would break the match and leave M70/M71
    dormant exactly as they were before Task 3 - silently, which is how they
    were found in the first place.

    **The symbol is translated BACK** into the app's own form. The app tracks
    `BHP.AX` and IBKR answers `BHP`; a fill returned unqualified matches no
    tracked position, so the stop that fired still goes unrecorded (M26, M96).

    **`cumQty`, NOT `shares`.** `BrokerFill.quantity` is the order's cumulative
    filled quantity; `shares` is what THIS execution moved. IBKR returns one
    Fill per execution, so supplying `shares` gave the OMS a per-execution
    number where it subtracts a stored cumulative - and only executions setting
    a new running maximum were ever absorbed. Measured 26 August 2026 on LOV.AX
    order 1216552509: 183 executions, 3,217 shares, of which 374 reached the
    ledger. `cumQty` runs 10, 35, 39 ... 3,217 monotonically across those same
    executions.
    """
    execution = fill.execution
    side = _IB_EXECUTION_SIDE.get(str(execution.side).upper())
    if side is None:
        logger.error(
            "IBKR execution %s has side %r, which is neither BOT nor SLD - dropping it "
            "rather than guessing a direction. This fill will NOT reach the ledger.",
            execution.execId,
            execution.side,
        )
        return None
    return BrokerFill(
        order_id=str(execution.permId),
        symbol=from_ibkr(fill.contract.symbol, market),
        side=side,  # type: ignore[arg-type]
        quantity=float(execution.cumQty),
        price=float(execution.price),
        filled_at=execution.time,
    )


# Order types that ARE a protective stop with a level readable from
# `auxPrice`. TRAIL and TRAIL LIMIT are excluded deliberately rather than by
# omission: a trailing stop's working level is not `auxPrice`, so reading it as
# one would report a stop price the broker is not holding - a wrong number in
# `risk_at_stop`, which is worse than a missing one because it looks answered.
_IB_STOP_TYPES = frozenset({"STP", "STP LMT"})

# Statuses at which an order is genuinely working. `PreSubmitted` counts: a
# bracket's stop child sits there with `whyHeld='child,trigger'` until its
# parent fills, and it IS the protection - a scan that demanded `Submitted`
# would report every bracketed position as unprotected (the M33d shape, where
# an OCO's `held` stop leg read as nothing at all).
_IB_WORKING_STATUSES = frozenset({"PreSubmitted", "Submitted", "PendingSubmit"})


def from_ib_resting_stop(trade: Trade, market: str = "US") -> RestingStopOrder | None:
    """One open IBKR order as a resting protective stop, or None if it is not
    one (Task 4).

    Keyed by `permId` for the same reason `from_ib_fill` is: it is the id the
    rest of the application knows the order by, and M39 re-prices a stop by
    calling `modify_order` with it.
    """
    order = trade.order
    if str(order.orderType) not in _IB_STOP_TYPES:
        return None
    if str(trade.orderStatus.status) not in _IB_WORKING_STATUSES:
        return None
    if not order.auxPrice:
        return None
    return RestingStopOrder(
        symbol=from_ibkr(trade.contract.symbol, market),
        order_id=str(order.permId or order.orderId),
        stop_price=float(order.auxPrice),
        quantity=float(order.totalQuantity),
        why_held=str(trade.orderStatus.whyHeld) or None,
        owner_client_id=int(order.clientId),
    )


def from_ib_open_order(trade: Trade, market: str = "US") -> RestingOrder:
    """One open IBKR order, translated and unjudged (M141, item 23).

    Returns a record for EVERY order, always. Compare `from_ib_resting_stop`,
    which returns None three separate ways - wrong type, non-working status, no
    auxPrice - each of which is correct for the question IT answers and wrong
    for this one.

    `ocaGroup` and `parentPermId` arrive as "" and 0 rather than absent, and the
    grouping in `unjustified_resting_risk` keys on falsiness, so both are
    normalised to None here rather than at each reader.
    """
    order = trade.order
    aux: float | None = None
    if order.auxPrice:
        aux = float(order.auxPrice)
    limit: float | None = None
    lmt_price = getattr(order, "lmtPrice", 0.0)
    if lmt_price:
        limit = float(lmt_price)
    return RestingOrder(
        symbol=from_ibkr(trade.contract.symbol, market),
        order_id=str(order.permId or order.orderId),
        side=str(order.action).lower(),
        order_type=str(order.orderType),
        quantity=float(trade.orderStatus.remaining),
        status=str(trade.orderStatus.status),
        oca_group=str(order.ocaGroup) or None,
        parent_perm_id=int(order.parentPermId) or None,
        owner_client_id=int(order.clientId),
        why_held=str(trade.orderStatus.whyHeld) or None,
        stop_price=aux,
        limit_price=limit,
        # I7, final review: the fallback for `remaining` reading 0.0 only
        # because `orderStatus` has not landed yet. See `RestingOrder.
        # total_quantity`.
        total_quantity=float(order.totalQuantity),
    )


def tighter_stop(
    left: RestingStopOrder, right: RestingStopOrder, selling: bool
) -> RestingStopOrder:
    """Whichever of two stops on one symbol would fire FIRST.

    Two live stops for one symbol is an anomaly - a duplicate re-arm, or a leg
    that outlived its parent - and the answer has one slot, so the choice must
    not depend on the order the broker happened to return them in.

    "Tightest" is not "highest". A SELL stop protecting a long fires on the way
    DOWN, so the higher one goes first; a BUY stop protecting a short fires on
    the way UP, so the LOWER one does. Always taking the maximum would report
    the stop furthest from firing on every short, overstating the risk actually
    being carried.
    """
    if selling:
        return left if left.stop_price >= right.stop_price else right
    return left if left.stop_price <= right.stop_price else right


def from_ib_position(
    position: IBPosition, market: str = "US", market_price: float | None = None
) -> Position:
    """One IBKR position, in the app's own symbol form (M104).

    The fourth and last boundary where an IBKR symbol enters the application,
    and the one that was missed: fills (M97), resting stops (M98) and adopted
    orders (M99) all translate, and this did not.

    It is also the one with the sharpest consequence.
    `OMS.check_reconciliation` builds `{pos.symbol: pos.quantity}` from here and
    unions it with the tracked quantities, so a tracked `BHP.AX` against a
    broker `BHP` produces TWO divergences rather than a match - and a
    reconciliation mismatch TRIPS THE KILL SWITCH. The first fill of a session
    would have halted it, and the halt would have read as a real position
    discrepancy rather than as a spelling difference.

    `verify_position_stops` fails the same way one step earlier: resting stops
    are keyed in the app's form, so every held position would have read as
    unprotected.
    """
    return Position(
        symbol=from_ibkr(position.contract.symbol, market),
        quantity=position.position,
        avg_price=position.avgCost,
        # Item 45. `IB.positions()` carries no price at all - the mark comes
        # from `IB.portfolio()` and is passed in rather than fetched here, so
        # this stays a pure translation. `None` when the caller has no mark,
        # which is a DIFFERENT claim from zero: read as zero, every position
        # would measure as risk-free.
        current_price=market_price,
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
        # No default: a broker that does not report it leaves None, which the
        # exposure metric reads as "unknown" rather than as zero.
        gross_position_value=by_tag.get("GrossPositionValue"),
    )

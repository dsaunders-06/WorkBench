"""What rests at the broker that the book cannot justify (M141, item 23).

Pure, with one deliberate exception (I7, final review): `unjustified_resting_
risk` logs a WARNING when it falls back from `quantity` to `total_quantity` on
an order whose `remaining` has not been populated yet. That is a genuine
anomaly in the DATA this module was handed, not a decision this module made,
and it needs to be on the record wherever it happens rather than only at
whichever caller happened to notice - the same reasoning `verify_position_
stops` and `_resting_stops` already apply to a broker that cannot answer at
all. No broker, no clock, no other I/O - so every other case below is a table
and the hard part is testable without a Gateway.

**Why arithmetic and never identity.** Order identity does not survive a restart:
`_broker_order_ids` and `_orders` are in memory and empty afterwards
(`version.py:501`). The 24 August orphans were themselves inherited across such
a restart, so "did this app place it" answers no for every order that matters.
The only durable question is whether the BOOK justifies what is resting.

**Why OCA groups net rather than sum.** TNE.AX holds 3,051 bracketed at 30.69
and 36.86: a stop for 3,051 AND a target for 3,051, 6,102 shares of resting sell
against a 3,051 long. Only one leg can ever fire. A rule that sums would flag the
first position this system ever placed correctly, on its first run, which is the
most damaging possible false positive.

**Residual, recorded rather than lost.** This holds only while the application's
entries are MARKET orders (outstanding item 44), so nothing of its own ever rests
unfilled. Give this application resting entry orders and a legitimate working
limit buy on a flat symbol reads as an orphan. Revisit here.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, replace

from qat.data.broker.adapter import Position, RestingOrder

logger = logging.getLogger(__name__)

# Share counts are whole numbers at every broker this app talks to, so this is a
# float-comparison guard rather than a real tolerance. Same value and same
# reasoning as `anomaly._QUANTITY_TOLERANCE` and `check_reconciliation`.
_TOLERANCE = 1e-6

# Statuses at which an order can still fill, and therefore still carries risk.
#
# PINNED TO ib_async's own `OrderStatus.ActiveStates`, not derived from it -
# and asserted against it, in both directions, by
# `tests/data/broker/test_working_statuses.py`. Written as literals HERE
# because this module is domain and must not import the broker library; the
# test at the boundary is what keeps the two from drifting apart the way
# `_IB_STATUS_MAP` did, which held four entries and none of IBKR's working
# states, so a transmitted order read as `pending_signoff` and went out four
# times (M139).
#
# It is WIDER than `ib_translate._IB_WORKING_STATUSES`, deliberately and by
# operator decision on 24 August: widening that one moves `_position_stops`,
# which is a sizing input, and it is being shipped separately. The divergence
# is expected.
#
# `ValidationError` is subtracted: ib_async counts it active, but an order that
# failed validation cannot fill and is not resting risk.
WORKING_STATUSES = frozenset(
    {"Submitted", "PreSubmitted", "PendingSubmit", "ApiPending", "ApiUpdate"}
)

# ⚠️ THE COMPLEMENT OF `WORKING_STATUSES` IS NOT ITS NEGATION, AND ASKING
# "is it gone?" WITH `not in WORKING_STATUSES` SENT A SELL OVER TWO RESTING
# LEGS.
#
# `PendingCancel` is in NEITHER set. `PositionCloser` verified its cancels by
# re-reading `open_orders()` and keeping only `WORKING_STATUSES`, so a leg
# sitting in `PendingCancel` was dropped from the read, `survivors` came back
# empty, the "stop dead if a leg survives" step passed, and the market SELL
# went out with both OCA legs STILL RESTING at the broker - a short position,
# reported to the operator as a clean close. And `PendingCancel` is the
# ORDINARY transient of a cancel that IS being honoured, as well as the
# 19 August state of one REJECTED outright (error 10147), so that fired on the
# happy path, on nothing worse than normal cancel latency.
#
# `adapter.py:151` and `ib_adapter.py:638` both already recorded the trap:
# after a cancel IBKR STILL SHOWS the order reporting `PendingCancel`, and
# VISIBLE IS NOT GONE.
#
# So "still working" and "definitely finished" are two questions with two
# answers and a gap between them, and the gap is where the risk lives.
# **Capture** asks the first (what must I cancel, what would I re-place):
# `WORKING_STATUSES`. **Verification** asks the second, and must fail CLOSED -
# an order counts as gone ONLY if it is absent from `open_orders()` entirely or
# reports one of these. Anything else still visible can still fill.
#
# PINNED TO ib_async's own `OrderStatus.DoneStates`, exactly as
# `WORKING_STATUSES` is pinned to `ActiveStates`, and asserted against it in
# both directions by `tests/data/broker/test_working_statuses.py`. Literals
# HERE for the same reason: this module is domain and must not import the
# broker library. The two sets are also asserted DISJOINT there, and their
# union asserted NOT to cover `PendingCancel` - the gap is deliberate and the
# test says so, rather than leaving the next reader to rediscover it.
TERMINAL_STATUSES = frozenset({"Cancelled", "ApiCancelled", "Filled", "Inactive"})


@dataclass(frozen=True, slots=True)
class SymbolOrderDivergence:
    """One symbol and one side carrying more resting quantity than the book
    justifies."""

    symbol: str
    side: str
    resting: float
    justified: float
    excess: float
    flat: bool
    legs: tuple[RestingOrder, ...]

    def describe(self) -> str:
        """Every leg, individually. "Sixteen orphaned legs" was established by
        hand on 24 August and should have been one log line."""
        # ⚠️ THE GROUP KEY IS PRINTED (31 August). `_netted` takes the MAX within
        # an OCA group and the SUM across groups, so two bracket legs sharing a
        # group net to one position's worth. On 31 August a freshly entered
        # JHX.AX bracket reported resting=2194 against justified=1097 - exactly
        # 2x, so its two legs were NOT grouped - while the nine adopted
        # positions with identical shapes read clean, and a read-only probe
        # moments later showed BOTH legs carrying oca=1031062661.
        #
        # The cause is NOT established, and this line is why the next occurrence
        # will not need a hypothesis: it says whether the legs grouped and under
        # what key. Guessing here is how M39 was designed against a feed that
        # did not exist.
        legs = "; ".join(
            f"{leg.order_id} {leg.side} {leg.order_type} {leg.quantity:g}"
            f"@{leg.stop_price or leg.limit_price or 0:g} (client {leg.owner_client_id}"
            f", group {_group_key(leg)})"
            for leg in self.legs
        )
        return (
            f"{self.symbol} {self.side.upper()} resting={self.resting:g} "
            f"justified={self.justified:g} excess={self.excess:g}"
            f"{' FLAT' if self.flat else ''} - {legs}"
        )


def _group_key(order: RestingOrder) -> str:
    """OCA group, else the shared parent, else the order alone.

    IBKR sends "" and 0 rather than absent for the first two; `from_ib_open_order`
    normalises both to None, so falsiness is the right test either way.
    """
    if order.oca_group:
        return f"oca:{order.oca_group}"
    if order.parent_perm_id:
        return f"parent:{order.parent_perm_id}"
    return f"solo:{order.order_id}"


def _netted(orders: Sequence[RestingOrder], effective_quantity: dict[str, float]) -> float:
    """MAX within a one-cancels-all group, SUM across groups.

    `effective_quantity` overrides `order.quantity` for the I7 zero-remaining
    fallback below - keyed by order id rather than mutating the (frozen)
    `RestingOrder`, so the log line at the substitution site stays the one
    place that decision is made.
    """
    groups: dict[str, float] = defaultdict(float)
    for order in orders:
        key = _group_key(order)
        groups[key] = max(groups[key], effective_quantity.get(order.order_id, order.quantity))
    return sum(groups.values())


def unjustified_resting_risk(
    orders: Sequence[RestingOrder], positions: Sequence[Position]
) -> list[SymbolOrderDivergence]:
    """Resting quantity the book cannot account for, per symbol and per side.

    A long justifies SELLs up to its size and no BUYs at all; a short the
    reverse; a flat symbol justifies nothing in either direction. Sides are
    grouped and netted independently, so a still-working BUY parent never nets
    against its own SELL children.

    Both directions are measured. Item 23's language is about short risk because
    that is what happened on 24 August, but unaccounted LONG risk is the same
    defect and costs the same to catch here.
    """
    held = {position.symbol: float(position.quantity) for position in positions}

    by_symbol_side: dict[tuple[str, str], list[RestingOrder]] = defaultdict(list)
    # I7, final review: order id -> the quantity to actually risk-count, when
    # it differs from `order.quantity`. See `RestingOrder.total_quantity` and
    # the module docstring's note on the one exception to "pure".
    effective_quantity: dict[str, float] = {}
    for order in orders:
        if order.status not in WORKING_STATUSES:
            continue
        quantity = order.quantity
        if quantity <= _TOLERANCE:
            if order.total_quantity <= _TOLERANCE:
                # A working order with a genuinely zero total. Dropped exactly
                # as before this fix - there is nothing here to fall back to.
                continue
            # `remaining` reads zero not because the order is empty, but
            # because IBKR had not yet delivered the `orderStatus` callback
            # that populates it when `openOrder` was read - verified in
            # installed ib_async 2.1.0, where `wrapper.openOrder` seeds
            # `OrderStatus(remaining=0.0)` for exactly this case: an order
            # this session has never seen before, which is the orphan case
            # this whole feature exists to catch. Dropping it here would
            # report the book clean on the incident it was built for, so it
            # is counted at `total_quantity` instead - and logged, because a
            # silent substitution of the risk figure is its own kind of lie.
            logger.warning(
                "Resting order %s (%s %s) on %s reports remaining=%g with "
                "totalQuantity=%g - counting it at totalQuantity rather than "
                "dropping it, since orderStatus.remaining had not been "
                "populated yet when this was read.",
                order.order_id,
                order.side,
                order.order_type,
                order.symbol,
                quantity,
                order.total_quantity,
            )
            quantity = order.total_quantity
        effective_quantity[order.order_id] = quantity
        by_symbol_side[(order.symbol, order.side.lower())].append(order)

    divergences: list[SymbolOrderDivergence] = []
    for (symbol, side), legs in sorted(by_symbol_side.items()):
        position = held.get(symbol, 0.0)
        resting = _netted(legs, effective_quantity)
        justified = max(position, 0.0) if side == "sell" else max(-position, 0.0)
        excess = resting - justified
        if excess <= _TOLERANCE:
            continue
        divergences.append(
            SymbolOrderDivergence(
                symbol=symbol,
                side=side,
                resting=resting,
                justified=justified,
                excess=excess,
                flat=abs(position) <= _TOLERANCE,
                legs=tuple(sorted(legs, key=lambda leg: leg.order_id)),
            )
        )
    return divergences


def explain_entries_in_flight(
    divergences: Sequence[SymbolOrderDivergence],
    orders: Sequence[RestingOrder],
    positions: Sequence[Position],
) -> tuple[list[SymbolOrderDivergence], list[SymbolOrderDivergence]]:
    """Split divergences into (unexplained, explained by an entry in flight).

    ⚠️ A BRACKET'S LEGS ARE UNJUSTIFIED WHILE ITS PARENT IS STILL WORKING, BY
    CONSTRUCTION. Measured live on COH.AX, 10 September 2026, at 10:29:05 - the
    same second as sign-off and five minutes before the fill:

        RESTING ORDER ORPHAN: COH.AX BUY  resting=363 justified=-0 excess=363 FLAT
        RESTING ORDER ORPHAN: COH.AX SELL resting=363 justified=0  excess=363 FLAT

    Nothing was wrong. The legs reach the broker before the entry fills, so a
    window where resting quantity exceeds the book is what an entry IS. It cost
    two ERROR lines and a 15-minute quarantine on a normal entry - and an ERROR
    raised by routine activity is how a REAL orphan comes to be scrolled past.

    ⚠️ **THIS IS NOT A WEAKENING OF THE 24 AUGUST RAIL, and the difference is
    measurable AT THE BROKER rather than inferred from app state.** TNE.AX was
    flat with sixteen legs and **no working parent**. An entry in flight has
    one. Nothing here consults `_orders`, `_transmitted` or any belief of this
    application - only what the broker reports as working.

    ⚠️ **AND IT IS BOUNDED BY QUANTITY, NOT BY SYMBOL.** A working buy of Q on a
    flat symbol justifies itself and up to Q of resting sell - the bracket it is
    about to protect. Anything beyond Q is still reported and still quarantines.
    Without that bound a one-share pending entry would exempt a symbol's entire
    sell side, and the 24 August shape could hide behind it.

    ⚠️ **WHAT IS DELIBERATELY GIVEN UP:** a genuinely orphaned WORKING buy on a
    flat symbol is now explained rather than reported. That is the cost of
    letting normal entries through, and it is the smaller risk of the two: a
    working buy that fills creates a LONG, which reconciliation catches on the
    share count. The 24 August failure was orphaned SELLs creating a naked
    short, and that side keeps its cover except up to a matching in-flight buy.

    The exemption ends by itself. When the parent stops working - filled or
    cancelled - it is no longer in `orders`, and the next scan reports normally.
    It cannot become permanent, which is why it needs no timeout.
    """
    held = {position.symbol: float(position.quantity) for position in positions}
    in_flight: dict[str, float] = defaultdict(float)
    for order in orders:
        if order.status not in WORKING_STATUSES or order.side != "buy":
            continue
        if abs(held.get(order.symbol, 0.0)) > _TOLERANCE:
            # Only a FLAT symbol can have its legs explained this way. A held
            # position justifies its own protection through the ordinary path,
            # and a buy against a long is the unaccounted-long case the rail is
            # also there to catch.
            continue
        in_flight[order.symbol] += float(order.quantity)

    unexplained: list[SymbolOrderDivergence] = []
    explained: list[SymbolOrderDivergence] = []
    for divergence in divergences:
        allowance = in_flight.get(divergence.symbol, 0.0)
        if allowance <= _TOLERANCE:
            unexplained.append(divergence)
            continue
        remaining = divergence.excess - allowance
        if remaining <= _TOLERANCE:
            explained.append(divergence)
            continue
        unexplained.append(replace(divergence, excess=remaining))
    return unexplained, explained

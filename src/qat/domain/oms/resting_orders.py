"""What rests at the broker that the book cannot justify (M141, item 23).

Pure. No broker, no clock, no logging, no I/O - so every case below is a table
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

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

from qat.data.broker.adapter import Position, RestingOrder

# Share counts are whole numbers at every broker this app talks to, so this is a
# float-comparison guard rather than a real tolerance. Same value and same
# reasoning as `anomaly._QUANTITY_TOLERANCE` and `check_reconciliation`.
_TOLERANCE = 1e-6

# Statuses at which an order can still fill, and therefore still carries risk.
#
# DERIVED from ib_async's own `OrderStatus.ActiveStates` rather than restated,
# and asserted against it by `tests/data/broker/test_working_statuses.py`. A
# hand-maintained status set is exactly what caused M139: `_IB_STATUS_MAP` held
# four entries and none of IBKR's working states, so a transmitted order read as
# `pending_signoff` and went out four times.
#
# Written as literals HERE because this module is domain and must not import the
# broker library; the test at the boundary is what keeps the two in step. It is
# WIDER than `ib_translate._IB_WORKING_STATUSES`, deliberately and by operator
# decision on 24 August: widening that one moves `_position_stops`, which is a
# sizing input, and it is being shipped separately. The divergence is expected.
#
# `ValidationError` is subtracted: ib_async counts it active, but an order that
# failed validation cannot fill and is not resting risk.
WORKING_STATUSES = frozenset(
    {"Submitted", "PreSubmitted", "PendingSubmit", "ApiPending", "ApiUpdate"}
)


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
        legs = "; ".join(
            f"{leg.order_id} {leg.side} {leg.order_type} {leg.quantity:g}"
            f"@{leg.stop_price or leg.limit_price or 0:g} (client {leg.owner_client_id})"
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


def _netted(orders: Sequence[RestingOrder]) -> float:
    """MAX within a one-cancels-all group, SUM across groups."""
    groups: dict[str, float] = defaultdict(float)
    for order in orders:
        key = _group_key(order)
        groups[key] = max(groups[key], order.quantity)
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
    for order in orders:
        if order.status not in WORKING_STATUSES:
            continue
        if order.quantity <= _TOLERANCE:
            continue
        by_symbol_side[(order.symbol, order.side.lower())].append(order)

    divergences: list[SymbolOrderDivergence] = []
    for (symbol, side), legs in sorted(by_symbol_side.items()):
        position = held.get(symbol, 0.0)
        resting = _netted(legs)
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

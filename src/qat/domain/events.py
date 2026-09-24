"""Typed events published on the in-process EventBus.

All inter-engine communication happens exclusively through these events
(spec §C) - engines never call each other directly. Every event carries a
UTC timestamp so downstream consumers can enforce point-in-time discipline.

Most event types below are declared now but not yet published by anything -
they exist so the domain vocabulary is fixed early; later milestones wire
producers and consumers for each.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any, Literal


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True, kw_only=True)
class Event:
    ts: datetime = field(default_factory=_utcnow)


@dataclass(frozen=True, slots=True, kw_only=True)
class MarketDataEvent(Event):
    symbol: str
    price: float
    volume: float


@dataclass(frozen=True, slots=True, kw_only=True)
class FeatureEvent(Event):
    symbol: str
    features: dict[str, float]
    as_of: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class MacroEvent(Event):
    series: str
    value: float


@dataclass(frozen=True, slots=True, kw_only=True)
class RegimeEvent(Event):
    label: str
    probs: dict[str, float]
    exposure_scalar: float


@dataclass(frozen=True, slots=True, kw_only=True)
class SignalEvent(Event):
    symbol: str
    side: Literal["buy", "sell"]
    conviction: float
    strategy: str
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True, kw_only=True)
class OrderPendingSignoffEvent(Event):
    """An order has been risk-approved and now awaits a decision.

    In "recommend" mode the decision is a human's, in the Order Blotter. In
    "auto" mode AutonomousExecutor subscribes to this and may make it. Both
    paths still go through OMS.sign_off - this event announces that an order is
    waiting, it does not bypass anything.
    """

    order_id: str
    symbol: str
    side: Literal["buy", "sell"]
    quantity: float
    strategy: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class OrderFilledEvent(Event):
    """An order actually filled at the broker.

    Distinct from OrderPendingSignoffEvent: that one announces an intention,
    this one records a fact. Performance measurement can only ever be built on
    the second - a decision journal tells you what the system chose, never
    whether it worked.
    """

    order_id: str
    symbol: str
    side: Literal["buy", "sell"]
    quantity: float
    price: float
    # Cumulative average for this order; quantity/price above describe only
    # the newly confirmed execution delta used by the ledger.
    order_average_price: float | None = None
    # Stable identity for one cumulative broker-fill observation. Consumers
    # persist this with their own state so a crash can replay the event without
    # applying a successful sibling write twice.
    fill_id: str | None = None
    cumulative_quantity: float | None = None
    strategy: str | None = None
    stop_price: float | None = None
    # Carried for the same reason stop_price is (M33): the bracket legs die
    # overnight and re-arming needs both levels, not just the protective one.
    take_profit_price: float | None = None
    operator: str = ""
    # Diagnostics, not mechanism (M37). Nothing decides on these; they exist so
    # that three months of closed trades can answer WHY a result happened and
    # not only what it was.
    reference_price: float | None = None
    """The price the order was sized against, so realised slippage is
    measurable against the assumption rather than guessed at."""
    earnings_at_entry: date | None = None
    """The next scheduled announcement as known when the order was sized (M41).

    Carried because it cannot be recovered later: by the time the trade closes
    the calendar has rolled to the following quarter, so "was this held through
    a print" stops being answerable the moment the position is opened.
    """
    exit_reason: str | None = None
    """How a position ended: stop, target, time_stop, signal, delever. Set by
    whichever component actually caused the exit, because after the fact the
    price alone cannot always distinguish them."""
    price_is_fill: bool = False
    """Whether `price` is what the broker actually charged, rather than the
    price the order was sized against (M175). `_announce_fill` publishes at
    "transmitted" as well as "filled", and at transmit only the reference
    exists. The entry record stamps which one it holds, so a restart never
    replaces an observed fill with a derived one."""


@dataclass(frozen=True, slots=True, kw_only=True)
class EntryPriceCorrectedEvent(Event):
    """What an order THIS APP transmitted actually filled at (M70).

    Deliberately not a second OrderFilledEvent. That one is a fact about a
    quantity as much as a price, and both its subscribers act on the quantity:
    the ledger opens a lot per buy, and sign_off has already counted the fill.
    Re-announcing would double the position on the Performance tab and
    re-create the M46 discrepancy that halted the 4 August session. This says
    one thing only - the price was wrong, here is the right one.

    Published when the broker reports a fill for an order the app sent at a
    price that differs from the one announced at transmit. `_announce_fill`
    fires at "transmitted" as well as "filled", and at transmit there is no
    fill price, so what it published was the price the order was SIZED
    against.
    """

    order_id: str
    symbol: str
    price: float
    """What the broker charged. `filled_avg_price`, so a partial that later
    completes reports the cumulative average and corrects again."""
    announced_price: float
    """What was published at transmit, carried so the log can state the
    difference rather than only the destination."""


@dataclass(frozen=True, slots=True, kw_only=True)
class ExitPriceCorrectedEvent(Event):
    """What an order THIS APP transmitted to CLOSE a position actually filled
    at (M71).

    The sell-side twin of EntryPriceCorrectedEvent, published by the same
    method for the same reason: `_announce_fill` fires at "transmitted" as
    well as "filled", and at transmit there is no fill price, so what went out
    for a sell was the price the order was SIZED against - and
    `TradeLedger._close_against_lots` built the ClosedTrade from it.

    A buy correction rebases an OPEN LOT, still in memory. A sell CLOSES the
    position, so by the time the true fill arrives the ClosedTrade is already
    written to closed_trades.csv - there is no next-startup healing path for a
    trade that is already closed. The ledger amends the row on this event
    rather than leaving a wrong exit price, P&L, cost and R-multiple on
    permanent record.
    """

    order_id: str
    symbol: str
    price: float
    """What the broker charged. `filled_avg_price`, so a partial that later
    completes reports the cumulative average and corrects again."""
    announced_price: float
    """What was published at transmit, carried so the log can state the
    difference rather than only the destination."""
    quantity: float
    """The order's own quantity - what `_close_against_lots` costed the exit
    against (`OrderFilledEvent.quantity`), not the broker's fill-report
    quantity, which can be a partial or a cumulative figure. Carried so the
    amendment recomputes `exit_cost` on the SAME basis the original write
    used: `_close_against_lots` bases the per-transaction commission floor on
    the full sell, then apportions across whatever lots it closed. Basing the
    amendment on the matched rows' own quantity total instead is only equal
    when nothing was left unmatched - a sell that partly closed an untracked
    position (M71 review)."""


@dataclass(frozen=True, slots=True, kw_only=True)
class DataStaleEvent(Event):
    """ONE symbol's quote is too old to size a trade against (M28a).

    Measured on the trade's own timestamp, so it answers "how old is the last
    print" - a thin ticker that has not traded for an hour, or a halted one.
    That is a reason to stop trading *that symbol*, and never a reason to halt
    the account: until M28a this tripped the kill-switch, and every trip it
    ever produced was a false positive. With a 60s poll against a 60s
    threshold, a trade arriving 40s old is already past the line before the
    next poll - the rail was measuring arithmetic, not risk.

    Whether the feed itself is alive is a different question, measured on
    receive time and reported by MarketDataFeedEvent.
    """

    symbol: str
    seconds_since_update: float
    # False when a symbol that was stale has printed again, so a consumer can
    # let it trade rather than excluding it for the rest of the session.
    stale: bool = True


@dataclass(frozen=True, slots=True, kw_only=True)
class KillSwitchEvent(Event):
    reason: str
    triggered_by: str


@dataclass(frozen=True, slots=True, kw_only=True)
class BrokerOrderIdResolvedEvent(Event):
    """A broker-native order id was resolved for an order this app placed,
    at some point after transmit (item 56/M99).

    IBKR's `permId` is 0 when `placeOrder` returns and TWS has not yet
    acknowledged, so the id `_broker_order_ids` learns at transmit time can
    be the app's own UUID rather than the id an execution later arrives
    under. `IBAdapter._adopt_from_broker` resolves the broker-native id
    moments later anyway - modify and cancel need it - and publishes it here
    so the OMS's own-fill check learns it at the same moment, rather than
    only on the next restart's reconciliation sweep.
    """

    order_id: str
    app_order_id: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class OrderRejectedEvent(Event):
    """A broker rejection proved an order will never fill (3 September 2026).

    Sign-off books the ORDERED size optimistically, before anything has
    executed, and lets broker reconciliation catch any divergence later -
    right for a transmit that stays live. But `IBAdapter._on_ib_error` can
    also learn, from IBKR itself, that an order is already dead: Error 383
    (a precautionary size limit) staged a 790-share BHP.AX order that was
    never transmitted to the exchange, sign-off had booked all 790, and
    nothing reversed it. `tracked=790 broker=0` tripped the kill switch every
    five minutes for two hours, and the phantom counted toward the position
    cap, refusing a real entry against a book of nine.

    Published from `_on_ib_error` for both `ErrorAction.REJECT` and
    `ErrorAction.HALT` - never `WARN`, which means ib_async's own wrapper.py
    is keeping the order LIVE at the broker, and reversing anything would be
    wrong in the other direction. Same precedent as `KillSwitchEvent`: the
    adapter publishes and must not import the OMS, which subscribes instead.
    """

    order_id: str
    symbol: str
    side: str
    """⚠️ "buy" or "sell". REQUIRED, because `_filled_quantities` is SIGNED -
    sign-off books `-quantity` for a sell (oms.py, `signed_qty`) while
    `Order.quantity` below is unsigned. Without this the reversal subtracts
    from a short and DOUBLES it, which is the phantom this event exists to
    remove, in the other direction. Found by review on 4 September; every
    test until then had used a buy."""
    booked_quantity: float
    """What sign-off booked at transmit time: the ORDERED size, not what
    actually executed. Unsigned - `side` carries the direction."""
    executed_quantity: float | None
    """`Order.filled_quantity` at the moment of rejection. `None` means this
    adapter does not report executed quantity - a different claim from zero -
    so the OMS must not reverse on a guess: leaving the booking in place is
    what let reconciliation catch 3 September in four minutes."""
    reason: str


@dataclass(frozen=True, slots=True, kw_only=True)
class MarketDataFeedEvent(Event):
    """The feed as a whole is up or down (spec M26).

    DataStaleEvent is per-symbol and only fires for a symbol that has ticked
    at least once, so a feed that never delivered anything raised nothing at
    all: the app ran a full session on no data while the banner read
    AUTO-TRADE ACTIVE. This event is about the feed rather than a symbol, and
    so it can be raised on exactly that case.
    """

    healthy: bool
    reason: str
    seconds_since_last_tick: float | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class RegimeHealthEvent(Event):
    """The regime classifier is producing labels, or it is not (M27a).

    StrategyEngine falls open to its default regime when no RegimeEvent has
    arrived, which keeps the application trading through a dead classifier -
    defensible for availability, and invisible until now. On 28 July the HMM
    crashed on every fit and the only trace was hmmlearn's traceback in the
    bus; the screen said nothing at all.

    Unhealthy covers both "it has failed" and "it has never yet succeeded",
    because the consequence is identical: the regime gate is not gating, and
    every strategy is being permitted or refused on a default rather than on a
    reading of the market.
    """

    healthy: bool
    reason: str

"""Broker-agnostic interface. IBAdapter (M7) and MockBroker both implement this."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Literal, Protocol

OrderStatus = Literal["new", "pending_signoff", "transmitted", "filled", "cancelled", "rejected"]


@dataclass(slots=True)
class Order:
    symbol: str
    side: Literal["buy", "sell"]
    quantity: float
    order_id: str
    status: OrderStatus = "new"
    limit_price: float | None = None
    filled_price: float | None = None
    # The price this order was sized against at submission. Kept so the
    # sign-off cash check has a known cost even when the broker cannot supply a
    # live quote - without it, an adapter that does not serve market data
    # leaves the check with no price at all.
    reference_price: float | None = None
    # Which strategy produced this order, when one did. Carried so the
    # autonomy gate can be granted per-strategy rather than all-or-nothing, and
    # so the decision journal can attribute an outcome to the strategy that
    # caused it. None for manual and exit orders, which belong to no strategy.
    strategy: str | None = None
    # Protective exits attached to the entry, submitted to the broker as one
    # bracket (M14). These live AT THE BROKER, which is the entire point: a
    # stop held only in this process disappears the moment the process does,
    # leaving the position naked. An unattended system that can die overnight
    # needs its protection to outlive it.
    stop_price: float | None = None
    take_profit_price: float | None = None
    # "stop" means the order IS a resting protective stop, not a market order
    # carrying one (M31d). Without the distinction a sell with a stop_price is
    # indistinguishable from a market sell, and submitting it as one would
    # liquidate the position it was meant to protect.
    order_type: Literal["market", "stop"] = "market"
    # The next scheduled earnings announcement as it was known when this order
    # was sized (M41). Diagnostics, never mechanism - the event-risk rail works
    # off a distance and has already done its work by the time this is carried.
    # It rides here so that a closed trade can answer whether it was held
    # through a print, which is not reconstructable afterwards: by the time the
    # trade closes, the calendar has moved on to the next quarter.
    earnings_date: date | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def is_bracket(self) -> bool:
        """Protective legs attached to an entry. A standalone stop is not one:
        it has no entry to attach to, and asking the broker to bracket it is
        how you get an order rejected."""
        if self.order_type == "stop":
            return False
        return self.stop_price is not None or self.take_profit_price is not None

    @property
    def is_protective_stop(self) -> bool:
        return self.order_type == "stop" and self.side == "sell"


@dataclass(frozen=True, slots=True)
class BrokerFill:
    """An execution the BROKER performed, which this app did not transmit (M34).

    A protective stop or target filling is the normal way a position closes
    here, and it happens entirely at the broker: no order leaves this process,
    so nothing publishes OrderFilledEvent and nothing tells the trade ledger a
    trade closed. Two things follow, and both bite.

    Reconciliation compares tracked quantity against the broker's and trips the
    kill-switch on any divergence, so a stop doing exactly its job halts the
    session. And every closed trade this system will ever produce comes from a
    stop, a target, or the time stop - two of the three are broker-side - so
    the ledger stays empty and the promotion gate never accumulates the
    evidence the whole plan rests on.
    """

    order_id: str
    symbol: str
    side: Literal["buy", "sell"]
    quantity: float
    price: float
    filled_at: datetime


@dataclass(slots=True)
class Position:
    symbol: str
    quantity: float
    avg_price: float


@dataclass(slots=True)
class AccountSummary:
    net_liquidation: float
    cash: float
    buying_power: float


@dataclass(frozen=True, slots=True)
class AccountBalances:
    """The broker's own balance sheet, for display (spec M21).

    Deliberately separate from AccountSummary rather than an extension of it.
    AccountSummary is load-bearing - the no-leverage cash rule and the risk
    engine size against it - and widening it would invite a display concern
    into a safety-critical structure. This one is read by screens only.

    Every field is optional because a broker can genuinely not know: an Alpaca
    paper account returns nothing for day-trade count or the PDT flag, and an
    unreported count is not the same fact as a count of zero. None renders as
    a dash, never as 0.
    """

    # What the money is
    equity: float | None = None
    last_equity: float | None = None  # previous close, for the day's P&L
    cash: float | None = None
    long_market_value: float | None = None
    short_market_value: float | None = None

    # What can be spent, by the broker's rules
    buying_power: float | None = None
    regt_buying_power: float | None = None
    daytrading_buying_power: float | None = None
    non_marginable_buying_power: float | None = None
    multiplier: float | None = None

    # What is pledged
    initial_margin: float | None = None
    maintenance_margin: float | None = None
    sma: float | None = None
    accrued_fees: float | None = None

    # Standing of the account
    status: str | None = None
    currency: str | None = None
    daytrade_count: int | None = None
    pattern_day_trader: bool | None = None
    trading_blocked: bool | None = None
    account_blocked: bool | None = None
    shorting_enabled: bool | None = None

    @property
    def day_pnl(self) -> float | None:
        """The broker's own definition: equity against previous-close equity.

        Taken from the broker rather than recomputed so this figure and the
        broker's own page cannot disagree - two different numbers for "today"
        is worse than one number with a caveat.
        """
        if self.equity is None or self.last_equity is None:
            return None
        return self.equity - self.last_equity

    @property
    def day_pnl_pct(self) -> float | None:
        change = self.day_pnl
        if change is None or not self.last_equity:
            return None
        return change / self.last_equity

    def spendable_cash(self, min_cash_reserve: float) -> float | None:
        """What THIS application will let a buy spend.

        Shown beside buying power because the two differ by a factor of four on
        a margin account, and that gap is the most confusing thing about
        running this app next to the broker's own screen. Buying power is what
        the broker would allow; this is what the no-leverage rule permits.
        """
        if self.cash is None:
            return None
        return max(0.0, self.cash - min_cash_reserve)


def balances_from_summary(summary: AccountSummary) -> AccountBalances:
    """The three figures every broker reports, for adapters with no richer view.

    Everything else stays None, which the panel renders as a dash - an honest
    "this broker does not report it" rather than a fabricated zero.
    """
    return AccountBalances(
        equity=summary.net_liquidation,
        cash=summary.cash,
        buying_power=summary.buying_power,
    )


class BrokerAdapter(Protocol):
    async def get_market_data(self, symbol: str) -> dict[str, float]: ...

    async def get_historical(self, symbol: str, bars: int) -> list[dict[str, float]]: ...

    async def place_order(self, order: Order) -> Order: ...

    async def modify_order(self, order_id: str, **changes: object) -> Order: ...

    async def cancel_order(self, order_id: str) -> Order: ...

    async def positions(self) -> list[Position]: ...

    async def account(self) -> AccountSummary: ...

    # Optional (M21): richer balance data for display. Adapters that cannot
    # answer more than the three core figures need not implement it - callers
    # fall back to balances_from_summary().
    async def balances(self) -> AccountBalances: ...

    # Optional (M34): executions the broker performed on this app's behalf -
    # a resting stop or target filling. Adapters that cannot answer return an
    # empty list, which leaves the previous behaviour exactly as it was.
    #
    # `symbols` bounds the question to what the caller is tracking (M48), and
    # `since` is a FILL-time window - not a "submitted since" one, which is
    # what Alpaca's own `after=` parameter turns out to mean.
    async def recent_fills(
        self, since: datetime, symbols: list[str] | None = None
    ) -> list[BrokerFill]: ...

    # Optional (M31b): protective orders actually resting at the broker, so the
    # app can verify its own belief rather than assume it. Adapters that cannot
    # answer return an empty tuple, which reads as "unknown" rather than
    # "none" - see OMS.verify_position_stops.
    async def resting_stops(self) -> dict[str, float]: ...

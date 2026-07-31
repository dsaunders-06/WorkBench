"""Realised trade outcomes (spec M16).

The decision journal records what the system *decided*. This records what
actually happened. They are different things and only the second can answer
"is this strategy any good" - a journal full of confident entries tells you
nothing about whether they made money.

Fills are matched FIFO per symbol into closed round-trips. FIFO rather than
average-cost because it preserves individual trade identity: average-cost
collapses five entries and five exits into one blended number, which destroys
exactly the per-trade distribution (win rate, R-multiple spread) that the
promotion gate needs to judge a strategy.

Each closed trade carries its **R-multiple** - profit divided by the risk
originally taken to the stop - as well as raw P&L. R is the comparable unit:
a $500 win on a trade risking $100 and a $500 win on one risking $2,000 are
not the same result, and only R says so.

**Costs are part of the trade, not an adjustment applied later (M28).** Every
trade records what it cost to open and to close, and reports gross and net
separately. Until M28 `pnl` was `(exit - entry) x quantity` with no fee term,
so expectancy, average R, profit factor and the promotion gate that consumes
them were all computed on money that was never earned. A round trip costs at
least $12 at IBKR's minimums, which is trivial on a large position and decisive
on a small one.

There is deliberately no attribute called `pnl` any more. Redefining it to mean
net would have silently changed the meaning of every existing call site, which
is the same failure as a placeholder wearing the name of the real thing - so
callers must now say `gross_pnl` or `net_pnl` and mean it.
"""

from __future__ import annotations

import csv
import logging
import threading
from collections import defaultdict, deque
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from qat.config import Settings
from qat.domain.backtester.costs import CostModel
from qat.domain.bus import EventBus
from qat.domain.events import OrderFilledEvent

logger = logging.getLogger(__name__)

TRADES_FILENAME = "closed_trades.csv"

_FIELDS = (
    "opened_at",
    "closed_at",
    "symbol",
    "strategy",
    "quantity",
    "entry_price",
    "exit_price",
    "stop_price",
    "gross_pnl",
    "entry_cost",
    "exit_cost",
    "net_pnl",
    "pnl_pct",
    "r_multiple",
    "gross_r_multiple",
    "risk_per_share",
)


def _share_of(total_cost: float, matched: float, whole: float) -> float:
    """The part of a per-transaction cost belonging to `matched` of `whole`."""
    if whole <= 0:
        return 0.0
    return total_cost * (matched / whole)


@dataclass(frozen=True, slots=True)
class OpenLot:
    symbol: str
    quantity: float
    price: float
    stop_price: float | None
    strategy: str | None
    opened_at: datetime
    # Cost of the fill that opened this lot, for the lot's WHOLE quantity.
    # Held whole and apportioned at close, because the broker's per-order
    # commission floor is charged once per transaction: closing a position in
    # three pieces must not pay three minimum commissions on the entry.
    entry_cost: float = 0.0


@dataclass(frozen=True, slots=True)
class ClosedTrade:
    symbol: str
    strategy: str | None
    quantity: float
    entry_price: float
    exit_price: float
    stop_price: float | None
    opened_at: datetime
    closed_at: datetime
    # Already apportioned to this trade's quantity - see OpenLot.entry_cost.
    entry_cost: float = 0.0
    exit_cost: float = 0.0

    @property
    def gross_pnl(self) -> float:
        """Price movement alone, before it cost anything to capture."""
        return (self.exit_price - self.entry_price) * self.quantity

    @property
    def costs(self) -> float:
        return self.entry_cost + self.exit_cost

    @property
    def net_pnl(self) -> float:
        """What the account actually kept. The number every metric uses."""
        return self.gross_pnl - self.costs

    @property
    def pnl_pct(self) -> float:
        """Net return on the capital committed, not the raw price change.

        Costs are charged against the position's own notional so this stays
        comparable across trade sizes - a $12 round trip is 0.06% of a $20,000
        position and 1.2% of a $1,000 one.
        """
        if self.entry_price <= 0 or self.quantity <= 0:
            return 0.0
        return self.net_pnl / (self.entry_price * self.quantity)

    @property
    def risk_per_share(self) -> float | None:
        """Distance from entry to the protective stop. None when no stop was
        recorded - the trade is still real, it just has no R."""
        if self.stop_price is None or self.stop_price >= self.entry_price:
            return None
        return self.entry_price - self.stop_price

    @property
    def r_multiple(self) -> float | None:
        """Net profit in units of the risk originally taken.

        Net, because R is the unit the promotion gate judges a strategy on and
        a gross R says the strategy earned something the account never saw. The
        denominator stays the risk as it was defined at entry - the stop
        distance - since that is what was actually put at hazard.

        None rather than 0.0 when no stop is known: a trade with unmeasurable R
        must be excluded from an average, not counted as a breakeven one, or
        every unstopped trade would silently drag the mean toward zero.
        """
        risk = self.risk_per_share
        if risk is None or risk <= 0 or self.quantity <= 0:
            return None
        return self.net_pnl / (risk * self.quantity)

    @property
    def gross_r_multiple(self) -> float | None:
        """R before costs - retained so the drag is visible, never for judging."""
        risk = self.risk_per_share
        if risk is None or risk <= 0:
            return None
        return (self.exit_price - self.entry_price) / risk

    @property
    def is_win(self) -> bool:
        """Net. A trade that gained $5 and cost $12 is a loss, and a win rate
        that counts it otherwise is measuring the market rather than the
        account."""
        return self.net_pnl > 0

    def as_row(self) -> dict[str, object]:
        return {
            "opened_at": self.opened_at.isoformat(timespec="seconds"),
            "closed_at": self.closed_at.isoformat(timespec="seconds"),
            "symbol": self.symbol,
            "strategy": self.strategy or "",
            "quantity": round(self.quantity, 6),
            "entry_price": round(self.entry_price, 4),
            "exit_price": round(self.exit_price, 4),
            "stop_price": round(self.stop_price, 4) if self.stop_price is not None else "",
            "gross_pnl": round(self.gross_pnl, 2),
            "entry_cost": round(self.entry_cost, 2),
            "exit_cost": round(self.exit_cost, 2),
            "net_pnl": round(self.net_pnl, 2),
            "pnl_pct": round(self.pnl_pct, 6),
            "r_multiple": round(self.r_multiple, 4) if self.r_multiple is not None else "",
            "gross_r_multiple": (
                round(self.gross_r_multiple, 4) if self.gross_r_multiple is not None else ""
            ),
            "risk_per_share": (
                round(self.risk_per_share, 4) if self.risk_per_share is not None else ""
            ),
        }


class TradeLedger:
    """Engine (per domain.orchestrator.Engine protocol)."""

    name = "trade-ledger"

    def __init__(
        self,
        bus: EventBus,
        data_dir: str | Path,
        filename: str = TRADES_FILENAME,
        settings: Settings | None = None,
    ) -> None:
        self.bus = bus
        self.path = Path(data_dir) / filename
        self.settings = settings or Settings()
        # Modelled, not billed. A paper broker charges nothing, so measuring
        # the paper account's own fees would report zero and promote a strategy
        # onto a broker where the same trades lose money (M27's reasoning, now
        # applied to the measurement as well as to the rail). Real per-fill
        # commissions from a live broker are not read back yet.
        self._costs = (
            CostModel.from_settings(self.settings)
            if self.settings.apply_costs_in_paper or self.settings.is_live
            else None
        )
        self._open_lots: dict[str, deque[OpenLot]] = defaultdict(deque)
        self._closed: list[ClosedTrade] = []
        self._lock = threading.Lock()

    async def start(self) -> None:
        self.bus.subscribe(OrderFilledEvent, self._on_fill)

    async def stop(self) -> None:
        self.bus.unsubscribe(OrderFilledEvent, self._on_fill)

    async def _on_fill(self, event: OrderFilledEvent) -> None:
        if event.quantity <= 0 or event.price <= 0:
            return
        if event.side == "buy":
            self._open_lots[event.symbol].append(
                OpenLot(
                    symbol=event.symbol,
                    quantity=event.quantity,
                    price=event.price,
                    stop_price=event.stop_price,
                    strategy=event.strategy,
                    opened_at=event.ts,
                    entry_cost=self._fill_cost(event.quantity, event.price),
                )
            )
            return
        self._close_against_lots(event)

    def _fill_cost(self, quantity: float, price: float) -> float:
        """What one fill costs, for its whole quantity.

        Charged per transaction, which is why it is computed here rather than
        per closed trade: the commission floor applies once to the order, and
        a position closed in three pieces pays one floor, not three.
        """
        if self._costs is None:
            return 0.0
        return self._costs.apply(abs(quantity) * price)

    def _close_against_lots(self, event: OrderFilledEvent) -> None:
        remaining = event.quantity
        lots = self._open_lots[event.symbol]
        # The exit's cost belongs to the whole sell, so it is apportioned
        # across whatever lots this sell happens to close - by quantity, the
        # same basis the entry cost is split on.
        exit_cost_total = self._fill_cost(event.quantity, event.price)
        exit_quantity = event.quantity

        while remaining > 1e-9 and lots:
            lot = lots[0]
            matched = min(remaining, lot.quantity)
            trade = ClosedTrade(
                symbol=event.symbol,
                # The ENTRY's strategy, not the exit's. A stop-loss sweep or a
                # delever trim closes a position it did not open, and attributing
                # the result to whatever happened to close it would credit the
                # wrong strategy with the outcome.
                strategy=lot.strategy,
                quantity=matched,
                entry_price=lot.price,
                exit_price=event.price,
                stop_price=lot.stop_price,
                opened_at=lot.opened_at,
                closed_at=event.ts,
                entry_cost=_share_of(lot.entry_cost, matched, lot.quantity),
                exit_cost=_share_of(exit_cost_total, matched, exit_quantity),
            )
            self._record(trade)

            remaining -= matched
            if matched >= lot.quantity - 1e-9:
                lots.popleft()
            else:
                lots[0] = OpenLot(
                    symbol=lot.symbol,
                    quantity=lot.quantity - matched,
                    price=lot.price,
                    stop_price=lot.stop_price,
                    strategy=lot.strategy,
                    opened_at=lot.opened_at,
                    # The remainder keeps the cost still owed on it, so a lot
                    # closed in pieces charges its entry commission exactly
                    # once across all of them.
                    entry_cost=lot.entry_cost - _share_of(lot.entry_cost, matched, lot.quantity),
                )

        if remaining > 1e-9:
            # A sell with no matching entry. Real when a position was adopted
            # from a previous session: this app never saw the buy, so it cannot
            # compute a P&L for it and must not invent one.
            logger.info(
                "Sell of %g %s exceeded tracked entries by %g - unmatched portion "
                "ignored (likely an adopted position this session never opened)",
                event.quantity,
                event.symbol,
                remaining,
            )

    def _record(self, trade: ClosedTrade) -> None:
        self._closed.append(trade)
        try:
            with self._lock:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                is_new = not self.path.exists() or self.path.stat().st_size == 0
                with self.path.open("a", newline="", encoding="utf-8") as handle:
                    writer = csv.DictWriter(handle, fieldnames=_FIELDS, extrasaction="ignore")
                    if is_new:
                        writer.writeheader()
                    writer.writerow(trade.as_row())
        except OSError:
            logger.exception("Could not append the closed trade for %s", trade.symbol)

    # --- reads ---------------------------------------------------------------

    def closed_trades(self, strategy: str | None = None) -> list[ClosedTrade]:
        if strategy is None:
            return list(self._closed)
        return [trade for trade in self._closed if trade.strategy == strategy]

    def open_lots(self, symbol: str | None = None) -> list[OpenLot]:
        if symbol is not None:
            return list(self._open_lots.get(symbol, ()))
        return [lot for lots in self._open_lots.values() for lot in lots]

    def strategies(self) -> list[str]:
        return sorted({trade.strategy for trade in self._closed if trade.strategy})


@dataclass(frozen=True, slots=True)
class EquityPoint:
    ts: datetime
    equity: float
    cash: float

    def as_row(self) -> dict[str, object]:
        return {
            "ts": self.ts.isoformat(timespec="seconds"),
            "equity": round(self.equity, 2),
            "cash": round(self.cash, 2),
        }


class EquityCurve:
    """Append-only equity samples.

    Kept separate from the closed-trade ledger because they answer different
    questions: trades measure decision quality, the curve measures the account.
    A strategy can have a good win rate while the account bleeds, and only
    having both lets you see it.
    """

    FILENAME = "equity_curve.csv"
    _FIELDS = ("ts", "equity", "cash")

    def __init__(self, data_dir: str | Path, filename: str | None = None) -> None:
        self.path = Path(data_dir) / (filename or self.FILENAME)
        self._points: list[EquityPoint] = self._load()
        self._lock = threading.Lock()

    def _load(self) -> list[EquityPoint]:
        """Read back what earlier runs recorded.

        The curve was written to disk and never read, so points() only ever
        held the current process's samples. A restart mid-session therefore
        silently rewrote the day: the first live session restarted after the
        account went flat and the daily report announced "equity 100,660.56 ->
        100,660.56, +0.00%, average exposure 0.0%" for a day that actually ran
        100,462.97 -> 100,660.56 at 17% average exposure. Not a arithmetic
        error - the report simply could not see the morning.

        A missing or damaged file is not fatal. Losing history is bad; failing
        to start because history is unreadable is worse.
        """
        if not self.path.exists():
            return []
        points: list[EquityPoint] = []
        try:
            with self.path.open(newline="", encoding="utf-8") as handle:
                for row in csv.DictReader(handle):
                    try:
                        points.append(
                            EquityPoint(
                                ts=datetime.fromisoformat(row["ts"]),
                                equity=float(row["equity"]),
                                cash=float(row["cash"]),
                            )
                        )
                    except (KeyError, TypeError, ValueError):
                        continue  # one unreadable row must not discard the rest
        except OSError:
            logger.exception("Could not read the equity history at %s", self.path)
            return []
        return points

    def record(self, equity: float, cash: float, ts: datetime | None = None) -> EquityPoint:
        point = EquityPoint(ts=ts or datetime.now(UTC), equity=equity, cash=cash)
        self._points.append(point)
        try:
            with self._lock:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                is_new = not self.path.exists() or self.path.stat().st_size == 0
                with self.path.open("a", newline="", encoding="utf-8") as handle:
                    writer = csv.DictWriter(handle, fieldnames=self._FIELDS, extrasaction="ignore")
                    if is_new:
                        writer.writeheader()
                    writer.writerow(point.as_row())
        except OSError:
            logger.exception("Could not append an equity sample to %s", self.path)
        return point

    def points(self) -> list[EquityPoint]:
        return list(self._points)


__all__ = [
    "ClosedTrade",
    "EquityCurve",
    "EquityPoint",
    "OpenLot",
    "TradeLedger",
    "asdict",
    "field",
]

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
import shutil
import threading
from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, date, datetime
from pathlib import Path

from qat.config import Settings
from qat.domain.backtester.costs import CostModel
from qat.domain.bus import EventBus
from qat.domain.events import (
    EntryPriceCorrectedEvent,
    ExitPriceCorrectedEvent,
    MarketDataEvent,
    OrderFilledEvent,
    RegimeEvent,
)

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
    "regime_at_entry",
    "regime_probability",
    "exposure_scalar",
    "exit_reason",
    "holding_days",
    "entry_slippage",
    "mae_r",
    "mfe_r",
    "risk_per_share",
    # The three raw inputs behind entry_slippage, mae_r and mfe_r (M49). Only
    # the derived figures were written, so a trade read back from this file
    # could never recompute them and the M37 diagnostics would degrade to blank
    # on the first restart. Added while the file does not yet exist, so there
    # is nothing to migrate.
    "reference_price",
    "worst_price",
    "best_price",
    # The announcement date known at entry, and whether it fell inside the
    # trade's life (M41). The second is derivable from the first, and is
    # written anyway: the question a reader actually asks is "was this held
    # through a print", and making them recompute it from two dates invites
    # them not to.
    "earnings_at_entry",
    "held_through_earnings",
    # The broker's id for the SELL that closed this trade (M71), so an
    # amendment can target the exact row(s) it belongs to rather than every
    # row for the symbol. Added while the file already has rows without it -
    # `from_row` reads it with `.get()` for exactly that reason.
    "order_id",
)


def _share_of(total_cost: float, matched: float, whole: float) -> float:
    """The part of a per-transaction cost belonging to `matched` of `whole`."""
    if whole <= 0:
        return 0.0
    return total_cost * (matched / whole)


def _optional_date(value: str | None) -> date | None:
    """An ISO date cell that is legitimately blank. Anything unparseable reads
    as absent rather than raising - a diagnostic column must never be able to
    stop a trade history loading."""
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _optional_float(value: str | None) -> float | None:
    """A CSV cell that is legitimately blank, not zero. Writing "" for absent
    and reading it back as 0.0 would turn "no stop recorded" into "stop at
    zero", which every R-multiple downstream would then believe."""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _reseeded(
    current: float | None,
    seed: float,
    actual: float,
    pick: Callable[[float, float], float],
) -> float | None:
    """An excursion extreme after its seed turns out to have been wrong (M70).

    Both extremes start life as the entry price, so when that price is
    corrected an untouched extreme is simply the wrong number and is replaced.
    Once a real tick has moved it the tick is evidence and the correction is
    not, so the range is widened to include the price actually paid rather than
    overwritten by it.
    """
    if current is None:
        return actual
    if current == seed:
        return actual
    return pick(current, actual)


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
    # --- diagnostics carried from entry to close (M37) --------------------
    # None of this decides anything. It exists so that a completed trial can
    # answer WHY a result happened - which regime it was taken in, how it was
    # sized, how far it went against before it worked - and not merely what
    # the result was. It cannot be reconstructed afterwards, so it has to be
    # captured as it happens.
    regime_at_entry: str | None = None
    regime_probability: float | None = None
    exposure_scalar: float | None = None
    reference_price: float | None = None
    """The price the order was sized against, so entry slippage is measurable."""
    worst_price: float | None = None
    """Lowest price seen while held - maximum adverse excursion."""
    best_price: float | None = None
    """Highest price seen while held - maximum favourable excursion."""
    earnings_at_entry: date | None = None
    """The next scheduled announcement as known when the lot was opened (M41)."""
    order_id: str | None = None
    """The broker's id for the order that opened this lot, so a late price
    correction lands on the right lot rather than on whichever one the symbol
    happened to hold (M70). None on a lot restored at startup, which needs no
    correction - `reconcile_entry_prices` has already healed the record it was
    rebuilt from."""


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
    # --- diagnostics (M37) ------------------------------------------------
    regime_at_entry: str | None = None
    regime_probability: float | None = None
    exposure_scalar: float | None = None
    exit_reason: str | None = None
    reference_price: float | None = None
    worst_price: float | None = None
    best_price: float | None = None
    earnings_at_entry: date | None = None
    order_id: str | None = None
    """The broker's id for the sell that closed this trade (M71), so a later
    price correction can target this exact row. `OpenLot` already carries one
    for the same reason on the entry side. None for a trade closed before this
    field existed, or one whose sell was never recorded with an id."""

    @property
    def held_through_earnings(self) -> bool | None:
        """Whether a scheduled announcement fell inside this trade's life (M41).

        None when no date was known, which is a third state and not a "no": an
        ETF has no earnings, a vendor cannot answer for every listing, and a
        trade adopted from the broker was never sized against a calendar at
        all. Reporting those as "did not hold through one" would put them in
        the same bucket as trades that genuinely avoided the event.

        The comparison is against the date recorded AT ENTRY on purpose. By the
        time a position closes the calendar has rolled to the next quarter, so
        asking again afterwards answers a different question.
        """
        if self.earnings_at_entry is None:
            return None
        return self.opened_at.date() <= self.earnings_at_entry <= self.closed_at.date()

    @property
    def holding_days(self) -> float:
        return (self.closed_at - self.opened_at).total_seconds() / 86400.0

    @property
    def entry_slippage(self) -> float | None:
        """Paid versus assumed on the way in. The cost model assumes a figure;
        this is what it actually cost, and the difference is the only way to
        find out whether the assumption holds."""
        if self.reference_price is None or self.reference_price <= 0:
            return None
        return self.entry_price - self.reference_price

    @property
    def mae_r(self) -> float | None:
        """How far the trade went against the entry before it resolved, in
        units of the risk taken. A winner that spent its life at -0.9R was
        nearly a loser, and the average result hides that entirely."""
        risk = self.risk_per_share
        if risk is None or self.worst_price is None:
            return None
        return -(self.entry_price - self.worst_price) / risk

    @property
    def mfe_r(self) -> float | None:
        """How far it went in favour. A loser that reached +2R first says
        something about the exit, not the entry."""
        risk = self.risk_per_share
        if risk is None or self.best_price is None:
            return None
        return (self.best_price - self.entry_price) / risk

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
            "regime_at_entry": self.regime_at_entry or "",
            "regime_probability": (
                round(self.regime_probability, 4) if self.regime_probability is not None else ""
            ),
            "exposure_scalar": (
                round(self.exposure_scalar, 4) if self.exposure_scalar is not None else ""
            ),
            "exit_reason": self.exit_reason or "",
            "holding_days": round(self.holding_days, 3),
            "entry_slippage": (
                round(self.entry_slippage, 4) if self.entry_slippage is not None else ""
            ),
            "mae_r": round(self.mae_r, 3) if self.mae_r is not None else "",
            "mfe_r": round(self.mfe_r, 3) if self.mfe_r is not None else "",
            "r_multiple": round(self.r_multiple, 4) if self.r_multiple is not None else "",
            "gross_r_multiple": (
                round(self.gross_r_multiple, 4) if self.gross_r_multiple is not None else ""
            ),
            "risk_per_share": (
                round(self.risk_per_share, 4) if self.risk_per_share is not None else ""
            ),
            "reference_price": (
                round(self.reference_price, 4) if self.reference_price is not None else ""
            ),
            "worst_price": round(self.worst_price, 4) if self.worst_price is not None else "",
            "best_price": round(self.best_price, 4) if self.best_price is not None else "",
            "earnings_at_entry": (
                self.earnings_at_entry.isoformat() if self.earnings_at_entry is not None else ""
            ),
            # Blank rather than False when unknown. "No date was available" and
            # "a date was available and the trade avoided it" are different
            # facts, and writing both as False would merge them permanently.
            "held_through_earnings": (
                "" if self.held_through_earnings is None else str(self.held_through_earnings)
            ),
            "order_id": self.order_id or "",
        }

    @classmethod
    def from_row(cls, row: dict[str, str]) -> ClosedTrade | None:
        """Rebuild a trade from its CSV row, or None if the row is unusable.

        Only the stored fields are read - everything else on this class is
        derived, and recomputing it is the point. A row this cannot parse is
        skipped rather than raising: a corrupt line must not cost the app every
        trade recorded after it.
        """
        try:
            return cls(
                symbol=row["symbol"],
                strategy=row.get("strategy") or None,
                quantity=float(row["quantity"]),
                entry_price=float(row["entry_price"]),
                exit_price=float(row["exit_price"]),
                stop_price=_optional_float(row.get("stop_price")),
                opened_at=datetime.fromisoformat(row["opened_at"]),
                closed_at=datetime.fromisoformat(row["closed_at"]),
                entry_cost=float(row.get("entry_cost") or 0.0),
                exit_cost=float(row.get("exit_cost") or 0.0),
                regime_at_entry=row.get("regime_at_entry") or None,
                regime_probability=_optional_float(row.get("regime_probability")),
                exposure_scalar=_optional_float(row.get("exposure_scalar")),
                exit_reason=row.get("exit_reason") or None,
                # .get, so a file written before M49 still loads - it simply
                # has no excursion data to restore.
                reference_price=_optional_float(row.get("reference_price")),
                worst_price=_optional_float(row.get("worst_price")),
                best_price=_optional_float(row.get("best_price")),
                # .get, not [...]: every file written before M41 lacks this
                # column, and a restart that discarded its whole trade history
                # over a missing diagnostic would be the M33 mistake again.
                earnings_at_entry=_optional_date(row.get("earnings_at_entry")),
                # .get, for the same reason (M71): the two rows in the live
                # record predate this column entirely.
                order_id=row.get("order_id") or None,
            )
        except (KeyError, TypeError, ValueError):
            return None


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
        # The ledger reads the regime itself rather than having it threaded
        # through the order path (M37). It is already on the bus, and the
        # alternative is five components carrying a field none of them uses.
        self._regime: str | None = None
        self._regime_probability: float | None = None
        self._exposure_scalar: float | None = None
        self._lock = threading.Lock()
        # Read back, not started empty (M49). This list is what EdgeEstimator
        # sizes from, what the promotion gate counts, and what every report
        # reads. It was in-memory only while the file beside it was append-only
        # and never opened, so the trade count reset to zero on every restart -
        # and the app restarts every session. A gate needing 30 closed trades
        # could never have reached them.
        self._closed: list[ClosedTrade] = self._load_closed()
        # Whether closed_trades.csv has been backed up yet in THIS process
        # (M71). Once, before the first amendment - not once per amended row,
        # and not again for a later, unrelated correction.
        self._closed_trades_backed_up = False

    def _load_closed(self) -> list[ClosedTrade]:
        """Trades earlier sessions closed.

        A missing file is a first run, not an error. An unreadable ROW is
        skipped and counted rather than allowed to abort the load, because
        losing every trade after a corrupt line is a far worse failure than
        losing the line.
        """
        if not self.path.exists():
            return []
        trades: list[ClosedTrade] = []
        skipped = 0
        try:
            with self.path.open(newline="", encoding="utf-8") as handle:
                for row in csv.DictReader(handle):
                    trade = ClosedTrade.from_row(row)
                    if trade is None:
                        skipped += 1
                    else:
                        trades.append(trade)
        except OSError:
            logger.exception("Could not read %s - starting with no closed-trade history", self.path)
            return []
        if trades or skipped:
            logger.info(
                "Restored %d closed trade(s) from %s%s",
                len(trades),
                self.path.name,
                f", skipping {skipped} unreadable row(s)" if skipped else "",
            )
        return trades

    def restore_open_lot(
        self,
        symbol: str,
        quantity: float,
        price: float,
        stop_price: float | None,
        strategy: str | None,
        opened_at: datetime,
    ) -> bool:
        """Re-create the entry lot for a position opened before this run (M49).

        A closed trade is only produced by matching a sell against an entry
        lot, and lots lived in memory alone. So a position opened in an earlier
        session - which, with a ten-day minimum hold and a session per night,
        is every position this system holds - could have its stop fire, be
        absorbed correctly, log "this is now a closed trade", and record
        nothing. The ledger's counter could not move off zero, which is the one
        number the whole validation phase exists to produce.

        Refuses to touch a symbol that already has lots. Restoration is a
        startup step and must never compete with a live fill for the same
        position: the running record is always the better one.

        The excursion fields start at the entry price rather than being
        invented, so MAE and MFE on a restored lot measure from the restart
        forward. That understates both, and understating a diagnostic is
        acceptable where fabricating one is not.
        """
        if quantity <= 0 or price <= 0:
            return False
        if self._open_lots.get(symbol):
            return False
        self._open_lots[symbol].append(
            OpenLot(
                symbol=symbol,
                quantity=quantity,
                price=price,
                stop_price=stop_price,
                strategy=strategy,
                opened_at=opened_at,
                entry_cost=self._fill_cost(quantity, price),
                worst_price=price,
                best_price=price,
            )
        )
        return True

    async def start(self) -> None:
        self.bus.subscribe(OrderFilledEvent, self._on_fill)
        self.bus.subscribe(EntryPriceCorrectedEvent, self._on_entry_price_corrected)
        self.bus.subscribe(ExitPriceCorrectedEvent, self._on_exit_price_corrected)
        self.bus.subscribe(RegimeEvent, self._on_regime)
        self.bus.subscribe(MarketDataEvent, self._on_price)

    async def stop(self) -> None:
        self.bus.unsubscribe(OrderFilledEvent, self._on_fill)
        self.bus.unsubscribe(EntryPriceCorrectedEvent, self._on_entry_price_corrected)
        self.bus.unsubscribe(ExitPriceCorrectedEvent, self._on_exit_price_corrected)
        self.bus.unsubscribe(RegimeEvent, self._on_regime)
        self.bus.unsubscribe(MarketDataEvent, self._on_price)

    async def _on_entry_price_corrected(self, event: EntryPriceCorrectedEvent) -> None:
        """Rebases an open lot onto the price the account actually paid (M70).

        The lot is what becomes a ClosedTrade, so correcting the entry record
        and leaving this alone would repair the file and still write the wrong
        trade - with the wrong P&L and the wrong R-multiple denominator, both
        of which feed the promotion gate.

        Matched on the order id rather than the symbol. A lot restored at
        startup carries none, and it does not need one: `reconcile_entry_prices`
        has already corrected the record it was rebuilt from.
        """
        lots = self._open_lots.get(event.symbol)
        if not lots or event.price <= 0:
            return
        for index, lot in enumerate(lots):
            if lot.order_id != event.order_id or lot.price == event.price:
                continue
            lots[index] = replace(
                lot,
                price=event.price,
                # Derived from the price, so a corrected price with a stale
                # cost is a trade paying commission on a fill that never
                # happened.
                entry_cost=self._fill_cost(lot.quantity, event.price),
                # The excursion seeds were the announced price. Left alone they
                # would put a price the market never printed into MAE and MFE -
                # so the seed is replaced where it is still the seed, and merely
                # widened where a real tick has already moved it.
                worst_price=_reseeded(lot.worst_price, event.announced_price, event.price, min),
                best_price=_reseeded(lot.best_price, event.announced_price, event.price, max),
            )

    async def _on_exit_price_corrected(self, event: ExitPriceCorrectedEvent) -> None:
        """Amends the closed-trade record for a sell that filled away from its
        announcement (M71).

        A buy correction rebases an OPEN LOT, still in memory. A sell CLOSES
        the position, so by the time the true fill arrives the `ClosedTrade` is
        already on `closed_trades.csv` - write-then-heal, chosen over deferring
        the write or leaving it manual. The row is rewritten in place, matched
        EXACTLY on order_id so a correction can never land on the wrong trade,
        and backed up before the first amendment this process makes.

        One sell can close several lots, producing several rows from one
        order - every row carrying that order_id is amended, not just the
        first. `exit_cost` is recomputed from the corrected price and
        re-apportioned across them on quantity, the same basis
        `_close_against_lots` used to split it in the first place. `r_multiple`
        and `gross_r_multiple` need no separate handling - they are properties
        derived from `exit_price` and `exit_cost`, so correcting those already
        corrects them.
        """
        if event.price <= 0:
            return
        matched = [
            index for index, trade in enumerate(self._closed) if trade.order_id == event.order_id
        ]
        if not matched:
            # Amend nothing you are not sure of. A correction applied to the
            # wrong trade is worse than no correction - and this is the normal
            # case for every trade closed before M71 added the column an
            # amendment targets.
            logger.info(
                "No closed trade recorded for order %s (%s) - nothing to amend",
                event.order_id,
                event.symbol,
            )
            return
        with self._lock:
            if not self._backup_closed_trades():
                logger.error(
                    "Could not back up %s before amending order %s - amendment abandoned "
                    "rather than risking an unrecoverable rewrite",
                    self.path.name,
                    event.order_id,
                )
                return
            total_quantity = sum(self._closed[index].quantity for index in matched)
            exit_cost_total = self._fill_cost(total_quantity, event.price)
            for index in matched:
                trade = self._closed[index]
                self._closed[index] = replace(
                    trade,
                    exit_price=event.price,
                    exit_cost=_share_of(exit_cost_total, trade.quantity, total_quantity),
                )
            self._rewrite_closed_trades()
        logger.warning(
            "EXIT PRICE CORRECTED ON DISK: %s order %s, %d closed-trade row(s) amended from "
            "%.4f to %.4f (%+.1f bps) - exit price, realised P&L, exit cost and R-multiple all "
            "moved.",
            event.symbol,
            event.order_id,
            len(matched),
            event.announced_price,
            event.price,
            (
                10_000.0 * (event.price - event.announced_price) / event.announced_price
                if event.announced_price
                else 0.0
            ),
        )

    def _backup_closed_trades(self) -> bool:
        """Backs up closed_trades.csv once per process, before the first
        amendment (M71) - the convention the CVS and MNST corrections used.

        An amendment rewrites the whole file, so the backup is the only way
        back to the pre-amendment record. Once, not per row: two rows amended
        by the same sell, or a second unrelated correction later in the same
        process, must not produce a second backup of an already-corrected
        file. Returns False - refusing the amendment - if the backup itself
        cannot be written, since a rewrite with no backup behind it is exactly
        the unrecoverable mistake this exists to prevent.
        """
        if self._closed_trades_backed_up:
            return True
        if not self.path.exists():
            # Nothing to protect yet - there is no amendment without an
            # existing row to amend, so this path is not expected to be hit,
            # but it must not block the write below if it ever is.
            self._closed_trades_backed_up = True
            return True
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = self.path.with_name(f"{self.path.name}.bak-{stamp}")
        try:
            shutil.copy2(self.path, backup)
        except OSError:
            logger.exception("Could not back up %s before amending a closed trade", self.path)
            return False
        logger.warning(
            "BACKED UP %s to %s before the first closed-trade amendment this process makes",
            self.path.name,
            backup.name,
        )
        self._closed_trades_backed_up = True
        return True

    def _rewrite_closed_trades(self) -> None:
        """Rewrites closed_trades.csv from `_closed` (M71).

        Through the same `csv.DictWriter(..., fieldnames=_FIELDS,
        extrasaction="ignore")` path `_record` appends with, so an amended
        file keeps exactly the shape a normal write produces - one shape, one
        writer.
        """
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=_FIELDS, extrasaction="ignore")
                writer.writeheader()
                for trade in self._closed:
                    writer.writerow(trade.as_row())
        except OSError:
            logger.exception("Could not rewrite %s with the amended closed trade(s)", self.path)

    async def _on_regime(self, event: RegimeEvent) -> None:
        self._regime = event.label
        self._regime_probability = event.probs.get(event.label)
        self._exposure_scalar = event.exposure_scalar

    async def _on_price(self, event: MarketDataEvent) -> None:
        """Tracks how far each open lot travelled, both ways.

        Recorded on the lot rather than computed at close because the path is
        gone by then: only the entry and exit prices survive, and those cannot
        say whether a winner spent a week at -0.9R first.
        """
        lots = self._open_lots.get(event.symbol)
        if not lots or event.price <= 0:
            return
        for index, lot in enumerate(lots):
            worst = min(lot.worst_price, event.price) if lot.worst_price else event.price
            best = max(lot.best_price, event.price) if lot.best_price else event.price
            if worst != lot.worst_price or best != lot.best_price:
                lots[index] = replace(lot, worst_price=worst, best_price=best)

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
                    regime_at_entry=self._regime,
                    regime_probability=self._regime_probability,
                    exposure_scalar=self._exposure_scalar,
                    reference_price=event.reference_price,
                    worst_price=event.price,
                    best_price=event.price,
                    earnings_at_entry=event.earnings_at_entry,
                    order_id=event.order_id,
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
                regime_at_entry=lot.regime_at_entry,
                regime_probability=lot.regime_probability,
                exposure_scalar=lot.exposure_scalar,
                exit_reason=event.exit_reason,
                reference_price=lot.reference_price,
                worst_price=lot.worst_price,
                best_price=lot.best_price,
                earnings_at_entry=lot.earnings_at_entry,
                # The SELL's id, not the lot's - this is what a later exit-price
                # correction targets (M71). `OpenLot.order_id` answers a
                # different question (which buy opened it) and is not carried
                # here.
                order_id=event.order_id,
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
                    regime_at_entry=lot.regime_at_entry,
                    regime_probability=lot.regime_probability,
                    exposure_scalar=lot.exposure_scalar,
                    reference_price=lot.reference_price,
                    worst_price=lot.worst_price,
                    best_price=lot.best_price,
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

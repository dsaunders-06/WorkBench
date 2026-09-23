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
import math
import os
import shutil
import threading
from collections import defaultdict, deque
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, date, datetime
from pathlib import Path
from typing import cast

from qat.config import Settings
from qat.domain import market_calendar as mc
from qat.domain.backtester.costs import CostModel
from qat.domain.bus import EventBus
from qat.domain.events import (
    BrokerOrderIdResolvedEvent,
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
    # Which exchange, and what the money on this row is denominated in (M122).
    # This file had no era dimension at all, so two US trades from the Alpaca
    # period - one of them an unadjusted MNST split recorded as a stop-out -
    # sat in the same ledger the ASX trial appends to, with their USD P&L
    # summable against AUD P&L. Blank on both means a pre-M122 row.
    "market",
    "currency",
    # The broker's id for the SELL that closed this trade (M71), so an
    # amendment can target the exact row(s) it belongs to rather than every
    # row for the symbol. Added while the file already has rows without it -
    # `from_row` reads it with `.get()` for exactly that reason.
    "order_id",
)


def repair_csv_header(path: Path, fields: Sequence[str]) -> bool:
    """Rewrite `path`'s header to `fields` when it has fallen behind.

    Returns True if the file was rewritten. Item 63: `_record` writes a
    header only when the file is NEW and then appends under the current
    `fields` forever, so every field added after creation is WRITTEN into
    rows and never NAMED. Found on the live ledger as a 30-field header over
    32-field rows, which made `market`, `currency` and `order_id` unreadable
    - and `EdgeEstimator` filters on `market`, so it matched nothing and
    would have matched nothing at any trade count.

    ⚠️ **Rows are read POSITIONALLY, never through `DictReader`.** Under a
    stale header the surplus values land in the restkey and a
    `DictWriter`-driven rewrite drops them, turning a mislabelling into
    data loss. Values are never re-keyed here: the rows are written back
    byte-for-byte in the columns they already occupy, and only the header
    line changes.

    ⚠️ **This is only safe because `fields` has only ever GROWN by
    appending**, which makes a short row a prefix of the current schema. A
    row WIDER than `fields` means that stopped being true - a field was
    removed or reordered - and a positional remap would move values between
    columns, so it raises rather than guessing.
    """
    if not path.exists() or path.stat().st_size == 0:
        return False
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))
    if not rows:
        return False
    header, data = rows[0], rows[1:]
    if header == list(fields):
        # Untouched rather than rewritten-identically. This is the only
        # record of realised P&L there is, and a rewrite it does not need
        # is risk it does not need either.
        return False
    widest = max((len(row) for row in data), default=0)
    if widest > len(fields):
        raise ValueError(
            f"{path.name} has a row {widest} fields wider than the {len(fields)}-field "
            f"schema, so columns were removed or reordered rather than appended. "
            f"Refusing to remap positionally - this needs a human."
        )
    tmp_path = path.with_name(f"{path.name}.tmp-{os.getpid()}")
    try:
        with tmp_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(list(fields))
            writer.writerows(data)
        os.replace(tmp_path, path)
    except OSError:
        logger.exception("Could not repair the header of %s", path)
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        return False
    logger.warning(
        "Repaired the header of %s: it named %d field(s) while rows carried up to %d, so "
        "%s %s unreadable (item 63)",
        path.name,
        len(header),
        widest,
        ", ".join(f for f in fields if f not in header) or "no field",
        "were" if len([f for f in fields if f not in header]) != 1 else "was",
    )
    return True


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
    market: str | None = None
    """Which exchange this trade belongs to (M122). None for a trade closed
    before this field existed - which is not the same as "unknown market", it
    means the Alpaca/US period, and the migration script names them."""
    currency: str | None = None
    """What `net_pnl` and every other money figure on this row is denominated
    in (M122). Recorded rather than derived from `market`, because a row that
    cannot say what its own numbers mean is not evidence."""
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
        # ⚠️ A ROW IS COMPUTED FROM EXACTLY WHAT IT STORES, or the audit - which
        # re-parses the stored (rounded) inputs and derives again - disagrees
        # with the writer. Derived from the unrounded values, the live ledger
        # failed it with 15 findings on 11 September (BHP.AX `net_pnl stores
        # -3091.29 but computes to -3091.3`). Every column below comes from `s`.
        s = self._as_stored()
        return {
            "opened_at": s.opened_at.isoformat(timespec="seconds"),
            "closed_at": s.closed_at.isoformat(timespec="seconds"),
            "symbol": s.symbol,
            "strategy": s.strategy or "",
            "quantity": round(s.quantity, 6),
            # ⚠️ EIGHT DECIMALS ON PRICES, NOT FOUR, AND THE REASON IS SHARE
            # COUNT. `gross_pnl` and `net_pnl` are DERIVED from these on
            # read-back - `from_row`'s docstring says recomputing them is the
            # point, and it is right: when the SEK.AX ledger was repaired on
            # 9 September the prices were corrected, and an app that trusted a
            # stored P&L column would have carried the old number forever.
            #
            # But a derivation is only as good as what it derives from. At four
            # decimals, IAG.AX's true entry of ~7.92697 stored as 7.9270, and
            # across 6,699 shares that fifth decimal became **twenty cents** -
            # so the 9 September report said -7,797.95 where the ledger said
            # -7,797.75. The error scales with quantity, and TAH is 64,229
            # shares.
            #
            # Eight decimals costs a few bytes a row and makes the round trip
            # exact to well under a cent at any size this account will hold.
            "entry_price": round(s.entry_price, 8),
            "exit_price": round(s.exit_price, 8),
            "stop_price": round(s.stop_price, 8) if s.stop_price is not None else "",
            "gross_pnl": round(s.gross_pnl, 2),
            "entry_cost": round(s.entry_cost, 2),
            "exit_cost": round(s.exit_cost, 2),
            "net_pnl": round(s.net_pnl, 2),
            "pnl_pct": round(s.pnl_pct, 6),
            "regime_at_entry": s.regime_at_entry or "",
            "regime_probability": (
                round(s.regime_probability, 4) if s.regime_probability is not None else ""
            ),
            "exposure_scalar": round(s.exposure_scalar, 4) if s.exposure_scalar is not None else "",
            "exit_reason": s.exit_reason or "",
            "holding_days": round(s.holding_days, 3),
            "entry_slippage": round(s.entry_slippage, 4) if s.entry_slippage is not None else "",
            "mae_r": round(s.mae_r, 3) if s.mae_r is not None else "",
            "mfe_r": round(s.mfe_r, 3) if s.mfe_r is not None else "",
            "r_multiple": round(s.r_multiple, 4) if s.r_multiple is not None else "",
            "gross_r_multiple": (
                round(s.gross_r_multiple, 4) if s.gross_r_multiple is not None else ""
            ),
            "risk_per_share": round(s.risk_per_share, 8) if s.risk_per_share is not None else "",
            "reference_price": (
                round(s.reference_price, 8) if s.reference_price is not None else ""
            ),
            "worst_price": round(s.worst_price, 8) if s.worst_price is not None else "",
            "best_price": round(s.best_price, 8) if s.best_price is not None else "",
            "earnings_at_entry": (
                s.earnings_at_entry.isoformat() if s.earnings_at_entry is not None else ""
            ),
            # Blank rather than False when unknown. "No date was available" and
            # "a date was available and the trade avoided it" are different
            # facts, and writing both as False would merge them permanently.
            "held_through_earnings": (
                "" if s.held_through_earnings is None else str(s.held_through_earnings)
            ),
            "order_id": s.order_id or "",
            # Blank on a pre-M122 row, which means the Alpaca/US period rather
            # than "unknown" - see the migration script, which names them.
            "market": s.market or "",
            "currency": s.currency or "",
        }

    def _as_stored(self) -> ClosedTrade:
        """This trade holding exactly the inputs `as_row` stores - the values
        `from_row` will read back - so what is derived from it is what the
        file's own reader derives. See the warning in `as_row`."""

        def price(value: float | None) -> float | None:
            return round(value, 8) if value is not None else None

        return replace(
            self,
            opened_at=self.opened_at.replace(microsecond=0),
            closed_at=self.closed_at.replace(microsecond=0),
            quantity=round(self.quantity, 6),
            entry_price=round(self.entry_price, 8),
            exit_price=round(self.exit_price, 8),
            stop_price=price(self.stop_price),
            reference_price=price(self.reference_price),
            worst_price=price(self.worst_price),
            best_price=price(self.best_price),
            entry_cost=round(self.entry_cost, 2),
            exit_cost=round(self.exit_cost, 2),
        )

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
                # .get and blank-to-None, same reason again (M122): the two
                # rows in the live record predate both columns, and a restart
                # that dropped them would destroy the only evidence of what the
                # Alpaca period actually did.
                market=row.get("market") or None,
                currency=row.get("currency") or None,
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
        # The broker's CHARGE, modelled (M175). Measured 11 September: IBKR's
        # own commission equals this model on 17 of 17 logged orders, to the
        # cent - and the paper account bills it, so the Alpaca-era reason for
        # modelling ("a paper broker charges nothing") no longer applies; the
        # model is simply exact. `commission_checks.csv` keeps checking it.
        # Slippage is NOT charged here: a fill's price already contains it.
        self._costs = (
            CostModel.from_settings(self.settings)
            if self.settings.apply_costs_in_paper or self.settings.is_live
            else None
        )
        # Per broker order id: (notional booked so far, charge booked so far).
        # One order absorbed in several pieces pays ONE floor across all of
        # them (M175) - LOV.AX's single exit on 26 August paid four. In memory
        # only: a piece absorbed after a restart can pay a second floor, which
        # matters only below ~AUD 7,500 of notional.
        self._charged: dict[str, tuple[float, float]] = {}
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
            # Item 63, BEFORE the DictReader runs: a header that has fallen
            # behind `_FIELDS` makes every field added since unreadable, and
            # `market` is what `EdgeEstimator` filters on.
            repair_csv_header(self.path, _FIELDS)
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
        reference_price: float | None = None,
        worst_price: float | None = None,
        best_price: float | None = None,
        order_id: str | None = None,
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

        The excursion fields fall back to the entry price when the caller has
        nothing better, so MAE and MFE then measure from the restart forward.
        That understates both, and understating a diagnostic is acceptable
        where fabricating one is not.

        The bridge supplies them from daily bars wherever it can (M157, see
        `_excursion_since`) - which is measurement from the same instrument the
        stop distance already rests on, not fabrication. The entry day's own bar
        is excluded there, because it holds prices from before the position
        existed.

        `reference_price` is the price the order was SIZED against, and `None`
        means UNKNOWN - never the entry price, which would report zero slippage
        on a trade nobody measured. ⚠️ M156 carried it onto the record, into
        `open_position_entries.json` and back out again, and stopped HERE: the
        parameter did not exist, so the bridge could not pass it and every
        restored lot got `None`. With a ten-day minimum hold and a session most
        nights, that is every trade this system closes. M157.
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
                entry_cost=self._increment_cost(order_id, quantity, price),
                reference_price=reference_price,
                worst_price=worst_price if worst_price is not None else price,
                best_price=best_price if best_price is not None else price,
                order_id=order_id,
            )
        )
        return True

    async def start(self) -> None:
        self.bus.subscribe(OrderFilledEvent, self._on_fill)
        self.bus.subscribe(BrokerOrderIdResolvedEvent, self._on_order_id_resolved)
        self.bus.subscribe(EntryPriceCorrectedEvent, self._on_entry_price_corrected)
        self.bus.subscribe(ExitPriceCorrectedEvent, self._on_exit_price_corrected)
        self.bus.subscribe(RegimeEvent, self._on_regime)
        self.bus.subscribe(MarketDataEvent, self._on_price)

    async def stop(self) -> None:
        self.bus.unsubscribe(OrderFilledEvent, self._on_fill)
        self.bus.unsubscribe(BrokerOrderIdResolvedEvent, self._on_order_id_resolved)
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
        the write or leaving it manual. Matched EXACTLY on order_id AND symbol
        (M71 review, minor 5 - order_id alone would let a future id collision
        or an adapter's id reuse land a correction on the wrong trade), and
        backed up before the first amendment this process makes.

        The row(s) already on disk are amended IN PLACE - see
        `_amend_closed_trade` - never regenerated from `self._closed`.
        Regenerating from memory silently drops any row `_load_closed` could
        not parse at startup (it is not in `self._closed` at all) and restates
        every untouched row's derived figures from whatever blanks `from_row`
        coerced to 0.0 - a review finding this rewrite exists specifically to
        close.
        """
        if event.price <= 0 or event.quantity <= 0:
            return
        with self._lock:
            outcome = self._amend_closed_trade(event)
        if outcome is None:
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
        amended_count, ok = outcome
        if not ok:
            # The failure itself was already logged at ERROR by whichever step
            # inside `_amend_closed_trade` failed - naming the specific reason
            # (backup failed, write failed, read-back disagreed). This must
            # never be followed by the WARNING below: that line asserts the
            # amendment reached disk, and on this path it did not.
            return
        logger.warning(
            "EXIT PRICE CORRECTED ON DISK: %s order %s, %d closed-trade row(s) amended from "
            "%.4f to %.4f (%+.1f bps) - exit price, realised P&L, exit cost and R-multiple all "
            "moved.",
            event.symbol,
            event.order_id,
            amended_count,
            event.announced_price,
            event.price,
            (
                10_000.0 * (event.price - event.announced_price) / event.announced_price
                if event.announced_price
                else 0.0
            ),
        )

    def _amend_closed_trade(self, event: ExitPriceCorrectedEvent) -> tuple[int, bool] | None:
        """Does the actual amendment, under `self._lock`. Returns None if
        nothing matched (no backup taken, no write attempted), otherwise
        `(rows amended, whether the amendment reached disk safely)`.

        Reads the file fresh rather than trusting `self._closed` to still
        agree with it (M71 review, critical 1 / important 2): a row
        `_load_closed` skipped at startup is not in `self._closed`, and a
        rewrite sourced from memory alone would silently lose it. The disk
        row's own `order_id`/`symbol` columns are what is matched against -
        the same identity check `self._closed` is matched on - so only rows
        that were ever written with this order's id can be touched, and every
        other row is carried forward exactly as read: same strings, same
        blanks, same formatting.
        """
        loaded = self._read_closed_rows()
        if loaded is None:
            return None
        fieldnames, rows = loaded
        disk_targets = [
            index
            for index, row in enumerate(rows)
            if row.get("order_id") == event.order_id and row.get("symbol") == event.symbol
        ]
        memory_targets = [
            index
            for index, trade in enumerate(self._closed)
            if trade.order_id == event.order_id and trade.symbol == event.symbol
        ]
        if not disk_targets and not memory_targets:
            return None
        if len(disk_targets) != len(memory_targets):
            # The two views of "what this order closed" disagree in COUNT, not
            # merely in content - there is no trustworthy way to pair them up
            # row-for-row, so guessing which memory trade corresponds to which
            # disk row is exactly the kind of guess this amendment must not
            # make.
            logger.error(
                "Closed trade record for order %s (%s) disagrees between memory (%d row(s)) "
                "and %s (%d row(s)) - amendment abandoned rather than guessing which rows "
                "correspond",
                event.order_id,
                event.symbol,
                len(memory_targets),
                self.path.name,
                len(disk_targets),
            )
            return len(memory_targets), False
        if not self._backup_closed_trades():
            logger.error(
                "Could not back up %s before amending order %s - amendment abandoned rather "
                "than risking an unrecoverable rewrite",
                self.path.name,
                event.order_id,
            )
            return len(memory_targets), False
        # The order's own quantity - what `_close_against_lots` costed the
        # exit against in the first place - not the sum of what matched a
        # tracked lot (M71 review, minor 6). Those differ once some of the
        # sell was unmatched and ignored, and a per-order commission floor is
        # in play.
        exit_cost_total = self._fill_cost(event.quantity, event.price)
        corrected = [
            replace(
                trade,
                exit_price=event.price,
                exit_cost=_share_of(exit_cost_total, trade.quantity, event.quantity),
            )
            for trade in (self._closed[index] for index in memory_targets)
        ]
        for disk_index, new_trade in zip(disk_targets, corrected, strict=True):
            rows[disk_index] = new_trade.as_row()
        if not self._write_closed_rows(fieldnames, rows):
            return len(memory_targets), False
        if not self._verify_closed_rows(len(rows), disk_targets, event.price):
            return len(memory_targets), False
        for mem_index, new_trade in zip(memory_targets, corrected, strict=True):
            self._closed[mem_index] = new_trade
        return len(memory_targets), True

    def _read_closed_rows(self) -> tuple[list[str], list[dict[str, object]]] | None:
        """Every row on disk, verbatim, keyed by whatever header the file
        actually has - not `_FIELDS` - so a row is read and, if untouched,
        written straight back under the schema it already had. None on a
        missing or unreadable file: there is nothing to amend into.

        Typed `dict[str, object]` rather than the `dict[str, str]`
        `csv.DictReader` actually yields, so an untouched row (a plain string
        value) and an amended one (`ClosedTrade.as_row()`'s floats and dates)
        can sit in the same list and be handed to the one writer below.
        """
        if not self.path.exists():
            return None
        try:
            with self.path.open(newline="", encoding="utf-8") as handle:
                reader = csv.DictReader(handle)
                fieldnames = list(reader.fieldnames or [])
                # Genuinely dict[str, str] at runtime - cast once here so
                # `rows` can also hold an amended row's dict[str, object]
                # (ClosedTrade.as_row()'s floats and dates) without every
                # caller re-litigating the variance.
                rows = cast("list[dict[str, object]]", [dict(row) for row in reader])
        except OSError:
            logger.exception("Could not read %s to amend a closed trade", self.path)
            return None
        return fieldnames, rows

    def _write_closed_rows(self, fieldnames: list[str], rows: list[dict[str, object]]) -> bool:
        """Writes the full row set back to `closed_trades.csv`, atomically.

        `self.path.open("w")` truncates before a single byte of new content
        is written, so a failure or a kill mid-write used to leave a
        truncated evidence file (M71 review, important 3). This writes to a
        sibling temp file first and swaps it in with `os.replace`, which on
        both POSIX and Windows either lands the whole new file or leaves the
        original untouched - never a partial one.
        """
        tmp_path = self.path.with_name(f"{self.path.name}.tmp-{os.getpid()}")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with tmp_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
                writer.writeheader()
                for row in rows:
                    writer.writerow(row)
            os.replace(tmp_path, self.path)
        except OSError:
            logger.exception("Could not write the amended %s", self.path)
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass
            return False
        return True

    def _verify_closed_rows(
        self, expected_row_count: int, targets: list[int], expected_price: float
    ) -> bool:
        """Re-reads `closed_trades.csv` after writing it and confirms the row
        count is unchanged and the amended rows carry the new price (M71
        review, important 4 remainder - the CVS/MNST precedent this backup
        discipline claims to follow does exactly this, and re-reads from disk
        rather than trusting the write).

        This runs unattended, unlike the operator-supervised script it copies
        the convention from, so a silent divergence between what was written
        and what actually landed needs the check more, not less.
        """
        reread = self._read_closed_rows()
        if reread is None:
            logger.error(
                "Could not re-read %s to verify the amendment to order - see the most recent "
                "%s.bak-* backup",
                self.path,
                self.path.name,
            )
            return False
        _fieldnames, rows = reread
        if len(rows) != expected_row_count:
            logger.error(
                "%s has %d row(s) after being amended, expected %d - see the most recent %s.bak-* "
                "backup",
                self.path,
                len(rows),
                expected_row_count,
                self.path.name,
            )
            return False
        for index in targets:
            try:
                # A fresh read of the file just written - genuinely str, same
                # as any other freshly-parsed CSV cell.
                price = float(str(rows[index]["exit_price"]))
            except (KeyError, TypeError, ValueError):
                logger.error(
                    "Row %d of %s does not carry a readable exit_price after being amended - "
                    "see the most recent %s.bak-* backup",
                    index,
                    self.path,
                    self.path.name,
                )
                return False
            if not math.isclose(price, expected_price, rel_tol=1e-6, abs_tol=1e-4):
                logger.error(
                    "Row %d of %s reads back as exit_price=%.4f after being amended to %.4f - "
                    "see the most recent %s.bak-* backup",
                    index,
                    self.path,
                    price,
                    expected_price,
                    self.path.name,
                )
                return False
        return True

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

    async def _on_order_id_resolved(self, event: BrokerOrderIdResolvedEvent) -> None:
        original = event.app_order_id
        if original is None or original == event.order_id:
            return
        for lots in self._open_lots.values():
            for index, lot in enumerate(lots):
                if lot.order_id == original:
                    lots[index] = replace(lot, order_id=event.order_id)
        if original in self._charged:
            self._charged[event.order_id] = self._charged.pop(original)

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
                    entry_cost=self._increment_cost(event.order_id, event.quantity, event.price),
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
        """What one WHOLE order is billed - commission and pass-through fees,
        never slippage (M175). For re-costing an order already known in full:
        a corrected entry, a corrected exit, a lot restored at startup."""
        if self._costs is None:
            return 0.0
        return self._costs.charge(abs(quantity) * price)

    def _increment_cost(self, order_id: str | None, quantity: float, price: float) -> float:
        """What THIS piece of an order adds to the order's bill (M175).

        The floor is charged once per ORDER, so each increment pays the
        difference between the order's charge with it and without it. With no
        order id there is nothing to accumulate against, so the piece is
        costed as a whole order.
        """
        if self._costs is None:
            return 0.0
        notional = abs(quantity) * price
        if not order_id:
            return self._costs.charge(notional)
        booked_notional, booked_charge = self._charged.get(order_id, (0.0, 0.0))
        total_notional = booked_notional + notional
        total_charge = self._costs.charge(total_notional)
        self._charged[order_id] = (total_notional, total_charge)
        return total_charge - booked_charge

    def _close_against_lots(self, event: OrderFilledEvent) -> None:
        remaining = event.quantity
        lots = self._open_lots[event.symbol]
        # The exit's cost belongs to the whole sell, so it is apportioned
        # across whatever lots this sell happens to close - by quantity, the
        # same basis the entry cost is split on.
        exit_cost_total = self._increment_cost(event.order_id, event.quantity, event.price)
        exit_quantity = event.quantity

        while remaining > 1e-9 and lots:
            lot = lots[0]
            # ⚠️ AN EXIT CANNOT PRECEDE THE LOT IT CLOSES (24 August 2026).
            #
            # This is arithmetic, not a plausibility judgement, and nothing
            # checked it until seven such trades reached `closed_trades.csv`.
            #
            # How they got there: `absorbed_fills.json`'s watermark advances
            # during a run, so when the process was killed at 14:08 it stayed at
            # 10:38. The next run replayed the whole interval - including the
            # operator's MANUAL remediation sells at 14:24 - and, because
            # `_is_foreign_unrecorded` tests in-memory sets that do not survive
            # a restart, every one of them read as a foreign fill. They were
            # matched against the lot opened at 15:19:36, producing trades that
            # closed an hour before they opened, worth -$167.90 nobody lost, in
            # the file the promotion gate reads.
            #
            # Refused rather than repaired, and LOUDLY: the lot is left intact
            # and the fill is dropped from the match. A fill this old belongs to
            # a position this process never opened, so there is no correct lot
            # for it here - inventing one is what produced the corruption.
            #
            # NARROWED, and an existing test is what narrowed it. The first
            # version refused on the timestamps alone and broke
            # test_live_exit_price_correction, which absorbs an exit against an
            # ADOPTED lot. That is the distinction that matters:
            #
            #   * a lot with a STRATEGY was opened by this app from its own entry
            #     fill, so `opened_at` is a real observation and an earlier exit
            #     is impossible;
            #   * a lot with NO strategy was adopted from the broker, where
            #     `opened_at` is a placeholder stamped at adoption time because
            #     no entry record existed. Comparing a real exit stamp against a
            #     placeholder proves nothing, and refusing on it would discard
            #     the legitimate M50 case - a position partially closed while
            #     this was down, whose remainder is adopted at restart and whose
            #     exit is genuinely older than the adoption.
            #
            # Today's corruption was the first kind: strategy "swing", opened
            # 15:19:36, matched against an exit at 14:24:45.
            if lot.strategy is not None and event.ts < lot.opened_at:
                logger.error(
                    "REFUSED an impossible closed trade: %s exit at %s precedes the lot "
                    "it would close, opened %s. Dropping %g shares from the match rather "
                    "than recording a trade that closed before it opened. This is the "
                    "24 August absorb-replay signature - check the fill watermark in "
                    "absorbed_fills.json against when this process started.",
                    event.symbol,
                    event.ts.isoformat(timespec="seconds"),
                    lot.opened_at.isoformat(timespec="seconds"),
                    remaining,
                )
                return
            matched = min(remaining, lot.quantity)
            # ⚠️ THE EXIT IS PART OF THE EXCURSION (31 August). worst/best were
            # only ever updated by `_on_price` from a market tick, so a
            # broker-side stop filling at a price the app never saw as a tick
            # was invisible to MAE. Measured on the PNI.AX stop-out - the first
            # trade this system ever produced with `mae_r` populated:
            #
            #   entry 17.9258  exit 15.56  r_multiple -1.6455
            #   worst_price 16.9979  ->  mae_r -0.633
            #
            # `worst_price` HIGHER than the exit. The trade reached its own exit
            # price by definition, so a loser's MAE can never be less severe
            # than its realised R - and the error ran in the dangerous
            # direction, making a gapped stop look milder than it was, on
            # exactly the case M44 exists to measure.
            #
            # min/max, never assignment: a genuinely worse tick the app DID see
            # must still win.
            exit_worst = min(lot.worst_price, event.price) if lot.worst_price else event.price
            exit_best = max(lot.best_price, event.price) if lot.best_price else event.price
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
                worst_price=exit_worst,
                best_price=exit_best,
                earnings_at_entry=lot.earnings_at_entry,
                # The SELL's id, not the lot's - this is what a later exit-price
                # correction targets (M71). `OpenLot.order_id` answers a
                # different question (which buy opened it) and is not carried
                # here.
                order_id=event.order_id,
                # Stamped at close from the running configuration (M122), which
                # is the only moment either fact is known for certain.
                market=self.settings.market,
                currency=mc.currency_for(self.settings.market),
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
                    # The residual lot keeps the folded excursion too: this exit
                    # happened while it was held, so it belongs to whatever
                    # closes the remainder later.
                    worst_price=exit_worst,
                    best_price=exit_best,
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

    @staticmethod
    def repair_header(path: Path) -> bool:
        """`repair_csv_header` for the closed-trade schema. See item 63."""
        return repair_csv_header(path, _FIELDS)

    def _record(self, trade: ClosedTrade) -> None:
        try:
            with self._lock:
                # Appended under the same lock the amendment path takes to
                # read and rewrite `self._closed` (M71 review, minor 7) - this
                # append used to happen before the lock was acquired, which
                # made it possible for an in-flight amendment to observe a
                # list it does not yet know about, or vice versa.
                self._closed.append(trade)
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

    def closed_trades(
        self, strategy: str | None = None, market: str | None = None
    ) -> list[ClosedTrade]:
        """Closed trades, optionally narrowed to one strategy and one market.

        `market` exists because strategy alone was never a sufficient filter
        (M122). "swing" names the same code on two exchanges in two currencies,
        so asking for swing's trades returned an Alpaca US loss alongside the
        ASX trial's - and `EdgeEstimator` turns exactly that list into a win
        rate that sets position size.

        ⚠️ RETURNS POSITIONS, NOT ROWS. A position that closes in pieces is
        written as one row per fill - five LOV.AX rows on 25 August 2026 shared
        one `order_id` and closed within 25 seconds, and they were ONE position
        filling its target. Every caller of this method is asking "how did the
        strategy do", and the answer is a count of trades, not of fills:
        `edge_min_trades` gates the position sizer on it, the promotion gate
        reads it, and the Performance tab and daily report display it. Rows read
        9 trades at 55.6% and 0.47 payoff; the 5 positions behind them read 40%
        and 0.87.

        ⚠️ THE RECORD ITSELF IS UNTOUCHED. `closed_trades.csv` is appended and
        amended in place and is "never regenerated from `self._closed`", so
        collapsing here changes what is REPORTED and never what is stored - the
        fills remain individually recoverable from the file.
        """
        trades = list(self._closed)
        if strategy is not None:
            trades = [trade for trade in trades if trade.strategy == strategy]
        if market is not None:
            trades = [trade for trade in trades if trade.market == market]
        return collapse_to_positions(trades)

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
    market: str | None = None
    """Which account this sample measures (M127). None means a sample written
    before this column existed - the Alpaca/US period - and is treated as its
    own era rather than as "unknown"."""
    position_value: float | None = None
    """Market value of what was HELD at this sample (M133). None when the
    broker did not report it, or on any sample written before the column
    existed - and "unknown" is not "nothing held"."""

    def as_row(self) -> dict[str, object]:
        return {
            "ts": self.ts.isoformat(timespec="seconds"),
            "equity": round(self.equity, 2),
            "cash": round(self.cash, 2),
            "market": self.market or "",
            "position_value": "" if self.position_value is None else round(self.position_value, 2),
        }


class EquityCurve:
    """Append-only equity samples.

    Kept separate from the closed-trade ledger because they answer different
    questions: trades measure decision quality, the curve measures the account.
    A strategy can have a good win rate while the account bleeds, and only
    having both lets you see it.
    """

    FILENAME = "equity_curve.csv"
    # "market" since M127. This file spans a BROKER MIGRATION: on 2026-08-18 it
    # records 101,157.17 in an Alpaca US account and on 2026-08-19 it records
    # 1,003,733.21 in an IBKR one, in a single continuous series. Nothing said
    # so, and the weekly report of 21 August read the step as "a dramatic
    # nominal equity rise ... a 896.39% increase" and had an LLM reason about
    # it as performance. Sharpe and max drawdown for that week were computed
    # across the change of account.
    _FIELDS = ("ts", "equity", "cash", "market", "position_value")

    def __init__(
        self, data_dir: str | Path, filename: str | None = None, market: str | None = None
    ) -> None:
        self.path = Path(data_dir) / (filename or self.FILENAME)
        self.market = market
        self._points: list[EquityPoint] = self._load()
        self._lock = threading.Lock()
        self._warned_about_eras = False

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
        # Item 63, the same defect as the trade ledger and found by
        # CHECKING rather than assuming this file was clean: the
        # header named 4 fields while rows carried 5, so M133's
        # `position_value` was written on every sample and readable on
        # none - and "unknown" is not "nothing held".
        repair_csv_header(self.path, self._FIELDS)
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
                                # .get, so every pre-M127 file still loads.
                                market=row.get("market") or None,
                                position_value=_optional_float(row.get("position_value")),
                            )
                        )
                    except (KeyError, TypeError, ValueError):
                        continue  # one unreadable row must not discard the rest
        except OSError:
            logger.exception("Could not read the equity history at %s", self.path)
            return []
        return points

    def record(
        self,
        equity: float,
        cash: float,
        ts: datetime | None = None,
        position_value: float | None = None,
    ) -> EquityPoint:
        point = EquityPoint(
            ts=ts or datetime.now(UTC),
            equity=equity,
            cash=cash,
            market=self.market,
            position_value=position_value,
        )
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
        """The samples for the CURRENT era only (M127).

        Scoped here rather than at each caller because there are four of them -
        the daily report, the weekly report, the summary and the dashboard
        chart - and every one computes returns, drawdown or Sharpe by walking
        this list. A caller that forgot would not fail; it would publish a
        number. The weekly report of 21 August published 896.39%.

        An "era" is a run of samples sharing one market label. The trailing run
        is the current account, and everything before the last change belongs
        to a different one - a different broker, a different base currency, and
        a step between them that is a transfer rather than a return. Use
        `all_points()` for the whole file.
        """
        points = list(self._points)
        if not points:
            return points

        current = points[-1].market
        first = len(points)
        while first > 0 and points[first - 1].market == current:
            first -= 1

        if first > 0 and not self._warned_about_eras:
            self._warned_about_eras = True
            logger.warning(
                "Equity history spans more than one account: %d sample(s) before "
                "%s belong to a different era (%r) and are EXCLUDED from returns, "
                "drawdown and Sharpe. The step between two accounts is a transfer, "
                "not a return.",
                first,
                points[first].ts.date().isoformat(),
                points[first - 1].market or "unlabelled (pre-M127)",
            )
        return points[first:]

    def all_points(self) -> list[EquityPoint]:
        """Every sample, eras included. For migration and inspection only."""
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


def collapse_to_positions(trades: list[ClosedTrade]) -> list[ClosedTrade]:
    """Ledger ROWS collapsed into distinct POSITIONS.

    ⚠️ A POSITION CAN CLOSE IN PIECES, and each piece was written as its own
    row. Measured in the live ledger on 7 September 2026: five LOV.AX rows
    sharing one `opened_at`, one `order_id` (1216552509) and closing within 25
    seconds of each other, in quantities 10 / 15 / 26 / 323 / 2843. One
    position filling its target, recorded as five trades.

    ⚠️ WHY THIS MATTERS MORE THAN THE DISPLAY. `edge_min_trades = 20` is what
    stops the sizer using invented constants (win rate 0.55, payoff 1.5), and
    it counts what `closed_trades()` returns. One fragmented exit yielded five,
    so the gate flips to "measured" on an unpredictable fraction of twenty real
    trades - the protection against acting on too small a sample was itself
    miscounting. The promotion gate at thirty reads the same list.

    And the statistics moved with it: the live ledger reported 9 trades, 55.6%
    win rate and 0.47 payoff, where the distinct positions are 5 trades, 40%
    and 0.87. Four winning fragments of ONE position outvoted three whole
    losers.

    ⚠️ QUANTITY-WEIGHTED prices, because `gross_pnl`, `net_pnl` and
    `r_multiple` are computed properties over quantity, price and cost. Summing
    quantity and costs and weighting price by quantity is the only merge that
    leaves the arithmetic identical; a plain mean would quietly restate the P&L.

    ⚠️ A MISSING `order_id` IS NOT A KEY. Older rows predate the field, and
    absence is not evidence that two rows are the same position - merging on it
    would silently combine unrelated history, so each such row stands alone.
    """
    groups: dict[object, list[ClosedTrade]] = {}
    singles: list[ClosedTrade] = []
    for trade in trades:
        if not trade.order_id:
            singles.append(trade)
            continue
        groups.setdefault((trade.order_id, trade.symbol, trade.opened_at), []).append(trade)

    merged: list[ClosedTrade] = list(singles)
    for members in groups.values():
        if len(members) == 1:
            merged.append(members[0])
            continue
        quantity = sum(m.quantity for m in members)
        if quantity <= 0:
            # Nothing to weight by, so no defensible average exists. Kept as
            # separate rows rather than invented into one.
            merged.extend(members)
            continue
        first = members[0]
        merged.append(
            replace(
                first,
                quantity=quantity,
                entry_price=sum(m.entry_price * m.quantity for m in members) / quantity,
                exit_price=sum(m.exit_price * m.quantity for m in members) / quantity,
                entry_cost=sum(m.entry_cost for m in members),
                exit_cost=sum(m.exit_cost for m in members),
                opened_at=min(m.opened_at for m in members),
                closed_at=max(m.closed_at for m in members),
            )
        )
    merged.sort(key=lambda t: t.closed_at)
    return merged


# Derived column -> (property name, decimal places `as_row` rounds it to).
# Every one of these is a COMPUTED property written out for readers; nothing in
# the application reads them back, which is exactly why they can drift unnoticed.
_DERIVED_COLUMNS = {
    "gross_pnl": ("gross_pnl", 2),
    "net_pnl": ("net_pnl", 2),
    "pnl_pct": ("pnl_pct", 6),
    "r_multiple": ("r_multiple", 4),
}


def audit_closed_trades(path: Path) -> list[str]:
    """Rows whose STORED derived columns disagree with the computed ones.

    ⚠️ WHY THIS EXISTS. On 7 September the live ledger held a LOV.AX row with
    2,843 shares, `gross_pnl` of 12,021.91 and `net_pnl` BLANK - written by the
    26 August repair script rather than by `as_row`, which always writes the
    computed value. The application was never wrong: `net_pnl` is a property, so
    in memory that row reads 12,021.91. Only the FILE was wrong.

    That is the dangerous shape. The CSV is what a person opens to check
    performance by hand, and reading the blank as zero turned a +$13,558 winner
    into a +$1,535 one - which flipped the measured payoff ratio from 2.32 to
    0.87 and the Kelly fraction from positive to negative. Nothing reported a
    problem, because nothing was comparing the two.

    Returns one line per discrepancy, empty when the file agrees with itself.
    A row `from_row` cannot parse is reported rather than skipped: unreadable
    is a discrepancy too, and `_load_closed` drops such rows silently.
    """
    if not path.exists():
        return []
    findings: list[str] = []
    with path.open(newline="", encoding="utf-8") as handle:
        for number, row in enumerate(csv.DictReader(handle), start=2):
            trade = ClosedTrade.from_row(row)
            if trade is None:
                findings.append(f"row {number}: could not be parsed, so it is invisible to the app")
                continue
            for column, (attribute, places) in _DERIVED_COLUMNS.items():
                stored = (row.get(column) or "").strip()
                computed = getattr(trade, attribute)
                if computed is None:
                    # Genuinely not computable - a trade with no stop has no R.
                    if stored:
                        findings.append(
                            f"row {number} ({trade.symbol}): {column} stores {stored!r} but "
                            f"the trade cannot produce one"
                        )
                    continue
                if not stored:
                    findings.append(
                        f"row {number} ({trade.symbol}, qty {trade.quantity:g}): {column} is "
                        f"BLANK but computes to {round(computed, places)} - anything reading "
                        f"this file gets a wrong answer"
                    )
                    continue
                try:
                    if abs(float(stored) - round(computed, places)) > 10 ** (-places) / 2:
                        findings.append(
                            f"row {number} ({trade.symbol}): {column} stores {stored} but "
                            f"computes to {round(computed, places)}"
                        )
                except ValueError:
                    findings.append(f"row {number} ({trade.symbol}): {column} is not a number")
    return findings

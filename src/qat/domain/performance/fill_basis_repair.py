"""Rebuild records whose entry price is IBKR's commission-inclusive average (M175).

`reconcile_entry_prices` (M65) wrote IBKR's `avgCost` over the fill at every
restart, and `avgCost` includes the commission - so every stored entry sits
8.8 bp high and `entry_cost` charged the same commission again. Found
11 September on all 12 closed rows and all 10 open records.

Evidence, never blanket:
  * a price is inflated ONLY if a logged M65 line wrote it (matched on the %g
    string M65 printed);
  * the true fill is the logged execDetails average where the logs hold the
    entry, else `CostModel.fill_price_from_average_cost`;
  * SELF-CHECK: where a logged fill exists, the formula must reproduce it within
    SELF_CHECK_DOLLARS over the order, or nothing is written.

Costs are recomputed on EVERY row - option A needs no evidence.

ONE RUN ONLY. After a repair the stored entries no longer match the %g strings
M65 printed, so a second run would find no evidence for a fragment, drop its
no-floor treatment and charge it whole floors; and once M175 is deployed, M65's
own log lines would be read as fresh inflation and deflate prices a second
time. `prior_repair` detects a completed repair so the script can refuse.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from qat.data.symbols import from_ibkr
from qat.domain.backtester.costs import CostModel
from qat.domain.performance.trades import ClosedTrade

SELF_CHECK_DOLLARS = 0.25

_BACKUP_PATTERNS = (
    "closed_trades.csv.bak-fill-basis-*",
    "open_position_entries.json.bak-fill-basis-*",
)
_SEED_TOLERANCE = 5e-5
"""Absolute: half a 4-dp unit. A seed stored at 4 dp (RHC.AX's 44.4523 for
44.45230503) sits 5e-6 from its entry, and 4-dp rounding never moves a price
more than 5e-5 - at any price level, so the bound does not scale with it. A
price further away than that really traded (44.45 against the same entry)."""

_M65_RE = re.compile(
    r"Corrected the recorded entry price for (?P<body>.+?) to what the broker charged"
)
_M65_PAIR_RE = re.compile(r"(?P<symbol>[A-Z0-9.]+) -> (?P<price>[0-9.eE+-]+)")
_EXEC_RE = re.compile(
    r"execDetails: Fill\(contract=Stock\([^)]*symbol='(?P<sym>[^']+)'.*?"
    r"execId='(?P<exec>[^']+)'.*?side='(?P<side>[A-Z]+)', shares=(?P<shares>[\d.]+), "
    r"price=(?P<price>[\d.]+), permId=(?P<perm>\d+)"
)


class SelfCheckFailed(Exception):
    """The formula did not reproduce a logged fill - write nothing."""


@dataclass(frozen=True, slots=True)
class LoggedBuy:
    order_id: str
    symbol: str
    quantity: float
    average_price: float


@dataclass(frozen=True, slots=True)
class Evidence:
    fill: float
    source: str
    order_quantity: float | None
    """The entry order's whole size, when the logs hold it."""


@dataclass(frozen=True, slots=True)
class RowRepair:
    index: int
    before: ClosedTrade
    after: ClosedTrade
    evidence: Evidence | None
    fragment: bool


@dataclass(frozen=True, slots=True)
class RecordChange:
    symbol: str
    before: float
    after: float
    evidence: Evidence


def prior_repair(data_dir: Path) -> str | None:
    """Why this data dir has already been repaired, or None if it has not.

    Evidence of a repair: a backup the script's `--apply` made, or an open
    record stamped `"price_source": "fill"` (only the repair and an M175 build
    write that stamp - either way the stored prices are no longer M65's).
    """
    for pattern in _BACKUP_PATTERNS:
        backups = sorted(p.name for p in data_dir.glob(pattern))
        if backups:
            return f"{data_dir / backups[0]} exists - the fill-basis repair was already applied"
    entries = data_dir / "open_position_entries.json"
    if entries.exists():
        records = json.loads(entries.read_text(encoding="utf-8"))
        stamped = sorted(
            symbol
            for symbol, record in records.items()
            if isinstance(record, dict) and record.get("price_source") == "fill"
        )
        if stamped:
            return (
                f"{entries} already stamps {', '.join(stamped)} with "
                f'"price_source": "fill" - those prices are already fills'
            )
    return None


def read_log_messages(log_dir: Path) -> list[str]:
    """The `message` field of every JSON line in qat.log and its rotations."""
    messages: list[str] = []
    for path in sorted(log_dir.glob("qat.log*")):
        with path.open(encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if "Corrected the recorded entry price" not in line and "execDetails" not in line:
                    continue
                try:
                    messages.append(str(json.loads(line)["message"]))
                except (ValueError, KeyError):
                    continue
    return messages


def parse_m65_corrections(messages: Iterable[str]) -> dict[str, set[str]]:
    """symbol -> every %g price string M65 ever wrote for it."""
    found: dict[str, set[str]] = defaultdict(set)
    for message in messages:
        match = _M65_RE.search(message)
        if match is None:
            continue
        for pair in _M65_PAIR_RE.finditer(match["body"]):
            found[pair["symbol"]].add(pair["price"])
    return dict(found)


def parse_logged_buys(messages: Iterable[str], market: str) -> list[LoggedBuy]:
    """BOT executions totalled per permId, in the app's symbol form."""
    seen: set[str] = set()
    totals: dict[str, list[Any]] = {}
    for message in messages:
        if not message.startswith("execDetails"):
            continue
        match = _EXEC_RE.search(message)
        if match is None or match["side"] != "BOT" or match["exec"] in seen:
            continue
        seen.add(match["exec"])
        shares, price = float(match["shares"]), float(match["price"])
        entry = totals.setdefault(match["perm"], [from_ibkr(match["sym"], market), 0.0, 0.0])
        entry[1] += shares
        entry[2] += shares * price
    return [
        LoggedBuy(order_id=perm, symbol=sym, quantity=qty, average_price=notional / qty)
        for perm, (sym, qty, notional) in totals.items()
        if qty > 0
    ]


def evidence_for(
    symbol: str,
    stored_price: float,
    quantity: float,
    corrections: dict[str, set[str]],
    buys: list[LoggedBuy],
    costs: CostModel,
) -> Evidence | None:
    """The true fill behind an inflated price, or None when M65 never wrote it."""
    if f"{stored_price:g}" not in corrections.get(symbol, set()):
        return None
    candidates = [b for b in buys if b.symbol == symbol]
    # Each candidate is checked against ITS OWN order quantity, not the
    # quantity of whatever row happens to be asking. A row can be a FRAGMENT
    # of a much larger order - TNE.AX below is 60 of a 3,051-share entry -
    # and the floor-vs-proportional branch of `fill_price_from_average_cost`
    # depends on quantity: deriving on the fragment's own 60 shares picks the
    # floor branch and lands nowhere near the logged fill, even though the
    # order itself (3,051 shares) is nowhere near the floor and reproduces it
    # to a fraction of a cent. "Over the order" in the module docstring means
    # exactly this: the order's quantity, not the caller's.
    for buy in candidates:
        derived = costs.fill_price_from_average_cost(stored_price, buy.quantity)
        if abs(derived - buy.average_price) * buy.quantity <= SELF_CHECK_DOLLARS:
            return Evidence(buy.average_price, f"logged fill, order {buy.order_id}", buy.quantity)
    if candidates:
        raise SelfCheckFailed(
            f"{symbol}: {len(candidates)} logged buy(s), and none is reproduced by "
            f"{stored_price} / (1 + commission) within ${SELF_CHECK_DOLLARS} an order - "
            f"refusing to write anything"
        )
    derived = costs.fill_price_from_average_cost(stored_price, quantity)
    # With no logged order, the caller's quantity is the only size there is -
    # and the floor branch depends on it. Above the floor the answer is the
    # same at any size (avgCost / (1 + rate)); ON the floor branch it is only
    # right if this quantity really was the whole order. A fragment whose entry
    # order rotated out of the logs looks exactly like a small order, and
    # there is nothing here to tell them apart - so refuse rather than guess.
    if derived * quantity * costs.commission_bps / 10_000.0 < costs.min_commission:
        raise SelfCheckFailed(
            f"{symbol}: no logged buy, and at quantity {quantity:g} the formula takes the "
            f"${costs.min_commission:.2f} floor branch ({stored_price} -> {derived:.8f}) - "
            f"that is only right if {quantity:g} was the whole entry order, and a fragment "
            f"whose order rotated out of the logs cannot be told apart - refusing to write anything"
        )
    return Evidence(derived, "IBKR avgCost / (1 + commission rate)", None)


def _proportional(costs: CostModel, notional: float) -> float:
    """The rate without the floor - for a fragment of an order of unknown size."""
    return abs(notional) * (costs.commission_bps + costs.third_party_bps) / 10_000.0


def _reseed(
    current: float | None,
    seed: float,
    actual: float,
    pick: Callable[[float, float], float],
) -> float | None:
    """`trades._reseeded`, except a seed stored at LOWER PRECISION is still the
    seed. RHC.AX's best_price is 44.4523 for an entry of 44.45230503; exact
    equality misses it, and pick(max) then keeps the inflated average - a price
    that never traded - as the trade's best. Within `_SEED_TOLERANCE` (absolute)
    of the seed it IS the seed; any further and it is a real tick, kept."""
    if current is None:
        return actual
    if abs(current - seed) <= _SEED_TOLERANCE:
        return actual
    return pick(current, actual)


def repair_closed_rows(
    rows: list[dict[str, str]],
    corrections: dict[str, set[str]],
    buys: list[LoggedBuy],
    costs: CostModel,
) -> list[RowRepair]:
    trades: list[ClosedTrade] = []
    for number, row in enumerate(rows):
        trade = ClosedTrade.from_row(row)
        if trade is None:
            raise ValueError(f"row {number + 2} cannot be parsed - refusing to rewrite the file")
        trades.append(trade)

    lots: dict[tuple[str, str], list[int]] = defaultdict(list)
    for index, trade in enumerate(trades):
        lots[(trade.symbol, trade.opened_at.isoformat())].append(index)

    fill_of: dict[int, float] = {}
    evidence_of: dict[int, Evidence | None] = {}
    fragment_of: dict[int, bool] = {}
    entry_cost_of: dict[int, float] = {}
    for (symbol, opened_at), members in lots.items():
        stored = trades[members[0]].entry_price
        prices = sorted({trades[i].entry_price for i in members})
        if prices[-1] - prices[0] > 1e-9:
            raise ValueError(
                f"{symbol} opened {opened_at}: the rows of this lot carry different entry "
                f"prices {prices} - one lot has one entry price; refusing to rewrite the file"
            )
        lot_quantity = sum(trades[i].quantity for i in members)
        ev = evidence_for(symbol, stored, lot_quantity, corrections, buys, costs)
        if (
            ev is not None
            and ev.order_quantity is not None
            and ev.order_quantity + 1e-9 < lot_quantity
        ):
            raise SelfCheckFailed(
                f"{symbol} opened {opened_at}: the lot is {lot_quantity:g} shares but the "
                f"matched order ({ev.source}) is only {ev.order_quantity:g} - the lot came "
                f"from more than one order, or the log undercounts; refusing to write anything"
            )
        fill = ev.fill if ev is not None else stored
        whole = ev.order_quantity if ev is not None and ev.order_quantity else lot_quantity
        order_charge = costs.charge(fill * whole)
        for i in members:
            fill_of[i] = fill
            evidence_of[i] = ev
            fragment_of[i] = lot_quantity + 1e-9 < whole
            entry_cost_of[i] = order_charge * trades[i].quantity / whole

    exit_groups: dict[str, list[int]] = defaultdict(list)
    for index, trade in enumerate(trades):
        exit_groups[trade.order_id or f"row-{index}"].append(index)
    exit_cost_of: dict[int, float] = {}
    for members in exit_groups.values():
        quantity = sum(trades[i].quantity for i in members)
        notional = sum(trades[i].quantity * trades[i].exit_price for i in members)
        fragment = any(fragment_of[i] for i in members)
        total = _proportional(costs, notional) if fragment else costs.charge(notional)
        for i in members:
            exit_cost_of[i] = total * trades[i].quantity / quantity

    repairs: list[RowRepair] = []
    for index, before in enumerate(trades):
        fill = fill_of[index]
        after = replace(
            before,
            entry_price=fill,
            entry_cost=entry_cost_of[index],
            exit_cost=exit_cost_of[index],
            worst_price=_reseed(before.worst_price, before.entry_price, fill, min),
            best_price=_reseed(before.best_price, before.entry_price, fill, max),
        )
        repairs.append(RowRepair(index, before, after, evidence_of[index], fragment_of[index]))
    return repairs


def repair_open_records(
    records: dict[str, dict[str, Any]],
    corrections: dict[str, set[str]],
    buys: list[LoggedBuy],
    costs: CostModel,
) -> tuple[dict[str, dict[str, Any]], list[RecordChange]]:
    """Open entry records: price -> fill, stamped "fill". Quantity is not on
    the record, so the formula takes its proportional branch - every open
    position is far above the ~AUD 7,500 floor crossover."""
    repaired: dict[str, dict[str, Any]] = {}
    changes: list[RecordChange] = []
    for symbol, record in records.items():
        stored = float(record["price"])
        ev = evidence_for(symbol, stored, 1e12, corrections, buys, costs)
        if ev is None:
            repaired[symbol] = dict(record)
            continue
        repaired[symbol] = {**record, "price": ev.fill, "price_source": "fill"}
        changes.append(RecordChange(symbol, stored, ev.fill, ev))
    return repaired, changes

"""Why an order did NOT happen (M51).

The trade ledger records what the system did. Nothing recorded what it was
prevented from doing, and at a ten-position cap that is where the behaviour
actually lives: on 5 August the book refused 503 orders and took one.

**A strategy that is never allowed to trade looks identical to one with no
setups.** The promotion gate counts outcomes; without this, a rail quietly
strangling a strategy is invisible - and so is a rail doing exactly its job.

The distinction this module exists to draw is between refusals that mean
different things:

* **Capacity** - the book could not fit it. Says NOTHING about the candidate.
  A month of these means "raise the limits or accept slower evidence".
* **Candidate** - this particular trade failed a test. A month of these means
  the strategy is producing trades the rails do not like, which is a statement
  about the strategy.
* **State** - the system was not accepting orders at all. Kill-switch, market
  closed, an ineligible session phase.
* **Execution** - it reached the broker and the broker said no. That is the app
  and the account disagreeing, which is a defect signal rather than a rail
  signal, and it should be read as one.

Counting them together produces a number that cannot be acted on. Counting them
apart is the whole point.
"""

from __future__ import annotations

import csv
import logging
from collections import Counter
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

logger = logging.getLogger(__name__)

RISK_DECISIONS_FILENAME = "risk_decisions.csv"


class RefusalFamily(StrEnum):
    """What a refusal tells you. Ordered by how it should be read."""

    CAPACITY = "capacity"
    CANDIDATE = "candidate"
    STATE = "state"
    EXECUTION = "execution"
    UNCLASSIFIED = "unclassified"

    @property
    def means(self) -> str:
        return _MEANINGS[self]


_MEANINGS = {
    RefusalFamily.CAPACITY: "the book was full - says nothing about the trade",
    RefusalFamily.CANDIDATE: "this trade failed a test - says something about the strategy",
    RefusalFamily.STATE: "the system was not accepting orders",
    RefusalFamily.EXECUTION: "the broker refused it - the app and the account disagreed",
    RefusalFamily.UNCLASSIFIED: "not recognised - see the note below",
}

# Matched against a lowercased reason. Ordered: the first match wins, so the
# specific sits above the general.
#
# Patterns are fragments of the strings the rails actually emit, taken from the
# source rather than guessed - `governor.py` for the caps, `engine.py` for the
# cost rail, `oms.py` for the gate and the broker.
# Each carries the RAIL's stable name as well as its family. Grouping by the
# reason text does not work: "Round-trip cost $18.24 is 13.2% of the $138.38 at
# risk" differs per symbol and per tick, so one rail fragmented into dozens of
# rows and the largest of them understated it by an order of magnitude. The
# label is what a human calls the rail; the numbers belong to the instance.
_PATTERNS: tuple[tuple[str, RefusalFamily, str], ...] = (
    ("position limit", RefusalFamily.CAPACITY, "Position limit"),
    ("aggregate risk-at-stop", RefusalFamily.CAPACITY, "Aggregate risk-at-stop cap"),
    # ONE RAIL, TWO MESSAGES. `governor.evaluate` refuses the aggregate cap in
    # two places - once when the cap is already breached, and once when the
    # headroom left will not cover a single share - and only the first was
    # matched. Measured 13 August: three refusals in a G1 replay landed in
    # UNCLASSIFIED and rendered as a pseudo-rail named "remaining aggregate risk
    # headroom", splitting one rail across two rows of the same report.
    ("aggregate risk headroom", RefusalFamily.CAPACITY, "Aggregate risk-at-stop cap"),
    # The per-order cap TRIMS a buy since 24 August 2026 rather than refusing it,
    # so "notional above the per-order cap" is no longer emitted anywhere. What
    # survives is the one case a trim cannot rescue: a cap too small to cover a
    # single share. Left mapped rather than deleted because historical journals
    # still carry the old wording, and an unrecognised reason in an old report
    # is the M89 defect - seven refusal messages classified as "not recognised"
    # because the taxonomy had drifted from the strings actually emitted.
    ("notional above the per-order cap", RefusalFamily.CAPACITY, "Per-order notional cap"),
    ("does not cover one share", RefusalFamily.CAPACITY, "Per-order notional cap"),
    ("cash", RefusalFamily.CAPACITY, "Cash floor"),
    ("too small to carry its", RefusalFamily.CANDIDATE, "Cost-to-risk (trade too small)"),
    ("round-trip cost", RefusalFamily.CANDIDATE, "Cost-to-risk (trade too small)"),
    ("correlat", RefusalFamily.CANDIDATE, "Correlated-cluster cap"),
    ("sector", RefusalFamily.CANDIDATE, "Sector concentration cap"),
    ("single-name", RefusalFamily.CANDIDATE, "Single-name concentration cap"),
    ("concentration", RefusalFamily.CANDIDATE, "Concentration cap"),
    ("gap", RefusalFamily.CANDIDATE, "Gap-risk budget"),
    # WAS `"es limit"`, WHICH NEVER MATCHED ANYTHING. PortfolioRiskChecker emits
    # "Portfolio ES 3.50% exceeds limit 3.00%", and the substring before
    # " limit" there is "exceed*s*" - so the pattern written to catch this rail
    # could not catch it, and every portfolio-ES refusal has been unclassified
    # since the module was written. Nothing surfaced it because the rail has
    # never fired in production: the governor trims concentration before the
    # checker refuses it, which is exactly M30's design.
    ("portfolio es", RefusalFamily.CANDIDATE, "Portfolio ES limit"),
    ("below one whole share", RefusalFamily.CANDIDATE, "Sized below one whole share"),
    ("sizing produced zero shares", RefusalFamily.CANDIDATE, "Sizer produced no shares"),
    # The governor's and the risk engine's degenerate guards. None should fire
    # in normal operation, which is precisely why they need names: a rail that
    # fires only when something is wrong is the one whose count must not be
    # swept into a catch-all.
    ("candidate has no measurable risk per share", RefusalFamily.CANDIDATE, "No risk per share"),
    ("proposed size is not positive", RefusalFamily.CANDIDATE, "Proposed size not positive"),
    ("exit quantity must be positive", RefusalFamily.CANDIDATE, "Exit quantity not positive"),
    ("equity is not positive", RefusalFamily.STATE, "Equity not positive"),
    ("kill-switch", RefusalFamily.STATE, "Kill-switch active"),
    ("session phase", RefusalFamily.STATE, "Session phase not eligible"),
    ("market is closed", RefusalFamily.STATE, "Market closed"),
    ("allow list", RefusalFamily.STATE, "Symbol not on the allow list"),
    ("account unavailable", RefusalFamily.STATE, "Account unreadable"),
    ("risk evaluation failed", RefusalFamily.STATE, "Risk evaluation failed"),
    ("stale", RefusalFamily.STATE, "Stale market data"),
    # Both are conditions of the POSITION rather than of the candidate, so STATE.
    #
    # "corporate action pending" is M39's. "position anomaly" is M60's and was
    # never added - so every quarantine refusal has been rendering on the Blotter
    # as "not recognised - see the note below" since 8 August, which is precisely
    # the failure this module exists to prevent, committed against this module.
    ("corporate action pending", RefusalFamily.STATE, "Corporate action pending"),
    ("position anomaly", RefusalFamily.STATE, "Position quarantined"),
    ("broker refused", RefusalFamily.EXECUTION, "Broker refused the order"),
    ("oms rejected at sign-off", RefusalFamily.EXECUTION, "OMS rejected at sign-off"),
    ("insufficient qty", RefusalFamily.EXECUTION, "Broker: insufficient quantity"),
)


def classify(reason: str) -> RefusalFamily:
    """Which family a refusal belongs to.

    An unrecognised reason returns UNCLASSIFIED rather than being swept into
    the largest bucket, and the summary reports those separately. A rail added
    later would otherwise disappear into a catch-all and be counted as
    something it is not - which is the failure this module exists to prevent,
    committed by the module itself.
    """
    return _match(reason)[0]


def rail_of(reason: str) -> str:
    """The stable name of the rail that produced this refusal.

    One rail is one row. Grouping by the reason text instead fragments a single
    cause across every distinct price and percentage it happened to mention.
    """
    return _match(reason)[1]


def _match(reason: str) -> tuple[RefusalFamily, str]:
    text = reason.lower()
    for fragment, family, label in _PATTERNS:
        if fragment in text:
            return family, label
    return RefusalFamily.UNCLASSIFIED, _leading_clause(reason)


def _leading_clause(reason: str) -> str:
    """A readable fallback for a rail this module does not know, with the
    per-instance arithmetic stripped so it still groups."""
    head = reason.split(" (")[0].split(" - ")[0].strip()
    return "".join("N" if character.isdigit() else character for character in head)


@dataclass(frozen=True, slots=True)
class RefusalSummary:
    considered: int
    approved: int
    by_family: dict[RefusalFamily, int]
    by_reason: dict[str, int]
    by_symbol: dict[str, int]
    never_approved: tuple[str, ...]
    unclassified_examples: tuple[str, ...] = field(default=())

    @property
    def refused(self) -> int:
        return self.considered - self.approved

    @property
    def approval_rate(self) -> float | None:
        return self.approved / self.considered if self.considered else None

    def share(self, family: RefusalFamily) -> float | None:
        """What fraction of refusals this family accounts for."""
        return self.by_family.get(family, 0) / self.refused if self.refused else None

    def headline(self) -> str:
        """The one sentence worth putting at the top of a report.

        Leads with the capacity/candidate split because that is the sentence
        that decides what to do: capacity says change the limits, candidate
        says look at the strategy.
        """
        if not self.considered:
            return "No sizing decisions recorded."
        if not self.refused:
            return f"{self.considered} candidate(s) considered, none refused."
        capacity = self.by_family.get(RefusalFamily.CAPACITY, 0)
        candidate = self.by_family.get(RefusalFamily.CANDIDATE, 0)
        return (
            f"{self.considered} candidate(s) considered, {self.approved} approved "
            f"({self.approval_rate:.1%}). Of {self.refused} refusals, "
            f"{capacity} were capacity (the book was full) and {candidate} were the "
            f"candidate failing a test."
        )


def summarise_refusals(rows: list[dict[str, str]]) -> RefusalSummary:
    """Group sizing decisions by what their refusal actually means.

    Takes already-parsed rows rather than a path so the caller decides what
    window to read - a session, a day, the whole file - and so this is testable
    without a filesystem.
    """
    considered = 0
    approved = 0
    families: Counter[RefusalFamily] = Counter()
    reasons: Counter[str] = Counter()
    symbols: Counter[str] = Counter()
    approved_symbols: set[str] = set()
    seen_symbols: set[str] = set()
    unclassified: list[str] = []

    for row in rows:
        considered += 1
        symbol = (row.get("symbol") or "").strip()
        if symbol:
            seen_symbols.add(symbol)
        # The column is written by csv.DictWriter from a bool, so it is the
        # string "True"/"False" rather than a boolean.
        if (row.get("approved") or "").strip().lower() == "true":
            approved += 1
            if symbol:
                approved_symbols.add(symbol)
            continue

        reason = (row.get("reason") or "").strip()
        if not reason:
            continue
        family, rail = _match(reason)
        families[family] += 1
        reasons[rail] += 1
        if symbol:
            symbols[symbol] += 1
        if family is RefusalFamily.UNCLASSIFIED and rail not in unclassified:
            unclassified.append(rail)

    return RefusalSummary(
        considered=considered,
        approved=approved,
        by_family=dict(families.most_common()),
        by_reason=dict(reasons.most_common()),
        by_symbol=dict(symbols.most_common()),
        # Symbols the strategy kept asking for and never once got. These are
        # the ones a capacity cap is silently costing.
        never_approved=tuple(sorted(seen_symbols - approved_symbols)),
        unclassified_examples=tuple(unclassified),
    )


def load_risk_decisions(
    data_dir: str | Path,
    *,
    since: str | None = None,
    market: str | None = None,
    filename: str = RISK_DECISIONS_FILENAME,
) -> list[dict[str, str]]:
    """Sizing decisions from disk, optionally from an ISO timestamp onwards.

    `since` is compared as a string, which works because the column is written
    in ISO-8601 - and is why it is written that way. A missing or unreadable
    file reads as "no decisions" rather than raising: this is an analysis
    layer, and it must never be able to stop a report being produced.

    `market` narrows to one era (M127). This file, like the equity curve and
    the trade ledger, spans the Alpaca/US period and the IBKR/ASX one - and the
    weekly report of 21 August cited *"rejected all 120 candidate orders
    because the book was full"* as this week's ASX behaviour when every one of
    those refusals happened on the other broker, against a book that no longer
    exists. Rows written before the column exists carry no market and are
    excluded by any market filter, which is the safe direction: an
    unattributable refusal should not be reported as this account's.
    """
    path = Path(data_dir) / filename
    if not path.exists():
        return []
    try:
        with path.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
    except OSError:
        logger.exception("Could not read %s", path)
        return []
    if since is not None:
        rows = [row for row in rows if (row.get("timestamp") or "") >= since]
    if market is not None:
        rows = [row for row in rows if (row.get("market") or "") == market]
    return rows


def format_refusal_section(summary: RefusalSummary) -> str:
    """The report block. Markdown, matching the rest of the daily report."""
    lines = ["### Why orders did not happen", "", summary.headline(), ""]
    if not summary.refused:
        return "\n".join(lines)

    lines.append("| Family | Refusals | What it means |")
    lines.append("|---|---|---|")
    for family, count in summary.by_family.items():
        lines.append(f"| {family.value} | {count} | {family.means} |")
    lines.append("")

    lines.append("| Binding rail | Refusals |")
    lines.append("|---|---|")
    for reason, count in list(summary.by_reason.items())[:6]:
        lines.append(f"| {reason} | {count} |")
    lines.append("")

    if summary.never_approved:
        named = ", ".join(summary.never_approved[:12])
        more = (
            f" and {len(summary.never_approved) - 12} more"
            if len(summary.never_approved) > 12
            else ""
        )
        lines.append(
            f"**Asked for and never taken:** {named}{more}. A capacity cap is what these cost."
        )
        lines.append("")

    if summary.unclassified_examples:
        lines.append(
            "**Unclassified refusal reasons** - a rail this summary does not recognise, "
            "so its count is not in any family above: " + "; ".join(summary.unclassified_examples)
        )
        lines.append("")

    return "\n".join(lines)

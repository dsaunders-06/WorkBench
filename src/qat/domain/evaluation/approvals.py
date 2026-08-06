"""What an approval nearly was (M51).

The refusal analysis answers "why did nothing happen". This answers the harder
half: when something DID happen, how close did it come to not happening.

"Approved" is recorded as a single bit, and it hides everything worth knowing.
An entry taken with 88% of the risk budget already spent and nine of ten slots
filled is a different decision from the same entry taken into an empty book,
and the trade ledger cannot tell them apart. Both read `approved`.

Two things this makes visible that nothing else does:

* **Which rail was tightest.** Not which one refused - none did - but which one
  the system came closest to hitting. A rail that is repeatedly at 95% is
  doing work; a rail never above 20% is not binding on anything and may be
  measuring the wrong quantity.
* **How often an order was TRIMMED rather than passed.** The governor resizes
  an order to fit rather than refusing it, so a trim leaves no refusal behind.
  An order cut from 40 shares to 19 was half-refused, and nothing counted it.

Read-only over `risk_decisions.csv`, which the risk engine already writes in
full. No new instrumentation, and no decision changes.
"""

from __future__ import annotations

import ast
import json
import logging
from collections import Counter
from dataclasses import dataclass
from statistics import median

from qat.config import Settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RailPressure:
    """How much of one rail's budget was already spent when an order passed."""

    rail: str
    used: float
    limit: float

    @property
    def utilisation(self) -> float:
        return self.used / self.limit if self.limit else 0.0

    def describe(self) -> str:
        return f"{self.rail} at {self.utilisation:.0%} of its limit"


@dataclass(frozen=True, slots=True)
class ApprovedDecision:
    timestamp: str
    symbol: str
    shares: float
    resized: bool
    pressures: tuple[RailPressure, ...]

    @property
    def tightest(self) -> RailPressure | None:
        return max(self.pressures, key=lambda p: p.utilisation, default=None)


@dataclass(frozen=True, slots=True)
class ApprovalSummary:
    decisions: tuple[ApprovedDecision, ...]
    tightest_counts: dict[str, int]
    median_utilisation: dict[str, float]
    resized_count: int
    unreadable: int

    @property
    def count(self) -> int:
        return len(self.decisions)

    def headline(self) -> str:
        if not self.decisions:
            # "None recorded" and "none I could read" are different statements,
            # and reporting the second as the first is the silent drop this
            # whole module exists to stop.
            if self.unreadable:
                return (
                    f"No readable entry approvals: {self.unreadable} carried rail state "
                    "this summary could not parse."
                )
            return "No entry approvals recorded."
        if self.resized_count == 1:
            trimmed = "1 of them was TRIMMED to fit rather than passed whole"
        elif self.resized_count:
            trimmed = f"{self.resized_count} of them were TRIMMED to fit rather than passed whole"
        else:
            trimmed = "none needed trimming"
        tightest = ", ".join(
            f"{rail} ({count})" for rail, count in list(self.tightest_counts.items())[:3]
        )
        return (
            f"{self.count} entry approval(s), and {trimmed}. "
            f"Tightest rail at the moment of approval: {tightest}."
        )


# value key -> (human name, settings attribute holding the limit, needs equity)
_RAILS: tuple[tuple[str, str, str, bool], ...] = (
    ("aggregate_risk_pct", "Aggregate risk-at-stop", "max_aggregate_risk_at_stop_pct", False),
    ("position_count", "Position count", "max_concurrent_positions", False),
    ("single_name_pct", "Single-name concentration", "max_single_name_concentration_pct", False),
    ("sector_pct", "Sector concentration", "max_sector_concentration_pct", False),
    ("es_975", "Portfolio ES", "portfolio_es_limit_pct", False),
    ("cost_to_risk_pct", "Cost-to-risk", "max_cost_to_risk_pct", False),
    ("gap_loss_at_shock_dollars", "Gap-risk budget", "max_gap_risk_at_shock_pct", True),
    ("held_in_cluster_dollars", "Correlated cluster", "max_correlated_cluster_pct", True),
)


def _parse_inputs(raw: str) -> dict[str, object] | None:
    """The `inputs` column, which is a Python repr rather than JSON.

    Written with `str(dict)`, so it has single quotes and `True`/`None`. JSON is
    tried first anyway - if the writer is ever changed to emit JSON this keeps
    working without a second pass over the file.
    """
    text = (raw or "").strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
    except (ValueError, TypeError):
        try:
            parsed = ast.literal_eval(text)
        except (ValueError, SyntaxError, TypeError, MemoryError):
            return None
    return parsed if isinstance(parsed, dict) else None


def _number(value: object) -> float | None:
    """A recorded figure, or None if it was not measured.

    `null` and 0 are different: a sector concentration of None means no sector
    was known, and treating it as zero would report a rail as comfortable when
    it was simply not evaluated.
    """
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    # CSV columns arrive as strings even when they hold numbers, which is how
    # `final_shares` silently read as zero and reported every trimmed order as
    # "(0)".
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def pressures_for(inputs: dict[str, object], settings: Settings) -> tuple[RailPressure, ...]:
    """How full each rail was at the moment this order was let through.

    The governor figures are PRE-trade: `aggregate_risk_pct` plus
    `headroom_dollars` reconstructs the cap exactly, which is what confirms
    these are "the state the order arrived into" rather than the state it left
    behind. That is the useful reading - it says how much room the system had
    when it said yes.
    """
    governor = inputs.get("governor")
    check = inputs.get("portfolio_check")
    merged: dict[str, object] = {}
    if isinstance(governor, dict):
        merged.update(governor)
    if isinstance(check, dict):
        merged.update(check)
    merged.update({k: v for k, v in inputs.items() if not isinstance(v, dict)})

    equity = _number(merged.get("equity")) or 0.0
    found: list[RailPressure] = []
    for key, name, attribute, needs_equity in _RAILS:
        used = _number(merged.get(key))
        if used is None:
            continue
        limit = float(getattr(settings, attribute))
        if needs_equity:
            if equity <= 0:
                continue
            used = used / equity
        found.append(RailPressure(rail=name, used=used, limit=limit))
    return tuple(found)


def summarise_approvals(rows: list[dict[str, str]], settings: Settings) -> ApprovalSummary:
    """Entry approvals only.

    Exits and de-lever trims are excluded deliberately: they bypass entry sizing
    entirely - the reason column says so - so they have no portfolio check, no
    rails, and no headroom to measure. Counting them here would dilute the
    figure with decisions that were never subject to the caps.
    """
    decisions: list[ApprovedDecision] = []
    unreadable = 0

    for row in rows:
        if (row.get("approved") or "").strip().lower() != "true":
            continue
        reason = (row.get("reason") or "").lower()
        if "exit" in reason or "delever" in reason:
            continue
        inputs = _parse_inputs(row.get("inputs") or "")
        if inputs is None:
            unreadable += 1
            continue
        pressures = pressures_for(inputs, settings)
        if not pressures:
            unreadable += 1
            continue
        decisions.append(
            ApprovedDecision(
                timestamp=(row.get("timestamp") or "").strip(),
                symbol=(row.get("symbol") or "").strip(),
                shares=_number(row.get("final_shares")) or 0.0,
                resized=bool(inputs.get("resized_by_governor")),
                pressures=pressures,
            )
        )

    tightest: Counter[str] = Counter()
    per_rail: dict[str, list[float]] = {}
    for decision in decisions:
        top = decision.tightest
        if top is not None:
            tightest[top.rail] += 1
        for pressure in decision.pressures:
            per_rail.setdefault(pressure.rail, []).append(pressure.utilisation)

    return ApprovalSummary(
        decisions=tuple(decisions),
        tightest_counts=dict(tightest.most_common()),
        median_utilisation={rail: median(values) for rail, values in sorted(per_rail.items())},
        resized_count=sum(1 for d in decisions if d.resized),
        unreadable=unreadable,
    )


def format_approval_section(summary: ApprovalSummary) -> str:
    lines = ["### What the approvals nearly were", "", summary.headline(), ""]
    if not summary.decisions:
        if summary.unreadable:
            lines.append(
                f"_{summary.unreadable} approval(s) carried no readable rail state and are "
                "excluded from the figures above._"
            )
            lines.append("")
        return "\n".join(lines)

    lines.append("| Rail | Median use at approval | Times tightest |")
    lines.append("|---|---|---|")
    for rail, value in sorted(
        summary.median_utilisation.items(),
        key=lambda kv: -kv[1],
    ):
        lines.append(f"| {rail} | {value:.0%} | {summary.tightest_counts.get(rail, 0)} |")
    lines.append("")

    # Named individually because a single order trimmed from 40 shares to 19 is
    # a half-refusal that leaves no refusal behind, and the count alone hides
    # which symbol it happened to.
    trimmed = [d for d in summary.decisions if d.resized]
    if trimmed:
        named = ", ".join(f"{d.symbol} ({d.shares:.0f})" for d in trimmed[:10])
        lines.append(
            f"**Trimmed to fit rather than refused:** {named}. "
            "A resized order leaves no refusal behind, so nothing else counts these."
        )
        lines.append("")

    if summary.unreadable:
        lines.append(
            f"_{summary.unreadable} approval(s) carried no readable rail state and are "
            "excluded from the figures above._"
        )
        lines.append("")

    return "\n".join(lines)

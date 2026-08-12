"""Does the replay bind the same rail the live book did? (W2 G1)

The acceptance gate for the research harness. A harness that cannot reproduce a
day that already happened is not measuring this system, and every number it
produced afterwards would be unfalsifiable.

Three decisions shape this module, each measured rather than assumed:

**The unit is the RAIL, never the reason text.** Cost-rail refusals fragment
across dozens of strings differing only in cents - $138.38, $138.37, $138.42 -
so `refusals.rail_of` is the key. Its own docstring makes the argument: one rail
is one row.

**The unit is (symbol, day), not the decision.** Live evaluates on every poll
and the replay once per bar: the frozen window holds up to 708 decisions in a
day against a replay's one per symbol. A symbol refused all day by the position
limit is one fact, not seventy.

**A day whose rails differ WITHIN it is a PARTIAL agreement, not a miss.** The
cap can bind in the morning and the position limit in the afternoon; the live
set then has two entries and the replay one. The replay cannot see intraday,
and scoring that as failure would tune the gate toward a resolution the daily
data does not have.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date

from qat.domain.evaluation.refusals import rail_of

APPROVED_RAIL = "Approved"


@dataclass(frozen=True, slots=True)
class RailAgreement:
    """One rail's agreement across the window."""

    rail: str
    agreed: int = 0
    live_only: int = 0
    harness_only: int = 0

    @property
    def considered(self) -> int:
        return self.agreed + self.live_only + self.harness_only

    @property
    def agreement_rate(self) -> float:
        return self.agreed / self.considered if self.considered else 0.0


@dataclass(frozen=True, slots=True)
class Verdict:
    """The gate's result, per rail and in summary.

    `partial_days` is reported separately and deliberately: it is neither
    agreement nor failure, and pooling it into either would misstate what the
    daily replay is capable of resolving.
    """

    rails: tuple[RailAgreement, ...] = ()
    exact_days: int = 0
    partial_days: int = 0
    disjoint_days: int = 0
    live_only_days: int = 0
    harness_only_days: int = 0
    excluded: tuple[str, ...] = field(default=())

    @property
    def days_considered(self) -> int:
        return (
            self.exact_days
            + self.partial_days
            + self.disjoint_days
            + self.live_only_days
            + self.harness_only_days
        )


def rails_by_symbol_day(
    rows: Iterable[Mapping[str, str]], exclude: frozenset[str] = frozenset()
) -> dict[tuple[str, date], set[str]]:
    """Collapse decision rows to the set of rails that bound each symbol-day.

    An approval is a rail too - `Approved` - because "the live book let this
    through and the replay refused it" is exactly as much a disagreement as the
    reverse, and dropping approvals would hide half of them.
    """
    out: dict[tuple[str, date], set[str]] = {}
    for row in rows:
        symbol = row["symbol"]
        if symbol in exclude:
            continue
        day = date.fromisoformat(row["timestamp"][:10])
        approved = str(row.get("approved", "")).strip().lower() == "true"
        rail = APPROVED_RAIL if approved else rail_of(row.get("reason", ""))
        out.setdefault((symbol, day), set()).add(rail)
    return out


def compare(
    live: Iterable[Mapping[str, str]],
    harness: Iterable[Mapping[str, str]],
    exclude: frozenset[str] = frozenset(),
) -> Verdict:
    live_rails = rails_by_symbol_day(live, exclude)
    harness_rails = rails_by_symbol_day(harness, exclude)

    tallies: dict[str, dict[str, int]] = {}

    def bump(rail: str, bucket: str) -> None:
        tallies.setdefault(rail, {"agreed": 0, "live_only": 0, "harness_only": 0})[bucket] += 1

    exact = partial = disjoint = live_only_days = harness_only_days = 0

    for key in set(live_rails) | set(harness_rails):
        left = live_rails.get(key)
        right = harness_rails.get(key)
        if left is None:
            harness_only_days += 1
            for rail in right or set():
                bump(rail, "harness_only")
            continue
        if right is None:
            live_only_days += 1
            for rail in left:
                bump(rail, "live_only")
            continue

        for rail in left & right:
            bump(rail, "agreed")
        for rail in left - right:
            bump(rail, "live_only")
        for rail in right - left:
            bump(rail, "harness_only")

        if left == right:
            exact += 1
        elif left & right:
            partial += 1
        else:
            disjoint += 1

    rails = tuple(
        sorted(
            (
                RailAgreement(
                    rail=rail,
                    agreed=counts["agreed"],
                    live_only=counts["live_only"],
                    harness_only=counts["harness_only"],
                )
                for rail, counts in tallies.items()
            ),
            key=lambda r: -r.considered,
        )
    )
    return Verdict(
        rails=rails,
        exact_days=exact,
        partial_days=partial,
        disjoint_days=disjoint,
        live_only_days=live_only_days,
        harness_only_days=harness_only_days,
        excluded=tuple(sorted(exclude)),
    )

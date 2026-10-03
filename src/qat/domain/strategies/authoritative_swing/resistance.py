"""Deterministic historical resistance zones and analytical entry ceilings."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_FLOOR, Context, Decimal, localcontext

from qat.domain.strategies.authoritative_swing.model import (
    AdjustmentStatus,
    DataQuality,
    DecisionStatus,
    FinalBar,
    PatternCandidate,
)
from qat.domain.strategies.authoritative_swing.numeric import NUMERIC_POLICY


@dataclass(frozen=True, slots=True)
class ResistanceMember:
    session: date
    digest: str
    price: Decimal
    ordinal: int

    @property
    def identity(self) -> tuple[date, str]:
        return self.session, self.digest


@dataclass(frozen=True, slots=True)
class ResistanceZone:
    lower: Decimal
    upper: Decimal
    members: tuple[ResistanceMember, ...]

    @property
    def member_identities(self) -> tuple[tuple[date, str], ...]:
        return tuple(member.identity for member in self.members)


@dataclass(frozen=True, slots=True)
class ResistanceDecision:
    status: DecisionStatus
    limit_price: Decimal | None
    zones: tuple[ResistanceZone, ...]
    relevant_zone: ResistanceZone | None
    reason: str | None = None


def _context() -> Context:
    return Context(prec=NUMERIC_POLICY.precision, rounding=NUMERIC_POLICY.rounding)


def _median(members: Sequence[ResistanceMember]) -> Decimal:
    middle = len(members) // 2
    if len(members) % 2:
        return members[middle].price
    with localcontext(_context()):
        return (members[middle - 1].price + members[middle].price) / Decimal(2)


def _zone_key(zone: ResistanceZone) -> tuple[Decimal, Decimal, tuple[tuple[date, str], ...]]:
    return zone.lower, zone.upper, zone.member_identities


def _swing_highs(bars: Sequence[FinalBar]) -> tuple[ResistanceMember, ...]:
    ordered = tuple(sorted(bars, key=lambda bar: (bar.session, bar.digest)))
    if any(
        left.session == right.session for left, right in zip(ordered, ordered[1:], strict=False)
    ):
        raise ValueError("resistance history contains duplicate sessions")
    highs: list[ResistanceMember] = []
    for index in range(5, len(ordered) - 5):
        price = ordered[index].adjusted.high
        neighbors = (*ordered[index - 5 : index], *ordered[index + 1 : index + 6])
        if all(price > bar.adjusted.high for bar in neighbors):
            highs.append(
                ResistanceMember(
                    ordered[index].session,
                    ordered[index].digest,
                    price,
                    index,
                )
            )
    return tuple(sorted(highs, key=lambda member: (member.price, member.identity)))


def find_resistance_zones(bars: Sequence[FinalBar]) -> tuple[ResistanceZone, ...]:
    """Enumerate every qualifying contiguous high group and keep maximal sets."""

    highs = _swing_highs(bars)
    qualifying: dict[frozenset[tuple[date, str]], ResistanceZone] = {}
    for start in range(len(highs)):
        for stop in range(start + 2, len(highs) + 1):
            members = highs[start:stop]
            median = _median(members)
            with localcontext(_context()):
                within_band = all(
                    abs(member.price - median) / median <= Decimal("0.01") for member in members
                )
            if not within_band:
                continue
            if (
                max(member.ordinal for member in members)
                - min(member.ordinal for member in members)
                < 20
            ):
                continue
            member_set = frozenset(member.identity for member in members)
            qualifying[member_set] = ResistanceZone(
                lower=min(member.price for member in members),
                upper=max(member.price for member in members),
                members=members,
            )

    retained = [
        zone
        for member_set, zone in qualifying.items()
        if not any(member_set < other_set for other_set in qualifying)
    ]
    return tuple(sorted(retained, key=_zone_key))


def nearest_relevant_resistance(
    entry: Decimal, zones: Sequence[ResistanceZone]
) -> ResistanceZone | None:
    """Choose the nearest zone whose upper edge has not been passed."""

    relevant = tuple(zone for zone in zones if zone.upper >= entry)
    if not relevant:
        return None
    return min(
        relevant,
        key=lambda zone: (max(entry, zone.lower), *_zone_key(zone)),
    )


def _three_year_cutoff(signal_session: date) -> date:
    try:
        return signal_session.replace(year=signal_session.year - 3)
    except ValueError:
        return signal_session.replace(year=signal_session.year - 3, day=28)


def _valid_resistance_bar(bar: FinalBar) -> bool:
    values = bar.adjusted
    finite = all(
        value.is_finite() for value in (values.open, values.high, values.low, values.close)
    )
    geometry = (
        values.low <= min(values.open, values.close)
        and values.high >= max(values.open, values.close)
        and values.high >= values.low
    )
    return (
        bar.finalized
        and bar.quality is DataQuality.VERIFIED
        and bar.adjustment is AdjustmentStatus.SPLIT_NORMALIZED
        and finite
        and geometry
    )


def _strict_ceiling(barrier: Decimal, stop: Decimal) -> Decimal:
    with localcontext(_context()):
        boundary = (barrier + Decimal(2) * stop) / Decimal(3)
        quantum = NUMERIC_POLICY.analytical_quantum
        floored = boundary.quantize(quantum, rounding=ROUND_FLOOR)
        if floored == boundary:
            floored -= quantum
        return floored


def analytical_entry_ceiling_for(
    candidate: PatternCandidate, history: Sequence[FinalBar]
) -> ResistanceDecision:
    """Apply three-year resistance in analytical basis before raw conversion."""

    cutoff = _three_year_cutoff(candidate.signal_session)
    ordered = tuple(sorted(history, key=lambda bar: (bar.session, bar.digest)))
    prior = tuple(bar for bar in ordered if cutoff <= bar.session < candidate.signal_session)
    if (
        not prior
        or prior[0].session > cutoff
        or candidate.signal_session - prior[-1].session > timedelta(days=7)
    ):
        return ResistanceDecision(
            DecisionStatus.ABSTAIN,
            None,
            (),
            None,
            "fewer than three calendar years of resistance history",
        )
    if any(not _valid_resistance_bar(bar) for bar in prior):
        return ResistanceDecision(
            DecisionStatus.ABSTAIN,
            None,
            (),
            None,
            "resistance history is unadjusted, malformed, synthetic, or unverifiable",
        )
    if candidate.analytical_signal_close <= candidate.analytical_invalidation:
        return ResistanceDecision(
            DecisionStatus.REJECTED,
            None,
            (),
            None,
            "candidate entry does not stand above structural invalidation",
        )

    try:
        zones = find_resistance_zones(prior)
    except ValueError as error:
        return ResistanceDecision(DecisionStatus.ABSTAIN, None, (), None, str(error))
    entry = candidate.analytical_signal_close
    stop = candidate.analytical_invalidation
    relevant = nearest_relevant_resistance(entry, zones)
    if relevant is None:
        return ResistanceDecision(DecisionStatus.QUALIFIED, entry, zones, None)
    if relevant.lower <= entry <= relevant.upper:
        return ResistanceDecision(
            DecisionStatus.REJECTED,
            None,
            zones,
            relevant,
            "signal close lies inside a resistance zone",
        )

    two_r = entry + Decimal(2) * (entry - stop)
    if two_r < relevant.lower:
        return ResistanceDecision(DecisionStatus.QUALIFIED, entry, zones, relevant)
    limit = min(entry, _strict_ceiling(relevant.lower, stop))
    if limit <= stop:
        return ResistanceDecision(
            DecisionStatus.REJECTED,
            None,
            zones,
            relevant,
            "no positive-risk entry can clear resistance through 2R",
        )
    return ResistanceDecision(DecisionStatus.QUALIFIED, limit, zones, relevant)

"""Chronological promotion windows and exact outcome-tail boundaries.

This module operates on catalog metadata and a signed calendar. It never opens
sealed observations from a later partition.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, timedelta
from decimal import Decimal
from enum import StrEnum

from qat.domain.backtester.swing_dataset import (
    DatasetCatalog,
    DatasetIntegrityError,
    DatasetShardManifest,
    DatasetTier,
    OfficialSessionCalendar,
)


class ValidationPartition(StrEnum):
    DEVELOPMENT = "development"
    VALIDATION = "validation"
    HOLDOUT = "holdout"


PARTITION_ORDER = (
    ValidationPartition.DEVELOPMENT,
    ValidationPartition.VALIDATION,
    ValidationPartition.HOLDOUT,
)


@dataclass(frozen=True, slots=True)
class BoundarySessions:
    calendar: OfficialSessionCalendar
    t0: date
    t1: date
    t10: date
    t11: date
    t64: date
    t65: date | None
    tail_sessions: tuple[date, ...]


@dataclass(frozen=True, slots=True)
class PartitionWindow:
    partition: ValidationPartition
    signal_months: tuple[str, ...]
    signal_sessions: tuple[date, ...]
    tail_sessions: tuple[date, ...]
    interstitial_sessions: tuple[date, ...]
    boundaries: BoundarySessions

    @property
    def first_signal_session(self) -> date:
        return self.signal_sessions[0]

    def moving_blocks(self, length: int) -> tuple[tuple[date, ...], ...]:
        """Return blocks wholly contained in this partition's entry window."""
        if length <= 0:
            raise ValueError("moving block length must be positive")
        return tuple(
            self.signal_sessions[index : index + length]
            for index in range(len(self.signal_sessions) - length + 1)
        )


@dataclass(frozen=True, slots=True)
class ValidationPlan:
    catalog_id: str
    partitions: tuple[PartitionWindow, PartitionWindow, PartitionWindow]
    signal_history_calendar_years: Decimal


@dataclass(frozen=True, slots=True)
class TerminalValuation:
    position_id: str
    symbol: str
    quantity: int
    session: date
    unit_price: Decimal
    total_value: Decimal
    reason: str
    source_event_id: str


def _validated_sessions(calendar: OfficialSessionCalendar) -> tuple[date, ...]:
    rows = calendar.rows
    if not rows or not calendar.source_hash:
        raise DatasetIntegrityError("signed official calendar is missing")
    if any(not row.finalized for row in rows):
        raise DatasetIntegrityError("official calendar has an unfinalized civil date")
    for previous, current in zip(rows, rows[1:], strict=False):
        if current.calendar_date != previous.calendar_date + timedelta(days=1):
            raise DatasetIntegrityError("official calendar is missing a civil date")
    projection = tuple(row.calendar_date for row in rows if row.is_tradable)
    if projection != calendar.official_sessions:
        raise DatasetIntegrityError("official session projection disagrees with signed civil dates")
    return projection


def _boundaries_from_sessions(
    final_entry_fill: date,
    calendar: OfficialSessionCalendar,
    sessions: tuple[date, ...],
) -> BoundarySessions:
    try:
        ordinal = sessions.index(final_entry_fill)
    except ValueError as exc:
        raise DatasetIntegrityError("T1 must be a signed official session") from exc
    if ordinal == 0 or ordinal + 63 >= len(sessions):
        raise DatasetIntegrityError("T1 lacks T0 or a complete 63-session outcome tail")
    return BoundarySessions(
        calendar=calendar,
        t0=sessions[ordinal - 1],
        t1=final_entry_fill,
        t10=sessions[ordinal + 9],
        t11=sessions[ordinal + 10],
        t64=sessions[ordinal + 63],
        t65=sessions[ordinal + 64] if ordinal + 64 < len(sessions) else None,
        tail_sessions=sessions[ordinal + 1 : ordinal + 64],
    )


def boundaries_for(final_entry_fill: date, calendar: OfficialSessionCalendar) -> BoundarySessions:
    """Resolve named boundaries using only the complete signed calendar."""
    return _boundaries_from_sessions(final_entry_fill, calendar, _validated_sessions(calendar))


def _month_number(month: str) -> int:
    try:
        year = int(month[:4])
        number = int(month[5:7])
        if len(month) != 7 or month[4] != "-" or not 1 <= number <= 12 or year < 1:
            raise ValueError
    except ValueError as exc:
        raise DatasetIntegrityError(f"invalid signal month: {month}") from exc
    return year * 12 + number - 1


def _month_bounds(month: str) -> tuple[date, date]:
    ordinal = _month_number(month)
    year, zero_month = divmod(ordinal, 12)
    first = date(year, zero_month + 1, 1)
    next_year, next_zero_month = divmod(ordinal + 1, 12)
    last = date(next_year, next_zero_month + 1, 1) - timedelta(days=1)
    return first, last


def _shard(
    catalog: DatasetCatalog, partition: ValidationPartition, kind: str
) -> DatasetShardManifest:
    matches = tuple(
        shard
        for shard in catalog.shards.values()
        if shard.partition == partition.value and shard.shard_kind == kind
    )
    if len(matches) != 1:
        raise DatasetIntegrityError(f"{partition.value} requires exactly one {kind} shard")
    return matches[0]


def _signal_months(shard: DatasetShardManifest) -> tuple[str, ...]:
    months = shard.signal_months
    if not months:
        raise DatasetIntegrityError("signal shard has no complete signal months")
    ordinals = tuple(_month_number(month) for month in months)
    if any(
        current != previous + 1 for previous, current in zip(ordinals, ordinals[1:], strict=False)
    ):
        raise DatasetIntegrityError("signal months must be complete and consecutive")
    return months


def _check_initial_allocation(windows: tuple[PartitionWindow, ...]) -> None:
    counts = tuple(len(window.signal_months) for window in windows)
    total = sum(counts)
    if total < 120:
        raise DatasetIntegrityError("ten complete signal years are required after tails")
    if counts[2] < 36:
        raise DatasetIntegrityError("holdout requires at least 36 complete signal months")
    if any(
        abs(count * 100 - target * total) > 100
        for count, target in zip(counts, (50, 20, 30), strict=True)
    ):
        raise DatasetIntegrityError("initial complete-month allocation must approximate 50/20/30")


def _check_forward_extension(plan: ValidationPlan, previous: ValidationPlan) -> None:
    if plan.catalog_id != previous.catalog_id:
        raise DatasetIntegrityError("holdout extension changed the catalog identity")
    for current, prior in zip(plan.partitions[:2], previous.partitions[:2], strict=True):
        if (
            current.signal_months != prior.signal_months
            or current.boundaries.t64 != prior.boundaries.t64
        ):
            raise DatasetIntegrityError("holdout extension changed development or validation")
    current_holdout, previous_holdout = plan.partitions[2], previous.partitions[2]
    if (
        current_holdout.first_signal_session != previous_holdout.first_signal_session
        or current_holdout.signal_months[: len(previous_holdout.signal_months)]
        != previous_holdout.signal_months
        or current_holdout.boundaries.t64 < previous_holdout.boundaries.t64
    ):
        raise DatasetIntegrityError("holdout extension must be forward-only")


def build_validation_plan(
    catalog: DatasetCatalog,
    calendar: OfficialSessionCalendar,
    *,
    previous_plan: ValidationPlan | None = None,
) -> ValidationPlan:
    """Create isolated complete-month signal windows and physical tails."""
    if catalog.tier is not DatasetTier.PROMOTION_POINT_IN_TIME:
        raise DatasetIntegrityError("promotion validation requires a point-in-time catalog")
    sessions = _validated_sessions(calendar)
    if (
        calendar.rows[0].calendar_date > catalog.first_session
        or calendar.rows[-1].calendar_date < catalog.last_session
    ):
        raise DatasetIntegrityError("signed calendar does not cover the catalog's civil dates")

    windows: list[PartitionWindow] = []
    previous_t64: date | None = None
    for partition in PARTITION_ORDER:
        signal_shard = _shard(catalog, partition, "signal")
        tail_shard = _shard(catalog, partition, "tail")
        months = _signal_months(signal_shard)
        first_civil, _ = _month_bounds(months[0])
        _, last_civil = _month_bounds(months[-1])
        if (
            first_civil < calendar.rows[0].calendar_date
            or last_civil > calendar.rows[-1].calendar_date
        ):
            raise DatasetIntegrityError("a signal month lacks a complete civil calendar")
        signal_sessions = tuple(
            session for session in sessions if first_civil <= session <= last_civil
        )
        if not signal_sessions:
            raise DatasetIntegrityError("complete signal months contain no official sessions")
        if (
            signal_shard.first_session > signal_sessions[0]
            or signal_shard.last_session != signal_sessions[-1]
        ):
            raise DatasetIntegrityError("signal shard does not cover complete entry-fill months")
        boundaries = _boundaries_from_sessions(signal_sessions[-1], calendar, sessions)
        if (
            tail_shard.first_session != boundaries.tail_sessions[0]
            or tail_shard.last_session != boundaries.t64
        ):
            raise DatasetIntegrityError("tail shard does not cover T2 through T64")
        for shard in (signal_shard, tail_shard):
            for name, expected in (("T1", boundaries.t1), ("T64", boundaries.t64)):
                if name in shard.boundary_ids and shard.boundary_ids[name] != expected:
                    raise DatasetIntegrityError(
                        f"{shard.shard_id} has an incorrect {name} boundary"
                    )
        if previous_t64 is not None and signal_sessions[0] <= previous_t64:
            raise DatasetIntegrityError("a signal window overlaps a previous outcome tail")
        if previous_t64 is not None:
            windows[-1] = replace(
                windows[-1],
                interstitial_sessions=tuple(
                    day for day in sessions if previous_t64 < day < signal_sessions[0]
                ),
            )
        windows.append(
            PartitionWindow(
                partition,
                months,
                signal_sessions,
                boundaries.tail_sessions,
                (),
                boundaries,
            )
        )
        previous_t64 = boundaries.t64

    partition_windows = (windows[0], windows[1], windows[2])
    plan = ValidationPlan(
        catalog.dataset_id,
        partition_windows,
        Decimal(sum(len(window.signal_months) for window in windows)) / Decimal(12),
    )
    if previous_plan is None:
        _check_initial_allocation(partition_windows)
    else:
        _check_forward_extension(plan, previous_plan)
        if len(partition_windows[2].signal_months) < 36:
            raise DatasetIntegrityError("holdout requires at least 36 complete signal months")
    return plan


def attribute_partition(entry_session: date, plan: ValidationPlan) -> ValidationPartition | None:
    """Assign an actual entry fill; tail and interstitial rows have no owner."""
    for window in plan.partitions:
        if entry_session in window.signal_sessions:
            return window.partition
    return None


def may_emit_instruction(session: date, boundaries: BoundarySessions | PartitionWindow) -> bool:
    """An instruction is eligible only when its next official fill is at most T1."""
    if isinstance(boundaries, PartitionWindow):
        if session not in boundaries.signal_sessions:
            return False
        boundary = boundaries.boundaries
    else:
        boundary = boundaries
    return session in boundary.calendar.official_sessions and session <= boundary.t0


def apply_terminal_valuation(
    *,
    position_id: str,
    symbol: str,
    quantity: int,
    session: date,
    boundaries: BoundarySessions,
    source_event_id: str,
    documented_consideration: Decimal | None,
    already_valued: bool = False,
) -> TerminalValuation | None:
    """Record one conservative valuation for a position still untradeable at T64."""
    if session != boundaries.t64:
        raise ValueError("terminal valuation is permitted only at T64")
    if already_valued:
        return None
    if not position_id or not symbol or not source_event_id or quantity <= 0:
        raise ValueError("terminal valuation requires an identified open position and event")
    price = documented_consideration if documented_consideration is not None else Decimal(0)
    if not price.is_finite() or price < 0:
        raise ValueError("documented consideration must be finite and nonnegative")
    return TerminalValuation(
        position_id,
        symbol,
        quantity,
        session,
        price,
        price * Decimal(quantity),
        "terminal_consideration" if documented_consideration is not None else "terminal_zero",
        source_event_id,
    )

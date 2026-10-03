"""Exact signal-window, tail, and terminal boundary contracts."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from qat.domain.backtester.swing_dataset import (
    DatasetCatalog,
    DatasetIntegrityError,
    DatasetShardManifest,
    DatasetTier,
    OfficialCalendarRow,
    OfficialSessionCalendar,
    SessionKind,
)
from qat.domain.backtester.swing_validation import (
    ValidationPartition,
    apply_terminal_valuation,
    attribute_partition,
    boundaries_for,
    build_validation_plan,
    may_emit_instruction,
)


def _calendar(first: date, last: date, *, closure: date | None = None) -> OfficialSessionCalendar:
    rows: list[OfficialCalendarRow] = []
    sessions: list[date] = []
    current = first
    while current <= last:
        tradable = current.weekday() < 5 and current != closure
        kind = SessionKind.FULL if tradable else SessionKind.AD_HOC_CLOSED
        rows.append(
            OfficialCalendarRow(
                current,
                kind,
                None,
                None,
                "signed-fixture",
                "v1",
                None,
                "signed session" if tradable else "closed",
                datetime(2009, 1, 1, tzinfo=UTC),
                f"row-{current.isoformat()}",
                True,
            )
        )
        if tradable:
            sessions.append(current)
        current += timedelta(days=1)
    return OfficialSessionCalendar(tuple(rows), tuple(sessions), "signed-fixture-hash")


def _months(year: int, month: int, count: int) -> tuple[str, ...]:
    months = []
    for offset in range(count):
        year_number, zero_month = divmod(year * 12 + month - 1 + offset, 12)
        months.append(f"{year_number:04d}-{zero_month + 1:02d}")
    return tuple(months)


def _catalog(
    calendar: OfficialSessionCalendar,
    *,
    holdout_months: int = 36,
    validation_start: tuple[int, int] = (2015, 4),
    holdout_start: tuple[int, int] = (2017, 7),
) -> DatasetCatalog:
    months = {
        ValidationPartition.DEVELOPMENT: _months(2010, 1, 60),
        ValidationPartition.VALIDATION: _months(*validation_start, 24),
        ValidationPartition.HOLDOUT: _months(*holdout_start, holdout_months),
    }
    shards: dict[str, DatasetShardManifest] = {}
    for partition, signal_months in months.items():
        signal_days = tuple(
            day for day in calendar.official_sessions if day.strftime("%Y-%m") in signal_months
        )
        t1 = signal_days[-1]
        ordinal = calendar.official_sessions.index(t1)
        tail = calendar.official_sessions[ordinal + 1 : ordinal + 64]
        assert len(tail) == 63
        shards[f"{partition.value}-signal"] = DatasetShardManifest(
            f"{partition.value}-signal",
            partition.value,
            signal_days[0],
            t1,
            {},
            "fixture",
            "signal",
            signal_months,
            {"T1": t1},
        )
        shards[f"{partition.value}-tail"] = DatasetShardManifest(
            f"{partition.value}-tail",
            partition.value,
            tail[0],
            tail[-1],
            {},
            "fixture",
            "tail",
            (),
            {"T1": t1, "T64": tail[-1]},
        )
    return DatasetCatalog(
        "phase2-swing-dataset-v1",
        "fixture-dataset",
        DatasetTier.PROMOTION_POINT_IN_TIME,
        "fixture",
        "split_only",
        "AUD",
        calendar.rows[0].calendar_date,
        calendar.rows[-1].calendar_date,
        True,
        "accumulation_total_return",
        None,
        shards,
        "fixture-signature",
        (),
    )


def test_named_boundaries_use_only_signed_official_sessions() -> None:
    calendar = _calendar(date(2020, 12, 1), date(2021, 5, 31), closure=date(2021, 1, 1))
    t1 = date(2020, 12, 31)
    boundary = boundaries_for(t1, calendar)
    ordinal = calendar.official_sessions.index(t1)

    assert boundary.t0 == calendar.official_sessions[ordinal - 1]
    assert boundary.t10 == calendar.official_sessions[ordinal + 9]
    assert boundary.t11 == calendar.official_sessions[ordinal + 10]
    assert boundary.t64 == calendar.official_sessions[ordinal + 63]
    assert boundary.t65 == calendar.official_sessions[ordinal + 64]
    assert len(boundary.tail_sessions) == 63
    assert date(2021, 1, 1) not in boundary.tail_sessions
    assert not may_emit_instruction(t1, boundary)
    assert may_emit_instruction(boundary.t0, boundary)


def test_t65_is_optional_when_the_signed_calendar_ends_at_t64() -> None:
    long_calendar = _calendar(date(2020, 12, 1), date(2021, 5, 31))
    t64 = boundaries_for(date(2020, 12, 31), long_calendar).t64
    calendar = _calendar(date(2020, 12, 1), t64)

    boundary = boundaries_for(date(2020, 12, 31), calendar)

    assert boundary.t64 == t64
    assert boundary.t65 is None


def test_missing_civil_calendar_row_invalidates_boundary() -> None:
    calendar = _calendar(date(2020, 12, 1), date(2021, 5, 31))
    missing = date(2021, 1, 4)
    damaged = replace(
        calendar,
        rows=tuple(row for row in calendar.rows if row.calendar_date != missing),
        official_sessions=tuple(day for day in calendar.official_sessions if day != missing),
    )
    with pytest.raises(DatasetIntegrityError, match="civil date"):
        boundaries_for(date(2020, 12, 31), damaged)


def test_complete_month_plan_excludes_tails_and_attributes_by_entry_fill() -> None:
    calendar = _calendar(date(2010, 1, 1), date(2020, 10, 31))
    plan = build_validation_plan(_catalog(calendar), calendar)
    development, validation, holdout = plan.partitions

    assert tuple(len(window.signal_months) for window in plan.partitions) == (60, 24, 36)
    assert plan.signal_history_calendar_years == Decimal("10")
    assert all(len(window.tail_sessions) == 63 for window in plan.partitions)
    assert holdout.first_signal_session.year == 2017
    assert attribute_partition(development.boundaries.t1, plan) is ValidationPartition.DEVELOPMENT
    assert attribute_partition(development.boundaries.t64, plan) is None
    assert attribute_partition(validation.boundaries.t1, plan) is ValidationPartition.VALIDATION
    assert attribute_partition(holdout.boundaries.t1, plan) is ValidationPartition.HOLDOUT
    assert not may_emit_instruction(development.boundaries.t1, development)
    assert may_emit_instruction(development.boundaries.t0, development)
    assert all(day not in development.signal_sessions for day in development.tail_sessions)
    assert all(day not in validation.signal_sessions for day in development.interstitial_sessions)
    assert all(
        set(block).isdisjoint(development.tail_sessions) for block in development.moving_blocks(10)
    )


def test_tail_and_interstitial_sessions_never_emit_or_own_entries() -> None:
    calendar = _calendar(date(2010, 1, 1), date(2020, 11, 30))
    plan = build_validation_plan(
        _catalog(
            calendar,
            validation_start=(2015, 5),
            holdout_start=(2017, 8),
        ),
        calendar,
    )
    development, validation, _ = plan.partitions
    assert development.interstitial_sessions
    assert validation.interstitial_sessions
    for window in (development, validation):
        for session in (window.tail_sessions[0], window.tail_sessions[-1]):
            assert attribute_partition(session, plan) is None
            assert not may_emit_instruction(session, window)
        for session in window.interstitial_sessions:
            assert attribute_partition(session, plan) is None
            assert not may_emit_instruction(session, window)


def test_incomplete_outcome_tail_invalidates_the_catalog() -> None:
    calendar = _calendar(date(2010, 1, 1), date(2020, 10, 31))
    catalog = _catalog(calendar)
    shards = dict(catalog.shards)
    tail = shards["development-tail"]
    shards["development-tail"] = replace(tail, last_session=tail.last_session - timedelta(days=1))

    with pytest.raises(DatasetIntegrityError, match="tail shard"):
        build_validation_plan(replace(catalog, shards=shards), calendar)


def test_short_or_partial_month_catalog_cannot_be_promoted() -> None:
    calendar = _calendar(date(2010, 1, 1), date(2020, 10, 31))
    catalog = _catalog(calendar)
    short = dict(catalog.shards)
    holdout = short["holdout-signal"]
    short["holdout-signal"] = replace(holdout, signal_months=holdout.signal_months[:-1])
    with pytest.raises(DatasetIntegrityError, match="complete|36|signal"):
        build_validation_plan(replace(catalog, shards=short), calendar)

    partial = dict(catalog.shards)
    development = partial["development-signal"]
    partial["development-signal"] = replace(development, first_session=date(2010, 1, 15))
    with pytest.raises(DatasetIntegrityError, match="complete"):
        build_validation_plan(replace(catalog, shards=partial), calendar)


def test_forward_only_holdout_extension_keeps_earlier_starts() -> None:
    original_calendar = _calendar(date(2010, 1, 1), date(2020, 10, 31))
    original = build_validation_plan(_catalog(original_calendar), original_calendar)
    extended_calendar = _calendar(date(2010, 1, 1), date(2021, 10, 31))
    extended = build_validation_plan(
        _catalog(extended_calendar, holdout_months=48),
        extended_calendar,
        previous_plan=original,
    )
    assert tuple(window.first_signal_session for window in extended.partitions) == tuple(
        window.first_signal_session for window in original.partitions
    )
    assert extended.partitions[-1].signal_months[:36] == original.partitions[-1].signal_months
    assert extended.partitions[-1].boundaries.t64 > original.partitions[-1].boundaries.t64


def test_terminal_valuation_is_single_and_only_at_t64() -> None:
    calendar = _calendar(date(2020, 12, 1), date(2021, 5, 31))
    boundary = boundaries_for(date(2020, 12, 31), calendar)
    terminal = apply_terminal_valuation(
        position_id="position-1",
        symbol="AAA.AX",
        quantity=5,
        session=boundary.t64,
        boundaries=boundary,
        source_event_id="halt-1",
        documented_consideration=None,
    )
    assert terminal is not None
    assert terminal.unit_price == Decimal(0)
    assert terminal.total_value == Decimal(0)
    assert terminal.reason == "terminal_zero"
    proceeds = apply_terminal_valuation(
        position_id="position-2",
        symbol="BBB.AX",
        quantity=5,
        session=boundary.t64,
        boundaries=boundary,
        source_event_id="delisting-1",
        documented_consideration=Decimal("1.25"),
    )
    assert proceeds is not None
    assert proceeds.total_value == Decimal("6.25")
    assert proceeds.reason == "terminal_consideration"
    assert (
        apply_terminal_valuation(
            position_id="position-1",
            symbol="AAA.AX",
            quantity=5,
            session=boundary.t64,
            boundaries=boundary,
            source_event_id="halt-1",
            documented_consideration=None,
            already_valued=True,
        )
        is None
    )
    with pytest.raises(ValueError, match="T64"):
        apply_terminal_valuation(
            position_id="position-1",
            symbol="AAA.AX",
            quantity=5,
            session=boundary.t10,
            boundaries=boundary,
            source_event_id="halt-1",
            documented_consideration=None,
        )

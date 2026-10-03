"""Support-matched, field-limited corporate-event incidence fixtures."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal

import pytest

from qat.domain.backtester.swing_reference import (
    PromotionStatus,
    ReferenceEvent,
    ReferenceObservation,
    ReferenceView,
    StrategyExposure,
    build_incidence_windows,
    calibrate_terminal_incidence,
    merge_buckets,
)


def _sessions(first: date, last: date) -> tuple[date, ...]:
    sessions = []
    current = first
    while current <= last:
        if current.weekday() < 5:
            sessions.append(current)
        current += timedelta(days=1)
    return tuple(sessions)


def _view(*, issuers: int = 100, years: int = 5, event_count: int = 8) -> ReferenceView:
    sessions = _sessions(date(2010, 1, 1), date(2021, 12, 31))
    observations = []
    events = []
    for issuer in range(issuers):
        for year in range(years):
            start = next(day for day in sessions if day.year == 2010 + year)
            observations.append(
                ReferenceObservation(
                    issuer_id=f"issuer-{issuer}",
                    session=start,
                    market_cap=Decimal(100 + issuer % 4 * 100),
                    price=Decimal("2"),
                    traded_value=Decimal(1000 + issuer % 2 * 1000),
                    ordinary_equity=True,
                    member_at_start=issuer % 2 == 0,
                )
            )
            if issuer < event_count and year == 0:
                events.append(
                    ReferenceEvent(
                        f"event-{issuer}",
                        f"issuer-{issuer}",
                        sessions[sessions.index(start) + 5],
                        "administration",
                    )
                )
    exposures = tuple(
        StrategyExposure(Decimal(cap), Decimal("2"), Decimal(liquidity), 1)
        for cap in (100, 200, 300, 400)
        for liquidity in (1000, 2000)
    )
    return ReferenceView(
        official_sessions=sessions,
        holdout_start=date(2020, 1, 1),
        observations=tuple(observations),
        events=tuple(events),
        strategy_exposures=exposures,
    )


def test_event_date_deterioration_does_not_remove_start_window() -> None:
    view = _view()
    first = view.observations[0]
    deteriorated = replace(
        first,
        session=view.official_sessions[view.official_sessions.index(first.session) + 2],
        traded_value=Decimal("1"),
    )
    view = replace(view, observations=view.observations + (deteriorated,))

    windows = build_incidence_windows(view)

    assert next(
        window
        for window in windows
        if window.issuer_id == first.issuer_id and window.start == first.session
    ).event_within_ten_sessions
    assert all(window.start != deteriorated.session for window in windows)


def test_one_onset_counts_each_distinct_overlapping_exposure_start() -> None:
    view = _view(event_count=0)
    first = view.observations[0]
    ordinal = view.official_sessions.index(first.session)
    starts = tuple(
        replace(first, session=view.official_sessions[ordinal + offset]) for offset in (1, 2)
    )
    event = ReferenceEvent(
        "overlap-event", first.issuer_id, view.official_sessions[ordinal + 5], "administration"
    )
    windows = build_incidence_windows(
        replace(view, observations=view.observations + starts, events=(event,))
    )
    marked = [
        window
        for window in windows
        if window.issuer_id == first.issuer_id
        and window.start in {first.session, *(item.session for item in starts)}
    ]
    assert len(marked) == 3
    assert all(window.event_within_ten_sessions for window in marked)


def test_holdout_crossing_window_and_outside_support_are_excluded() -> None:
    view = _view()
    last_start = max(day for day in view.official_sessions if day < view.holdout_start)
    crossing = replace(view.observations[0], issuer_id="crossing", session=last_start)
    microcap = replace(view.observations[0], issuer_id="microcap", market_cap=Decimal("1"))
    view = replace(view, observations=view.observations + (crossing, microcap))

    windows = build_incidence_windows(view)

    assert not any(window.issuer_id in {"crossing", "microcap"} for window in windows)


def test_bucket_merge_uses_exposure_only_and_retains_former_members() -> None:
    view = _view()
    windows = build_incidence_windows(view)
    first_merge = merge_buckets(windows, min_issuer_years=500, min_issuers=100)
    changed_events = tuple(replace(event, category="short_halt") for event in view.events)
    changed = build_incidence_windows(replace(view, events=changed_events))

    assert first_merge == merge_buckets(changed, min_issuer_years=500, min_issuers=100)
    assert any(not window.member_at_start for window in windows)
    assert len(set(first_merge.values())) == 1


def test_clustered_and_exact_bounds_both_contribute_to_primary_bound() -> None:
    result = calibrate_terminal_incidence(_view(), bootstrap_draws=199, seed=41)

    assert result.status is PromotionStatus.PASS
    assert result.primary_bound == max(result.clustered_upper, result.landmark_exact_upper)
    assert result.primary_bound >= Decimal(0)
    assert result.stressed_bound >= result.primary_bound


def test_under_supported_reference_stops_calibration_and_duration_advice() -> None:
    result = calibrate_terminal_incidence(_view(issuers=20, years=5), bootstrap_draws=99)

    assert result.status is PromotionStatus.INCIDENCE_DATA_INSUFFICIENT
    assert result.recommended_holdout_months is None
    assert result.primary_bound is None


def test_vendor_omission_is_integrity_error_not_a_zero_event() -> None:
    view = _view()
    omission = ReferenceEvent("missing", "issuer-0", view.official_sessions[6], "vendor_omission")
    with pytest.raises(ValueError, match="vendor omission"):
        build_incidence_windows(replace(view, events=view.events + (omission,)))


@pytest.mark.parametrize(
    ("category", "consideration", "unresolved", "qualifies"),
    (
        ("receivership", False, False, True),
        ("liquidation", False, False, True),
        ("ordinary_equity_cancellation", False, False, True),
        ("delisting", False, False, True),
        ("delisting", True, False, False),
        ("short_halt", False, False, False),
        ("suspension", False, True, True),
        ("suspension", False, False, False),
    ),
)
def test_terminal_categories_exclude_short_halts_and_known_consideration(
    category: str, consideration: bool, unresolved: bool, qualifies: bool
) -> None:
    view = _view(event_count=0)
    first = view.observations[0]
    event = ReferenceEvent(
        "event-test",
        first.issuer_id,
        view.official_sessions[view.official_sessions.index(first.session) + 5],
        category,
        consideration,
        unresolved,
    )
    windows = build_incidence_windows(replace(view, events=(event,)))
    assert (
        next(
            window
            for window in windows
            if window.issuer_id == first.issuer_id and window.start == first.session
        ).event_within_ten_sessions
        is qualifies
    )


def test_fewer_than_five_event_clusters_make_exact_landmark_bound_bind() -> None:
    result = calibrate_terminal_incidence(_view(event_count=3), bootstrap_draws=199)
    assert result.status is PromotionStatus.PASS
    assert result.primary_bound == result.landmark_exact_upper


def test_highest_risk_bucket_shift_is_at_least_primary_bound() -> None:
    result = calibrate_terminal_incidence(
        _view(), min_issuer_years=100, min_issuers=20, bootstrap_draws=99
    )
    assert len(result.buckets) == 4
    assert result.primary_bound is not None
    assert result.stressed_bound is not None
    assert result.stressed_bound >= result.primary_bound

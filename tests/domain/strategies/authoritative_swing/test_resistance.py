"""Deterministic swing-high resistance and strict 2R ceiling tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal

import pytest

from qat.domain.strategies.authoritative_swing.model import (
    AdjustmentStatus,
    DataQuality,
    DecisionStatus,
    FinalBar,
    Ohlcv,
    Pattern,
    PatternCandidate,
)
from qat.domain.strategies.authoritative_swing.numeric import SplitFactor
from qat.domain.strategies.authoritative_swing.resistance import (
    ResistanceMember,
    ResistanceZone,
    analytical_entry_ceiling_for,
    find_resistance_zones,
    nearest_relevant_resistance,
)


def D(value: str | int) -> Decimal:
    return Decimal(value)


def _bar(index: int, *, start: date = date(2023, 1, 1), high: str = "5") -> FinalBar:
    session = start + timedelta(days=index)
    prices = Ohlcv(D("4.5"), D(high), D("4"), D("4.75"), 1000)
    return FinalBar(
        symbol="BHP.AX",
        session=session,
        raw=prices,
        adjusted=prices,
        source="fixture",
        quality=DataQuality.VERIFIED,
        adjustment=AdjustmentStatus.SPLIT_NORMALIZED,
        raw_to_adjusted_price_factor=SplitFactor(1, 1),
        finalized=True,
        digest=f"digest-{index}",
    )


def _bars(count: int, peaks: dict[int, str] | None = None) -> tuple[FinalBar, ...]:
    peaks = peaks or {}
    return tuple(_bar(index, high=peaks.get(index, "5")) for index in range(count))


def _candidate(
    *,
    signal_close: str = "10",
    invalidation: str = "9",
    session: date = date(2026, 1, 5),
) -> PatternCandidate:
    return PatternCandidate(
        pattern=Pattern.EMA_PULLBACK,
        pattern_instance_id="pattern",
        breakout_event_id=None,
        signal_session=session,
        analytical_signal_close=D(signal_close),
        analytical_invalidation=D(invalidation),
        analytical_atr14=D("0.5"),
    )


def _three_year_history(peaks: dict[int, str] | None = None) -> tuple[FinalBar, ...]:
    return _bars(1100, peaks)


def test_five_bars_on_both_sides_are_required_for_swing_high() -> None:
    zones = find_resistance_zones(_bars(50, {4: "10", 10: "10.05", 35: "10.06"}))

    assert all(member.session != _bar(4).session for zone in zones for member in zone.members)


def test_exact_canonical_grouping_keeps_overlapping_maximal_zones() -> None:
    bars = _bars(80, {5: "10.00", 25: "10.10", 45: "10.20", 65: "10.30"})

    zones = find_resistance_zones(bars)

    assert [(zone.lower, zone.upper) for zone in zones] == [
        (D("10.00"), D("10.20")),
        (D("10.10"), D("10.30")),
    ]
    assert [len(zone.members) for zone in zones] == [3, 3]


def test_even_median_and_twenty_session_separation_are_exact_boundaries() -> None:
    assert find_resistance_zones(_bars(40, {5: "10.00", 25: "10.20"}))
    assert find_resistance_zones(_bars(40, {5: "10.00", 24: "10.20"})) == ()


def test_zone_construction_is_invariant_to_input_permutation() -> None:
    bars = _bars(80, {5: "10.00", 25: "10.10", 45: "10.20", 65: "10.30"})

    assert find_resistance_zones(bars) == find_resistance_zones(tuple(reversed(bars)))


def test_nearest_relevant_zone_uses_upper_edge_and_canonical_tie_break() -> None:
    member_a = ResistanceMember(date(2025, 1, 1), "a", D("10.1"), 1)
    member_b = ResistanceMember(date(2025, 2, 1), "b", D("10.2"), 25)
    left = ResistanceZone(D("10.1"), D("10.2"), (member_a, member_b))
    member_c = ResistanceMember(date(2025, 3, 1), "c", D("10.1"), 50)
    right = ResistanceZone(D("10.1"), D("10.3"), (member_a, member_c))

    assert nearest_relevant_resistance(D("10"), (right, left)) == left


def test_entry_limit_is_signal_close_when_no_zone_exists() -> None:
    result = analytical_entry_ceiling_for(_candidate(), _three_year_history())

    assert result.status is DecisionStatus.QUALIFIED
    assert result.limit_price == D("10")


def test_limit_is_last_quantum_whose_2r_price_is_below_zone() -> None:
    history = _three_year_history({500: "11.95", 900: "11.95"})

    result = analytical_entry_ceiling_for(_candidate(), history)

    assert result.status is DecisionStatus.QUALIFIED
    assert result.limit_price is not None
    assert result.limit_price + D("2") * (result.limit_price - D("9")) < D("11.95")


def test_zone_wholly_below_entry_is_ignored() -> None:
    history = _three_year_history({500: "8.00", 900: "8.10"})

    result = analytical_entry_ceiling_for(_candidate(), history)

    assert result.status is DecisionStatus.QUALIFIED
    assert result.limit_price == D("10")


def test_signal_close_inside_zone_or_on_either_edge_is_rejected() -> None:
    for close in ("9.90", "10.00", "10.10"):
        history = _three_year_history({500: "9.90", 900: "10.10"})

        result = analytical_entry_ceiling_for(_candidate(signal_close=close), history)

        assert result.status is DecisionStatus.REJECTED


def test_zone_touching_2r_path_requires_a_lower_entry() -> None:
    history = _three_year_history({500: "12.00", 900: "12.00"})

    result = analytical_entry_ceiling_for(_candidate(), history)

    assert result.limit_price is not None
    assert result.limit_price < D("10")


def test_unadjusted_or_short_history_abstains() -> None:
    short = analytical_entry_ceiling_for(_candidate(), _bars(100))
    assert short.status is DecisionStatus.ABSTAIN

    history = list(_three_year_history())
    history[4] = replace(history[4], adjustment=AdjustmentStatus.UNADJUSTED)
    unadjusted = analytical_entry_ceiling_for(_candidate(), tuple(history))
    assert unadjusted.status is DecisionStatus.ABSTAIN


@pytest.mark.parametrize(
    "replacement",
    [
        {"quality": DataQuality.SYNTHETIC},
        {"quality": DataQuality.UNVERIFIED},
        {"finalized": False},
    ],
)
def test_synthetic_unverified_or_partial_history_abstains(
    replacement: dict[str, object],
) -> None:
    history = list(_three_year_history())
    history[4] = replace(history[4], **replacement)

    result = analytical_entry_ceiling_for(_candidate(), tuple(history))

    assert result.status is DecisionStatus.ABSTAIN

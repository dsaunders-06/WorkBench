"""Canonical indicator and official-session weekly aggregation tests."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from qat.domain.strategies.authoritative_swing.indicators import (
    completed_weekly_bars,
    ema,
    wilder_atr,
)
from qat.domain.strategies.authoritative_swing.model import (
    AdjustmentStatus,
    DataQuality,
    FinalBar,
    Ohlcv,
)
from qat.domain.strategies.authoritative_swing.numeric import SplitFactor


def D(value: str) -> Decimal:
    return Decimal(value)


def _bar(
    session: date,
    *,
    open_: str = "10",
    high: str = "12",
    low: str = "9",
    close: str = "11",
    volume: int = 100,
) -> FinalBar:
    values = Ohlcv(D(open_), D(high), D(low), D(close), volume)
    return FinalBar(
        symbol="BHP.AX",
        session=session,
        raw=values,
        adjusted=values,
        source="fixture",
        quality=DataQuality.VERIFIED,
        adjustment=AdjustmentStatus.SPLIT_NORMALIZED,
        raw_to_adjusted_price_factor=SplitFactor(1, 1),
        finalized=True,
        digest=f"digest-{session.isoformat()}",
    )


def test_ema_is_seeded_by_the_first_simple_mean() -> None:
    assert ema(tuple(map(D, ("1", "2", "3", "4"))), 3) == (
        None,
        None,
        D("2"),
        D("3"),
    )


def test_ema_refuses_invalid_periods() -> None:
    with pytest.raises(ValueError, match="positive"):
        ema((D("1"),), 0)


def test_wilder_atr_uses_previous_close_for_gaps() -> None:
    bars = (
        _bar(date(2026, 1, 5), high="10", low="8", close="9"),  # TR 2
        _bar(date(2026, 1, 6), high="13", low="10", close="12"),  # TR 4
        _bar(date(2026, 1, 7), high="14", low="11", close="13"),  # TR 3
        _bar(date(2026, 1, 8), high="19", low="13", close="18"),  # TR 6
    )

    assert wilder_atr(bars, period=3) == (None, None, D("3"), D("4"))


def test_current_week_is_excluded_but_christmas_short_week_is_complete() -> None:
    sessions = tuple(
        map(
            date.fromisoformat,
            ("2026-12-21", "2026-12-22", "2026-12-23", "2026-12-24", "2026-12-29"),
        )
    )
    bars = tuple(_bar(session, volume=index) for index, session in enumerate(sessions, 1))

    weekly = completed_weekly_bars(bars, sessions)

    assert tuple(bar.session for bar in weekly) == (date(2026, 12, 24),)
    assert weekly[0].adjusted.volume == 10


def test_dataset_ad_hoc_closure_controls_week_completion() -> None:
    sessions = tuple(
        map(
            date.fromisoformat,
            ("2026-02-02", "2026-02-03", "2026-02-04", "2026-02-05", "2026-02-09"),
        )
    )
    bars = tuple(_bar(session) for session in sessions)

    assert completed_weekly_bars(bars, sessions)[-1].session == date(2026, 2, 5)


def test_weekly_ohlcv_uses_first_max_min_last_and_summed_volume() -> None:
    sessions = tuple(
        map(date.fromisoformat, ("2026-01-05", "2026-01-06", "2026-01-07", "2026-01-12"))
    )
    bars = (
        _bar(sessions[0], open_="10", high="12", low="9", close="11", volume=100),
        _bar(sessions[1], open_="11", high="14", low="10", close="13", volume=200),
        _bar(sessions[2], open_="13", high="13.5", low="8", close="9", volume=300),
        _bar(sessions[3]),
    )

    weekly = completed_weekly_bars(bars, sessions)[0]

    assert weekly.adjusted == Ohlcv(D("10"), D("14"), D("8"), D("9"), 600)
    assert weekly.finalized is True
    assert weekly.digest.startswith("swing:")


def test_incomplete_official_week_is_not_silently_aggregated() -> None:
    sessions = tuple(
        map(date.fromisoformat, ("2026-01-05", "2026-01-06", "2026-01-07", "2026-01-12"))
    )
    bars = (_bar(sessions[0]), _bar(sessions[2]), _bar(sessions[3]))

    assert completed_weekly_bars(bars, sessions) == ()


def test_official_sessions_must_be_unique_and_ordered() -> None:
    sessions = (date(2026, 1, 6), date(2026, 1, 5))

    with pytest.raises(ValueError, match="strictly increasing"):
        completed_weekly_bars((), sessions)

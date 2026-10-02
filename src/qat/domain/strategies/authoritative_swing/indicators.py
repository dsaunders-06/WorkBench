"""Canonical indicators and official-session weekly aggregation."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import date
from decimal import Context, Decimal, localcontext

from qat.domain.strategies.authoritative_swing.evidence import stable_decision_id
from qat.domain.strategies.authoritative_swing.model import (
    AdjustmentStatus,
    DataQuality,
    FinalBar,
    Ohlcv,
)
from qat.domain.strategies.authoritative_swing.numeric import NUMERIC_POLICY

IndicatorSeries = tuple[Decimal | None, ...]


def _calculation_context() -> Context:
    return Context(prec=NUMERIC_POLICY.precision, rounding=NUMERIC_POLICY.rounding)


def ema(values: Sequence[Decimal], period: int) -> IndicatorSeries:
    """Return an EMA seeded by the first period's arithmetic mean."""

    if period <= 0:
        raise ValueError("EMA period must be positive")
    if any(not value.is_finite() for value in values):
        raise ValueError("EMA values must be finite")
    output: list[Decimal | None] = [None] * len(values)
    if len(values) < period:
        return tuple(output)
    with localcontext(_calculation_context()):
        seed = sum(values[:period], Decimal(0)) / Decimal(period)
        output[period - 1] = seed
        multiplier = Decimal(2) / Decimal(period + 1)
        prior = seed
        for index in range(period, len(values)):
            prior = (values[index] - prior) * multiplier + prior
            output[index] = prior
    return tuple(output)


def wilder_atr(bars: Sequence[FinalBar], period: int = 14) -> IndicatorSeries:
    """Return Wilder ATR on split-normalized analytical bars."""

    if period <= 0:
        raise ValueError("ATR period must be positive")
    true_ranges: list[Decimal] = []
    previous_close: Decimal | None = None
    for bar in bars:
        prices = bar.adjusted
        candidates = [prices.high - prices.low]
        if previous_close is not None:
            candidates.extend((abs(prices.high - previous_close), abs(prices.low - previous_close)))
        true_ranges.append(max(candidates))
        previous_close = prices.close

    output: list[Decimal | None] = [None] * len(bars)
    if len(true_ranges) < period:
        return tuple(output)
    with localcontext(_calculation_context()):
        seed = sum(true_ranges[:period], Decimal(0)) / Decimal(period)
        output[period - 1] = seed
        prior = seed
        for index in range(period, len(true_ranges)):
            prior = ((prior * Decimal(period - 1)) + true_ranges[index]) / Decimal(period)
            output[index] = prior
    return tuple(output)


_QUALITY_RANK = {
    DataQuality.VERIFIED: 0,
    DataQuality.UNVERIFIED: 1,
    DataQuality.PARTIAL: 2,
    DataQuality.SYNTHETIC: 3,
    DataQuality.CONFLICTING: 4,
}


def _aggregate_ohlcv(bars: Sequence[FinalBar], basis: str) -> Ohlcv:
    values = [getattr(bar, basis) for bar in bars]
    return Ohlcv(
        open=values[0].open,
        high=max(value.high for value in values),
        low=min(value.low for value in values),
        close=values[-1].close,
        volume=sum(value.volume for value in values),
    )


def _validate_ordered_unique(values: Sequence[date], label: str) -> None:
    if any(
        current >= following
        for current, following in zip(values, values[1:], strict=False)
    ):
        raise ValueError(f"{label} must be unique and strictly increasing")


def completed_weekly_bars(
    bars: Sequence[FinalBar], official_sessions: Sequence[date]
) -> tuple[FinalBar, ...]:
    """Aggregate only complete weeks from the caller's official session catalog."""

    _validate_ordered_unique(official_sessions, "official sessions")
    bar_sessions = tuple(bar.session for bar in bars)
    _validate_ordered_unique(bar_sessions, "daily bar sessions")
    official_set = set(official_sessions)
    if any(session not in official_set for session in bar_sessions):
        raise ValueError("every daily bar session must exist in the official session catalog")

    sessions_by_week: dict[tuple[int, int], list[date]] = defaultdict(list)
    for session in official_sessions:
        iso = session.isocalendar()
        sessions_by_week[(iso.year, iso.week)].append(session)
    ordered_weeks = list(sessions_by_week)
    completed_weeks = set(ordered_weeks[:-1])
    bars_by_session = {bar.session: bar for bar in bars}
    weekly: list[FinalBar] = []

    for week in ordered_weeks:
        if week not in completed_weeks:
            continue
        expected_sessions = sessions_by_week[week]
        if any(session not in bars_by_session for session in expected_sessions):
            continue
        inputs = tuple(bars_by_session[session] for session in expected_sessions)
        last = inputs[-1]
        adjustments = {bar.adjustment for bar in inputs}
        sources = {bar.source for bar in inputs}
        weekly.append(
            FinalBar(
                symbol=last.symbol,
                session=last.session,
                raw=_aggregate_ohlcv(inputs, "raw"),
                adjusted=_aggregate_ohlcv(inputs, "adjusted"),
                source=last.source if len(sources) == 1 else "mixed",
                quality=max((bar.quality for bar in inputs), key=_QUALITY_RANK.__getitem__),
                adjustment=(
                    last.adjustment if len(adjustments) == 1 else AdjustmentStatus.UNKNOWN
                ),
                raw_to_adjusted_price_factor=last.raw_to_adjusted_price_factor,
                finalized=all(bar.finalized for bar in inputs),
                digest=stable_decision_id(
                    {
                        "kind": "completed_week",
                        "session": last.session,
                        "input_digests": tuple(bar.digest for bar in inputs),
                    }
                ),
            )
        )
    return tuple(weekly)

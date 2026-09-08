"""The GROWTH axis - Phase 2 of the macro regime matrix spec.

Every regime in the 7-regime matrix keys on growth: high, negative, normal, low,
accelerating, flat. QAT had PRICE TREND against a 50-day average and nothing
else. ⚠️ Those are not the same thing, and substituting one for the other is the
silent category error the spec forbids in section 3.3.

⚠️ THE SERIES IS THE OPERATOR'S CHOICE, NOT THIS MODULE'S. `classify_growth`
works over any observation history FRED can return; which series - and which
economy - is `Settings.macro_growth_series`, and it ships EMPTY. No growth axis
until someone chooses one, and the matrix refuses growth-dependent regimes
meanwhile. Picking a default here would silently answer the spec's open question
3, which also settles whether US macro drives an ASX book.

⚠️ AND EVERY CANDIDATE IS LAGGED. Real GDP is quarterly and published a month or
more after the quarter closes; Australian GDP is later still, so a reading can be
five months old before it moves. `GrowthRead` carries `age_days` so Phase 3 can
judge that rather than discover it. This module does not refuse on age: what
counts as too stale depends on the series chosen, and inventing a limit before
the series exists would be guessing twice.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from qat.data.macro_fred import MacroObservation
from qat.domain.macro_analysis.growth import classify_growth

_SERIES = "GDPC1"


def _quarterly(values: list[float], *, end: datetime | None = None) -> list[MacroObservation]:
    """Oldest first, one observation per quarter - the shape FRED returns."""
    end = end or datetime(2026, 6, 30, tzinfo=UTC)
    return [
        MacroObservation(
            series=_SERIES,
            ts=end - timedelta(days=91 * (len(values) - 1 - i)),
            value=value,
        )
        for i, value in enumerate(values)
    ]


def _growing(quarters: int, *, quarterly_rate: float, start: float = 100.0):
    return [start * (1.0 + quarterly_rate) ** i for i in range(quarters)]


def test_steady_expansion_reads_as_positive_growth() -> None:
    read = classify_growth(_quarterly(_growing(12, quarterly_rate=0.005)))

    assert read is not None
    # ~0.5% a quarter compounds to just over 2% a year.
    assert 1.5 < read.yoy_pct < 2.5


def test_contraction_reads_as_negative_growth() -> None:
    """⚠️ The BEAR and RECESSION regimes both require negative growth, so the
    sign is what separates half the matrix from the other half."""
    read = classify_growth(_quarterly(_growing(12, quarterly_rate=-0.01)))

    assert read is not None
    assert read.yoy_pct < 0


def test_growth_that_is_speeding_up_reads_as_accelerating() -> None:
    """⚠️ RECOVERY requires ACCELERATING growth - a second derivative of the
    level series. A rate alone cannot tell an expansion beginning from one
    ending."""
    slow = _growing(9, quarterly_rate=0.002)
    fast = [slow[-1] * (1.0 + 0.02) ** i for i in range(1, 5)]

    read = classify_growth(_quarterly(slow + fast))

    assert read is not None
    assert read.direction == "accelerating"


def test_growth_that_is_slowing_reads_as_decelerating() -> None:
    fast = _growing(9, quarterly_rate=0.02)
    slow = [fast[-1] * (1.0 + 0.001) ** i for i in range(1, 5)]

    read = classify_growth(_quarterly(fast + slow))

    assert read is not None
    assert read.direction == "decelerating"


def test_steady_growth_is_flattening_rather_than_a_trend() -> None:
    """Perfectly constant compounding: the year-on-year rate does not move."""
    read = classify_growth(_quarterly(_growing(13, quarterly_rate=0.005)))

    assert read is not None
    assert read.direction == "flattening"


def test_a_move_smaller_than_the_tolerance_is_still_flattening() -> None:
    """⚠️ THE TOLERANCE BAND ITSELF, and the test above does NOT exercise it.

    Found by sabotage: replacing the threshold with `change > 0` left every
    test green, because constant compounding moves the year-on-year rate by
    EXACTLY zero and zero fails a bare `> 0` too. A band that only ever sees
    zero is not a band.

    A tenth of a point is real movement and well inside the tolerance - the
    revision noise the band exists to absorb.
    """
    values = _growing(13, quarterly_rate=0.005)
    values[-1] *= 1.001

    read = classify_growth(_quarterly(values))

    assert read is not None
    assert read.direction == "flattening", "a tenth of a point was read as a turn"


def test_a_history_too_short_for_a_year_yields_nothing() -> None:
    """⚠️ Two quarters is not a smaller year-on-year figure - it is a different
    number. `None` rather than a partial-window guess, the habit
    `compute_macro_signal` already follows."""
    assert classify_growth(_quarterly(_growing(2, quarterly_rate=0.005))) is None


def test_an_empty_series_yields_nothing() -> None:
    assert classify_growth([]) is None


def test_a_gap_where_the_year_ago_reading_should_be_yields_nothing() -> None:
    """⚠️ Silently comparing against a TWO year old observation would report a
    growth rate for a period nobody asked about."""
    full = _quarterly(_growing(12, quarterly_rate=0.005))
    # Drop everything that would sit near the one-year mark.
    latest = full[-1].ts
    sparse = [o for o in full if not (300 <= (latest - o.ts).days <= 430)]

    assert classify_growth(sparse) is None


def test_the_read_carries_how_old_it_is() -> None:
    """⚠️ Real GDP is quarterly and published a month or more after the quarter
    closes. Phase 3 needs to know the reading's age to decide whether it may
    drive anything; discovering it later is how a five-month-old number ends up
    setting today's exposure."""
    end = datetime.now(UTC) - timedelta(days=140)
    read = classify_growth(_quarterly(_growing(12, quarterly_rate=0.005), end=end))

    assert read is not None
    assert read.age_days >= 139
    assert read.series == _SERIES


def test_a_zero_or_negative_base_yields_nothing() -> None:
    """A percentage change against zero is not a large number, it is no number."""
    values = _growing(12, quarterly_rate=0.005)
    values[0] = 0.0
    observations = _quarterly(values)
    # Keep only the window that would divide by that zero.
    assert classify_growth(observations[:5]) is None

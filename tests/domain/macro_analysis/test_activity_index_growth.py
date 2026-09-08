"""CFNAI-MA3 read against its own published bands, not through a YoY rate.

Operator decision, 8 September 2026: use a composite high-frequency proxy rather
than a quarterly GDP print, because a matrix sitting beside a DAILY engine and
fed a print published a quarter in arrears is permanently blind to a pivot.

⚠️ AND IT CANNOT GO THROUGH `classify_growth`. CFNAI is a weighted average of 85
indicators, normalised so ZERO IS TREND GROWTH and the units are standard
deviations. Computing a year-on-year change of it would be computing the change
OF A DEVIATION MEASURE: a move from -0.5 to -0.1 reads as an 80% change and
actually means "still below trend, improving". This is a different reader, not a
different constant.

⚠️ THE BANDS ARE THE CHICAGO FED'S. Below -0.70 following an expansion is their
published recession signal, and adopting it retires two thresholds this project
had invented (year-on-year growth at 1.5% and 3.0%). +0.20 is their
SUSTAINED-INFLATION threshold, used here as the high-growth boundary - that is an
interpretation and the module says so rather than passing it off as their rule.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from qat.data.macro_fred import MacroObservation
from qat.domain.macro_analysis.growth import classify_activity_index

_SERIES = "CFNAIMA3"


def _monthly(values: list[float], *, end: datetime | None = None) -> list[MacroObservation]:
    end = end or datetime(2026, 8, 31, tzinfo=UTC)
    return [
        MacroObservation(
            series=_SERIES,
            ts=end - timedelta(days=30 * (len(values) - 1 - i)),
            value=value,
        )
        for i, value in enumerate(values)
    ]


def test_below_the_recession_threshold_reads_as_negative_growth() -> None:
    """⚠️ -0.70 is the Chicago Fed's own line, and it is what separates the BEAR
    and RECESSION rows from the rest of the matrix."""
    read = classify_activity_index(_monthly([-0.2, -0.5, -0.85]))

    assert read is not None
    assert read.bucket == "negative"
    assert "-0.7" in read.summary


def test_below_trend_but_above_the_threshold_reads_as_low() -> None:
    """Between -0.70 and zero is a slowing economy, not a contracting one - and
    the matrix answers those two very differently."""
    read = classify_activity_index(_monthly([-0.1, -0.2, -0.35]))

    assert read is not None
    assert read.bucket == "low"


def test_at_or_above_trend_reads_as_normal() -> None:
    read = classify_activity_index(_monthly([0.0, 0.05, 0.10]))

    assert read is not None
    assert read.bucket == "normal"


def test_above_the_strong_band_reads_as_high() -> None:
    read = classify_activity_index(_monthly([0.10, 0.18, 0.31]))

    assert read is not None
    assert read.bucket == "high"


def test_a_rising_index_reads_as_accelerating() -> None:
    """⚠️ RECOVERY needs this, and it is the direction of the INDEX rather than
    a second derivative of a rate."""
    read = classify_activity_index(_monthly([-0.90, -0.85, -0.40]))

    assert read is not None
    assert read.direction == "accelerating"


def test_a_falling_index_reads_as_decelerating() -> None:
    read = classify_activity_index(_monthly([0.30, 0.25, -0.10]))

    assert read is not None
    assert read.direction == "decelerating"


def test_a_small_move_stays_flattening() -> None:
    """A tolerance band, so month-to-month revision noise is not read as a turn.
    ⚠️ This one IS this project's number - one invented constant where the
    year-on-year path had three."""
    read = classify_activity_index(_monthly([0.10, 0.11, 0.14]))

    assert read is not None
    assert read.direction == "flattening"


def test_the_summary_reports_the_index_and_never_a_percentage() -> None:
    """⚠️ The matrix quotes this verbatim. Formatting a standard-deviation
    reading as "% y/y" would put a unit on it that it does not have."""
    read = classify_activity_index(_monthly([-0.2, -0.5, -0.85]))

    assert read is not None
    assert "%" not in read.summary
    assert read.yoy_pct is None, "an activity index has no year-on-year rate"
    assert _SERIES in read.summary


def test_the_reading_carries_its_age() -> None:
    """Monthly and published about 25 days after month end - far better than a
    quarterly print, and still not current."""
    end = datetime.now(UTC) - timedelta(days=40)
    read = classify_activity_index(_monthly([0.1, 0.1, 0.1], end=end))

    assert read is not None
    assert read.age_days >= 39


def test_an_empty_series_yields_nothing() -> None:
    assert classify_activity_index([]) is None


def test_a_single_observation_has_no_direction() -> None:
    """One reading is not a smaller comparison."""
    read = classify_activity_index(_monthly([-0.85]))

    assert read is not None
    assert read.direction is None

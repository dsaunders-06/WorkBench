"""The one place a date becomes what an Australian reader expects on screen
(the ASX move) - pinned here so no call site drifts back to ISO on its own."""

from __future__ import annotations

from datetime import date, datetime

from qat.domain.display_dates import format_display_date


def test_a_date_renders_day_month_year():
    assert format_display_date(date(2026, 8, 18)) == "18/08/2026"


def test_a_datetime_renders_only_its_date_component():
    """The time-of-day is the caller's to format alongside this, at whatever
    precision that screen needs - this function is not the place a time
    silently reappears or silently vanishes."""
    assert format_display_date(datetime(2026, 8, 18, 14, 30, 5)) == "18/08/2026"


def test_day_and_month_are_unambiguous_even_when_both_are_single_digit():
    """3 April, not 4/3 - the exact ambiguity a US reader would resolve the
    other way."""
    assert format_display_date(date(2026, 4, 3)) == "03/04/2026"

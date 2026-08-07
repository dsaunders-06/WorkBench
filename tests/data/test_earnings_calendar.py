"""The earnings calendar and its distance arithmetic (M57).

The rail that consumes this can only ever make a position smaller, so every
failure here must read as "unknown" and cost the protection rather than the
session.
"""

from __future__ import annotations

import json
from datetime import date

from qat.data.earnings import (
    CACHE_FILENAME,
    NullEarningsCalendar,
    YFinanceEarningsCalendar,
    trading_days_between,
)

# Friday 7 August 2026 through the following week. 8-9 August is a weekend.
FRIDAY = date(2026, 8, 7)
MONDAY = date(2026, 8, 10)
TUESDAY = date(2026, 8, 11)


def test_a_weekend_is_not_two_trading_days() -> None:
    """The whole reason this counts sessions rather than dividing by seven."""
    assert (MONDAY - FRIDAY).days == 3
    assert trading_days_between(FRIDAY, MONDAY) == 1


def test_the_same_day_is_zero_days_away() -> None:
    assert trading_days_between(FRIDAY, FRIDAY) == 0


def test_a_date_already_past_reads_as_negative() -> None:
    """A stale entry must not size the next trade down forever - the risk it
    names has already happened."""
    assert trading_days_between(TUESDAY, FRIDAY) < 0


def test_a_us_holiday_is_not_counted() -> None:
    """4 July 2026 falls on a Saturday and is observed on Friday the 3rd."""
    before, after = date(2026, 7, 2), date(2026, 7, 6)
    assert (after - before).days == 4
    assert trading_days_between(before, after) == 1


def test_the_null_calendar_answers_nothing() -> None:
    assert NullEarningsCalendar().trading_days_until("AAA") is None


def test_a_cached_unknown_is_not_refetched(tmp_path) -> None:
    """A hit carrying None is a real answer - the vendor was asked and does not
    know. Treating it as a miss would refetch on every candidate, every tick,
    for exactly the symbols that can never answer."""
    (tmp_path / CACHE_FILENAME).write_text(
        json.dumps({"AAA": {"fetched_at": "2999-01-01T00:00:00+00:00", "next_earnings": None}}),
        encoding="utf-8",
    )
    calendar = YFinanceEarningsCalendar(tmp_path)

    fetched: list[str] = []
    calendar._fetch = lambda symbol: fetched.append(symbol) or None  # type: ignore[method-assign]

    assert calendar.next_earnings("AAA") is None
    assert fetched == [], "a known-unknown must not go back to the network"


def test_a_cached_date_is_used_and_measured_in_sessions(tmp_path) -> None:
    (tmp_path / CACHE_FILENAME).write_text(
        json.dumps(
            {"AAA": {"fetched_at": "2999-01-01T00:00:00+00:00", "next_earnings": "2026-08-11"}}
        ),
        encoding="utf-8",
    )
    calendar = YFinanceEarningsCalendar(tmp_path)

    assert calendar.next_earnings("AAA") == TUESDAY
    # Friday to the following Tuesday is two sessions, not four days.
    assert calendar.trading_days_until("AAA", as_of=FRIDAY) == 2


def test_an_unreadable_cache_degrades_to_empty(tmp_path) -> None:
    (tmp_path / CACHE_FILENAME).write_text("{ not json", encoding="utf-8")
    calendar = YFinanceEarningsCalendar(tmp_path)

    calendar._fetch = lambda symbol: None  # type: ignore[method-assign]
    assert calendar.next_earnings("AAA") is None


def test_a_fetch_that_raises_is_an_unknown_not_an_error(tmp_path) -> None:
    """This rail is optional. A vendor outage must cost the protection, never
    the session."""
    calendar = YFinanceEarningsCalendar(tmp_path)

    def boom(symbol: str) -> date | None:
        raise RuntimeError("vendor down")

    calendar._fetch = boom  # type: ignore[method-assign]
    try:
        result = calendar.next_earnings("AAA")
    except RuntimeError:
        raise AssertionError("the calendar must swallow a vendor failure") from None
    assert result is None

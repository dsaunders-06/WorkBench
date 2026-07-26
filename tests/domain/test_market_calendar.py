"""Market calendar (spec M13).

Holiday handling is the reason this module exists, so the holiday tests carry
the weight here: the original app's hours check had none, and under unattended
execution "is the market open" gates real orders.
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from qat.domain import market_calendar as mc

_NY = ZoneInfo("America/New_York")
_SYD = ZoneInfo("Australia/Sydney")


def _ny(y, m, d, hh=0, mm=0) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=_NY)


def _syd(y, m, d, hh=0, mm=0) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=_SYD)


# --- Easter, the input to four separate holidays ------------------------------


@pytest.mark.parametrize(
    ("year", "expected"),
    [
        (2024, date(2024, 3, 31)),
        (2025, date(2025, 4, 20)),
        (2026, date(2026, 4, 5)),
        (2027, date(2027, 3, 28)),
        (2030, date(2030, 4, 21)),
    ],
)
def test_easter_sunday_matches_known_dates(year, expected):
    assert mc.easter_sunday(year) == expected


# --- US holidays --------------------------------------------------------------


@pytest.mark.parametrize(
    ("day", "label"),
    [
        (date(2026, 1, 1), "New Year's Day"),
        (date(2026, 1, 19), "MLK Day"),
        (date(2026, 2, 16), "Presidents Day"),
        (date(2026, 4, 3), "Good Friday"),
        (date(2026, 5, 25), "Memorial Day"),
        (date(2026, 6, 19), "Juneteenth"),
        (date(2026, 7, 3), "Independence Day observed (Jul 4 is a Saturday)"),
        (date(2026, 9, 7), "Labor Day"),
        (date(2026, 11, 26), "Thanksgiving"),
        (date(2026, 12, 25), "Christmas Day"),
    ],
)
def test_us_market_is_closed_on_holidays(day, label):
    assert not mc.is_trading_day("US", day), label
    assert mc.closed_reason("US", day) == "public holiday"


def test_us_thanksgiving_is_the_fourth_thursday_not_the_last():
    """November 2025 has five Thursdays - a 'last Thursday' bug shows up here
    and nowhere else."""
    assert date(2025, 11, 27) in mc.us_holidays(2025)
    assert date(2025, 11, 20) not in mc.us_holidays(2025)


def test_a_saturday_holiday_is_observed_on_the_friday_before():
    # Independence Day 2026 falls on a Saturday.
    assert date(2026, 7, 3) in mc.us_holidays(2026)
    assert date(2026, 7, 4) not in mc.us_holidays(2026)


def test_a_sunday_holiday_is_observed_on_the_monday_after():
    # 1 January 2028 is a Saturday; 2022's New Year fell on a Saturday too.
    # Christmas 2022 fell on a Sunday -> observed Monday 26 December.
    assert date(2022, 12, 26) in mc.us_holidays(2022)


# --- ASX holidays -------------------------------------------------------------


@pytest.mark.parametrize(
    ("day", "label"),
    [
        (date(2026, 1, 1), "New Year's Day"),
        (date(2026, 1, 26), "Australia Day"),
        (date(2026, 4, 3), "Good Friday"),
        (date(2026, 4, 6), "Easter Monday"),
        (date(2026, 6, 8), "King's Birthday"),
        (date(2026, 12, 25), "Christmas Day"),
    ],
)
def test_asx_is_closed_on_holidays(day, label):
    assert not mc.is_trading_day("ASX", day), label


def test_anzac_day_on_a_weekend_is_observed_on_the_monday():
    # 25 April 2026 is a Saturday.
    assert date(2026, 4, 27) in mc.asx_holidays(2026)


def test_christmas_and_boxing_day_never_collapse_onto_the_same_date():
    """Christmas on a weekend pushes both observances forward; a naive shift
    lands them both on the same Monday and silently loses a closure."""
    for year in range(2020, 2041):
        holidays = mc.asx_holidays(year)
        christmas_ish = sorted(d for d in holidays if d.month == 12)
        assert len(christmas_ish) == len(set(christmas_ish))
        assert len(christmas_ish) == 2, year


def test_the_two_markets_have_genuinely_different_calendars():
    """Australia Day is an ASX closure and a normal US session, and vice versa
    for Thanksgiving - proof the market argument is actually honoured."""
    australia_day = date(2026, 1, 26)
    assert not mc.is_trading_day("ASX", australia_day)
    assert mc.is_trading_day("US", australia_day)

    thanksgiving = date(2026, 11, 26)
    assert not mc.is_trading_day("US", thanksgiving)
    assert mc.is_trading_day("ASX", thanksgiving)


# --- Weekends and ordinary days -----------------------------------------------


def test_weekends_are_closed_for_both_markets():
    saturday = date(2026, 7, 25)
    assert not mc.is_trading_day("US", saturday)
    assert not mc.is_trading_day("ASX", saturday)
    assert mc.closed_reason("US", saturday) == "weekend"


def test_an_ordinary_weekday_is_a_trading_day():
    ordinary = date(2026, 7, 23)  # a Thursday, no holiday either side
    assert mc.is_trading_day("US", ordinary)
    assert mc.is_trading_day("ASX", ordinary)
    assert mc.closed_reason("US", ordinary) is None


# --- Sessions and phases ------------------------------------------------------


def test_market_is_closed_before_the_open():
    session = mc.session_for("US", _ny(2026, 7, 23, 9, 0))
    assert session.is_open is False
    assert session.closed_reason == "before open"
    assert session.opens_at is not None


def test_market_is_closed_after_the_close():
    session = mc.session_for("US", _ny(2026, 7, 23, 16, 30))
    assert session.is_open is False
    assert session.closed_reason == "after close"


@pytest.mark.parametrize(
    ("hour", "minute", "expected_phase"),
    [
        (9, 31, "Opening Volatility"),
        (10, 30, "Morning Trend"),
        (12, 30, "Midday Lull"),
        (14, 45, "Afternoon"),
        (15, 50, "Closing Session"),
    ],
)
def test_us_session_phases(hour, minute, expected_phase):
    session = mc.session_for("US", _ny(2026, 7, 23, hour, minute))
    assert session.is_open is True
    assert session.phase == expected_phase


def test_asx_session_uses_its_own_hours():
    """10:00 is open on the ASX and would be pre-open on a US-hours check."""
    session = mc.session_for("ASX", _syd(2026, 7, 23, 10, 30))
    assert session.is_open is True
    assert session.phase == "Morning Trend"


def test_a_holiday_session_reports_closed_with_a_reason():
    session = mc.session_for("US", _ny(2026, 12, 25, 11, 0))
    assert session.is_open is False
    assert session.closed_reason == "public holiday"
    assert session.phase is None


def test_open_markets_switches_by_the_clock():
    """The auto-switching behaviour: the same instant is a US session and an
    ASX overnight, or the reverse."""
    us_hours = _ny(2026, 7, 23, 11, 0)
    assert "US" in mc.open_markets(us_hours)
    assert "ASX" not in mc.open_markets(us_hours)

    asx_hours = _syd(2026, 7, 23, 11, 0)
    assert "ASX" in mc.open_markets(asx_hours)
    assert "US" not in mc.open_markets(asx_hours)


def test_no_market_is_open_on_a_shared_weekend():
    assert mc.open_markets(_ny(2026, 7, 25, 12, 0)) == ()


# --- Early closes -------------------------------------------------------------


def test_black_friday_is_an_early_close_and_shifts_the_phase_boundaries():
    black_friday = _ny(2026, 11, 27, 12, 45)
    session = mc.session_for("US", black_friday)
    assert session.is_open is True
    assert session.is_early_close is True
    assert session.closes_at is not None
    assert session.closes_at.hour == 13
    # 12:45 is 15 minutes from a 13:00 close: the closing stretch, not the
    # midday lull it would be against a 16:00 close.
    assert session.phase == "Closing Session"


def test_after_an_early_close_the_market_reads_closed():
    session = mc.session_for("US", _ny(2026, 11, 27, 14, 0))
    assert session.is_open is False
    assert session.closed_reason == "after close"


# --- Autonomy eligibility -----------------------------------------------------


def test_opening_volatility_is_not_eligible_for_unattended_execution():
    session = mc.session_for("US", _ny(2026, 7, 23, 9, 35))
    assert session.is_open is True
    assert session.is_autonomous_eligible is False


def test_midday_lull_is_not_eligible_for_unattended_execution():
    session = mc.session_for("US", _ny(2026, 7, 23, 12, 30))
    assert session.is_open is True
    assert session.is_autonomous_eligible is False


def test_morning_trend_is_eligible():
    session = mc.session_for("US", _ny(2026, 7, 23, 10, 30))
    assert session.is_autonomous_eligible is True


def test_a_closed_market_is_never_eligible():
    session = mc.session_for("US", _ny(2026, 12, 25, 11, 0))
    assert session.is_autonomous_eligible is False


# --- Next open ----------------------------------------------------------------


def test_next_open_skips_the_weekend():
    friday_evening = _ny(2026, 7, 24, 18, 0)
    nxt = mc.next_open("US", friday_evening)
    assert nxt is not None
    assert nxt.date() == date(2026, 7, 27)  # the Monday
    assert (nxt.hour, nxt.minute) == (9, 30)


def test_next_open_skips_a_holiday():
    christmas_eve_evening = _ny(2026, 12, 24, 18, 0)
    nxt = mc.next_open("US", christmas_eve_evening)
    assert nxt is not None
    assert nxt.date() == date(2026, 12, 28)  # Christmas Friday is closed


def test_next_open_is_later_today_when_called_before_the_bell():
    nxt = mc.next_open("US", _ny(2026, 7, 23, 6, 0))
    assert nxt is not None
    assert nxt.date() == date(2026, 7, 23)


# --- One-off closures ---------------------------------------------------------


def test_an_extra_closure_can_be_registered(monkeypatch):
    day = date(2026, 7, 23)
    assert mc.is_trading_day("US", day)
    monkeypatch.setitem(mc.EXTRA_CLOSURES, day, frozenset({"US"}))
    assert not mc.is_trading_day("US", day)
    assert mc.closed_reason("US", day) == "unscheduled closure"
    # ASX was not listed, so it is unaffected.
    assert mc.is_trading_day("ASX", day)

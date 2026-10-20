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

_SYD = ZoneInfo("Australia/Sydney")


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


def test_asx_calendar_observes_australia_day_and_trades_on_thanksgiving():
    australia_day = date(2026, 1, 26)
    assert not mc.is_trading_day("ASX", australia_day)

    thanksgiving = date(2026, 11, 26)
    assert mc.is_trading_day("ASX", thanksgiving)


# --- Weekends and ordinary days -----------------------------------------------


def test_weekends_are_closed_for_asx():
    saturday = date(2026, 7, 25)
    assert not mc.is_trading_day("ASX", saturday)


def test_an_ordinary_weekday_is_a_trading_day():
    ordinary = date(2026, 7, 23)  # a Thursday, no holiday either side
    assert mc.is_trading_day("ASX", ordinary)


# --- Sessions and phases ------------------------------------------------------


def test_asx_session_uses_its_own_hours():
    """10:00 is open on the ASX and would be pre-open on a US-hours check."""
    session = mc.session_for("ASX", _syd(2026, 7, 23, 10, 30))
    assert session.is_open is True
    assert session.phase == "Morning Trend"


def test_open_markets_includes_asx_during_its_session():
    asx_hours = _syd(2026, 7, 23, 11, 0)
    assert "ASX" in mc.open_markets(asx_hours)


def test_no_market_is_open_on_a_shared_weekend():
    assert mc.open_markets(_syd(2026, 7, 25, 12, 0)) == ()


# --- Early closes -------------------------------------------------------------


def test_asx_christmas_eve_early_close_shifts_the_phase_boundary():
    session = mc.session_for("ASX", _syd(2026, 12, 24, 14, 5))
    assert session.is_open is True
    assert session.is_early_close is True
    assert session.closes_at is not None
    assert (session.closes_at.hour, session.closes_at.minute) == (14, 10)
    assert session.phase == "Closing Session"
    assert not mc.session_for("ASX", _syd(2026, 12, 24, 14, 11)).is_open


# --- Autonomy eligibility -----------------------------------------------------


def test_asx_autonomy_phases_keep_opening_and_midday_exclusions():
    assert not mc.session_for("ASX", _syd(2026, 7, 23, 10, 15)).is_autonomous_eligible
    assert mc.session_for("ASX", _syd(2026, 7, 23, 11, 0)).is_autonomous_eligible
    assert not mc.session_for("ASX", _syd(2026, 7, 23, 13, 0)).is_autonomous_eligible
    assert not mc.session_for("ASX", _syd(2026, 7, 23, 18, 0)).is_autonomous_eligible


# --- Next open ----------------------------------------------------------------


def test_asx_next_open_skips_the_weekend():
    next_session = mc.next_open("ASX", _syd(2026, 7, 24, 18, 0))
    assert next_session is not None
    assert next_session.date() == date(2026, 7, 27)
    assert (next_session.hour, next_session.minute) == (10, 0)


def test_asx_next_open_is_later_today_before_the_bell():
    next_session = mc.next_open("ASX", _syd(2026, 7, 23, 9, 0))
    assert next_session is not None
    assert next_session.date() == date(2026, 7, 23)
    assert (next_session.hour, next_session.minute) == (10, 0)


# --- One-off closures ---------------------------------------------------------


def test_an_extra_closure_can_be_registered(monkeypatch):
    day = date(2026, 7, 23)
    monkeypatch.setitem(mc.EXTRA_CLOSURES, day, frozenset({"US"}))
    # A historical US closure must not change the ASX calendar.
    assert mc.is_trading_day("ASX", day)


def test_an_asx_extra_closure_can_be_registered(monkeypatch):
    day = date(2026, 7, 23)
    assert mc.is_trading_day("ASX", day)
    monkeypatch.setitem(mc.EXTRA_CLOSURES, day, frozenset({"ASX"}))
    assert not mc.is_trading_day("ASX", day)
    assert mc.closed_reason("ASX", day) == "unscheduled closure"


# --- Auction states (Stage 3) -------------------------------------------------
#
# Constants MEASURED against the live paper Gateway on 21 August 2026 and
# RE-MEASURED 9 September; see
# docs/superpowers/specs/2026-09-09-asx-session-hours-raw.md. The tail is
# eleven minutes (tradingHours 1611 against liquidHours 1600) on both.
#
# 10 September 2026 is a Thursday, and that probe reports it as a normal
# session in as many words: "20260910:0959-20260910:1611".


def _syd_at(hh: int, mm: int, ss: int = 0) -> datetime:
    return datetime(2026, 9, 10, hh, mm, ss, tzinfo=_SYD)


@pytest.mark.parametrize(
    ("when", "expected_state", "expected_open"),
    [
        (_syd_at(9, 59), "pre_open", False),
        (_syd_at(10, 0), "opening_auction", True),
        (_syd_at(10, 9, 59), "opening_auction", True),
        (_syd_at(10, 10), "continuous", True),
        (_syd_at(12, 0), "continuous", True),
        (_syd_at(16, 0), "continuous", True),
        (_syd_at(16, 0, 1), "closing_auction", False),
        (_syd_at(16, 11), "closing_auction", False),
        (_syd_at(16, 11, 1), "closed", False),
    ],
)
def test_asx_trading_state_at_each_boundary(when, expected_state, expected_open):
    """Half-open at the start, inclusive at the close. 10:10:00 exactly is
    continuous, not still in the auction; 16:00:00 exactly is still open,
    preserving the existing `local > closes_at` comparison rather than quietly
    shortening the session by a second."""
    session = mc.session_for("ASX", when)
    assert session.trading_state == expected_state
    assert session.is_open is expected_open


def test_the_phase_boundaries_are_unchanged_by_the_auction_work():
    """The auction is modelled BESIDE the phase table, not inside it. Folding
    eleven minutes into the denominator would move every boundary in the day -
    Morning Trend would end at 12:00.4 rather than 11:58.8 - for a mechanism
    intraday volume patterns do not describe. This is the regression that would
    otherwise be invisible."""
    assert mc.session_for("ASX", _syd_at(10, 28)).phase == "Opening Volatility"
    assert mc.session_for("ASX", _syd_at(10, 29)).phase == "Morning Trend"
    assert mc.session_for("ASX", _syd_at(11, 58)).phase == "Morning Trend"
    assert mc.session_for("ASX", _syd_at(11, 59)).phase == "Midday Lull"
    assert mc.session_for("ASX", _syd_at(14, 5)).phase == "Afternoon"
    assert mc.session_for("ASX", _syd_at(15, 17)).phase == "Closing Session"
    assert mc.session_for("ASX", _syd_at(16, 0)).closes_at == _syd_at(16, 0)


def test_the_opening_auction_is_inside_opening_volatility():
    """Why buys need no new rule. The auction window sits strictly inside
    Opening Volatility, which is already excluded from unattended execution, so
    entries were never reaching the auction and only exits needed a gate."""
    assert mc.session_for("ASX", _syd_at(10, 5)).phase == "Opening Volatility"
    assert mc.session_for("ASX", _syd_at(10, 5)).is_autonomous_eligible is False


def test_the_closing_auction_is_not_autonomous_eligible():
    """is_open is False through the auction, and is_autonomous_eligible is
    defined as is_open AND an eligible phase."""
    assert mc.session_for("ASX", _syd_at(16, 5)).is_autonomous_eligible is False


def test_closed_reason_names_the_auction_rather_than_saying_after_close():
    assert mc.session_for("ASX", _syd_at(16, 5)).closed_reason == "closing auction"
    assert mc.session_for("ASX", _syd_at(17, 0)).closed_reason == "after close"


def test_a_holiday_is_closed_not_pre_open():
    """Christmas Day 2026 is a Friday, so this tests the holiday branch rather
    than the weekend one."""
    session = mc.session_for("ASX", datetime(2026, 12, 25, 11, 0, tzinfo=_SYD))
    assert session.trading_state == "closed"
    assert session.is_open is False


def test_auction_tail_minutes_is_public_because_preflight_compares_against_it():
    """Pre-flight compares this against what IBKR reports. A consumer reaching
    into `_AUCTION_TAIL_MINUTES` would be importing a private name across a
    module boundary to do it."""
    assert mc.auction_tail_minutes("ASX") == 11

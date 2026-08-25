"""The earnings calendar must answer for ASX symbols (item 49).

`YFinanceEarningsCalendar._fetch` asked `yf.Ticker(symbol).calendar`. Measured
on 25 August 2026 against the live vendor, for both TNE.AX and ANZ.AX, that
returns a dict whose `Earnings Date` is an EMPTY LIST - while
`get_earnings_dates()` returns a real date for each (17 and 9 November 2026).

So the rail asked the one API that does not answer for this market, and
`next_earnings` returned None for every ASX symbol. Everything downstream then
behaved exactly as designed for "unknown": the advisory context said "Next
scheduled results: UNKNOWN", and the earnings-event risk rail abstained. None
of it was broken - it was all correctly abstaining on a fact the vendor could
have supplied.

Note the original ShareTrader app used `get_earnings_dates()`, which is why
this information was visible in the first iteration of this project and not in
this one.
"""

from __future__ import annotations

from datetime import date, datetime

import pandas as pd

from qat.data.earnings import earnings_date_from_sources

_NOW = datetime(2026, 8, 25, 12, 0)


def test_the_calendar_dict_is_used_when_it_answers():
    calendar = {"Earnings Date": [date(2026, 9, 30)]}
    assert earnings_date_from_sources(calendar, None, now=_NOW) == date(2026, 9, 30)


def test_an_EMPTY_earnings_date_list_falls_back():
    """The live ASX shape. An empty list is not an answer."""
    calendar = {"Earnings Date": [], "Ex-Dividend Date": date(2026, 5, 28)}
    frame = pd.DataFrame(index=pd.DatetimeIndex([datetime(2026, 11, 17)]))
    assert earnings_date_from_sources(calendar, frame, now=_NOW) == date(2026, 11, 17)


def test_a_past_date_in_the_fallback_is_not_returned():
    """A stale announcement must not read as an upcoming one."""
    frame = pd.DataFrame(index=pd.DatetimeIndex([datetime(2026, 2, 1)]))
    assert earnings_date_from_sources({"Earnings Date": []}, frame, now=_NOW) is None


def test_the_soonest_future_date_wins():
    frame = pd.DataFrame(index=pd.DatetimeIndex([datetime(2027, 5, 1), datetime(2026, 11, 17)]))
    assert earnings_date_from_sources({"Earnings Date": []}, frame, now=_NOW) == date(2026, 11, 17)


def test_neither_source_answering_is_still_None():
    """The rail must keep abstaining rather than inventing a date."""
    assert earnings_date_from_sources({"Earnings Date": []}, None, now=_NOW) is None
    assert earnings_date_from_sources(None, pd.DataFrame(), now=_NOW) is None


def test_a_new_york_stamped_date_is_read_in_the_MARKET_timezone():
    """yfinance returns ASX announcement times stamped America/New_York -
    measured: Timestamp('2026-11-17 01:00:00-0500', tz='America/New_York') for
    TNE.AX. Taking `.date()` off that yields the NEW YORK calendar date.

    An ASX company announces on an ASX day. 2026-11-17 21:00 New York is
    2026-11-18 in Sydney, so reading it raw puts the announcement a session
    early - and this date sets the earnings blackout the risk engine sizes
    against.
    """
    import pandas as pd

    ny_evening = pd.Timestamp("2026-11-17 21:00:00", tz="America/New_York")
    frame = pd.DataFrame(index=pd.DatetimeIndex([ny_evening]))

    assert earnings_date_from_sources(
        {"Earnings Date": []}, frame, market="ASX", now=_NOW
    ) == date(2026, 11, 18), "the ASX date, not the New York one"


def test_the_same_instant_reads_as_the_new_york_date_for_a_US_symbol():
    """The conversion follows the MARKET, it is not a blanket shift to Sydney."""
    import pandas as pd

    ny_evening = pd.Timestamp("2026-11-17 21:00:00", tz="America/New_York")
    frame = pd.DataFrame(index=pd.DatetimeIndex([ny_evening]))

    assert earnings_date_from_sources(
        {"Earnings Date": []}, frame, market="US", now=_NOW
    ) == date(2026, 11, 17)


def test_a_naive_date_is_left_alone():
    """A plain date carries no time and must not be shifted by a conversion."""
    assert earnings_date_from_sources(
        {"Earnings Date": [date(2026, 11, 17)]}, None, market="ASX", now=_NOW
    ) == date(2026, 11, 17)

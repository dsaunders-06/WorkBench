"""IBKR trading-hours parsing.

Every fixture here is a string IBKR actually returned. An invented fixture
would test the parser against our idea of the format rather than against the
format.

⚠️ TAKEN FROM THE 9 SEPTEMBER PROBE, not the 21 August one the plan quoted -
`docs/superpowers/specs/2026-09-09-asx-session-hours-raw.md`. The two are
identical in shape nineteen days and a broker round trip apart, which is itself
worth knowing, but a fixture should come from the most recent measurement
somebody actually took rather than the oldest one still on disk.
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from qat.data.broker.ib_hours import parse_ib_hours

_SYD = ZoneInfo("Australia/Sydney")

# Verbatim from the 9 September probe. A2M.AX, and identical for all fourteen
# contracts spanning A2M to XRO - which is what settles that IBKR reports no
# staggered open.
TRADING = (
    "20260909:0959-20260909:1611;20260910:0959-20260910:1611;"
    "20260911:0959-20260911:1611;20260912:CLOSED;20260913:CLOSED;"
    "20260914:0959-20260914:1611"
)
LIQUID = (
    "20260909:0959-20260909:1600;20260910:0959-20260910:1600;"
    "20260911:0959-20260911:1600;20260912:CLOSED;20260913:CLOSED;"
    "20260914:0959-20260914:1600"
)


def test_parses_every_day_in_the_string():
    parsed = parse_ib_hours(TRADING, _SYD)
    assert sorted(parsed) == [
        date(2026, 9, 9),
        date(2026, 9, 10),
        date(2026, 9, 11),
        date(2026, 9, 12),
        date(2026, 9, 13),
        date(2026, 9, 14),
    ]


def test_a_trading_day_carries_one_timezone_aware_window():
    parsed = parse_ib_hours(TRADING, _SYD)
    assert parsed[date(2026, 9, 10)] == (
        (
            datetime(2026, 9, 10, 9, 59, tzinfo=_SYD),
            datetime(2026, 9, 10, 16, 11, tzinfo=_SYD),
        ),
    )


def test_the_windows_are_genuinely_timezone_aware():
    """⚠️ A naive datetime here would reproduce M128's shape one boundary
    further out, so the offset is asserted rather than assumed. Equality
    against another aware datetime would pass even if both were naive."""
    start, end = parse_ib_hours(TRADING, _SYD)[date(2026, 9, 10)][0]
    assert start.utcoffset() is not None
    assert end.utcoffset() is not None


def test_closed_days_are_present_and_empty():
    """Absent and closed are different facts. A caller asking whether Saturday
    is a trading day must be able to tell "IBKR says closed" from "IBKR did not
    mention Saturday"."""
    parsed = parse_ib_hours(TRADING, _SYD)
    assert parsed[date(2026, 9, 12)] == ()
    assert date(2026, 9, 15) not in parsed


def test_liquid_hours_close_earlier_than_trading_hours():
    """The eleven-minute delta IS the closing auction, and it is the only
    auction constant in this design that was measured."""
    trading = parse_ib_hours(TRADING, _SYD)[date(2026, 9, 10)][0]
    liquid = parse_ib_hours(LIQUID, _SYD)[date(2026, 9, 10)][0]
    assert trading[0] == liquid[0]
    assert (trading[1] - liquid[1]).total_seconds() == 11 * 60


def test_a_day_may_carry_more_than_one_window():
    """Not seen on ASX, documented by IBKR, and a parser that dropped the
    second window would do so silently."""
    text = "20260910:0800-20260910:1200,20260910:1300-20260910:1600"
    parsed = parse_ib_hours(text, _SYD)
    assert len(parsed[date(2026, 9, 10)]) == 2


def test_a_window_may_span_midnight():
    parsed = parse_ib_hours("20260910:2200-20260911:0400", _SYD)
    start, end = parsed[date(2026, 9, 10)][0]
    assert start == datetime(2026, 9, 10, 22, 0, tzinfo=_SYD)
    assert end == datetime(2026, 9, 11, 4, 0, tzinfo=_SYD)


def test_unparseable_input_returns_empty_rather_than_raising():
    """This is read inside pre-flight. A vendor string in an unexpected shape
    must degrade to "no comparison available", never take down the checks."""
    assert parse_ib_hours("nonsense", _SYD) == {}
    assert parse_ib_hours("", _SYD) == {}
    assert parse_ib_hours("20260910:99999-20260910:1600", _SYD) == {}


def test_one_bad_segment_discards_the_WHOLE_string():
    """⚠️ A DELIBERATE CHOICE, pinned because it looks like a bug otherwise.

    A partially-readable string yields `{}`, not the days that did parse. Half
    a calendar is worse than none here: the consumer compares IBKR's holidays
    against a hand-maintained table, and a silently truncated answer would
    report every missing day as a disagreement. Refusing the whole string makes
    the check say "no comparison available", which is true.
    """
    text = "20260909:0959-20260909:1611;GARBAGE;20260911:0959-20260911:1611"
    assert parse_ib_hours(text, _SYD) == {}

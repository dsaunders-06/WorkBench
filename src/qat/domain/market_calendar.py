"""Market hours, holidays and session phases for US and ASX (spec M13).

This is the piece the original ShareTrader app got approximately right and
explicitly flagged as incomplete: its hours check was a weekday + clock-time
comparison with no holiday awareness at all, so it believed the market was
open on Thanksgiving, Christmas and every ASX public holiday. That was
tolerable when a human was watching. It is not tolerable for unattended
execution, where "the market is open" is a precondition that gates real
orders - so holidays are computed here rather than ignored.

Holidays are *derived*, not listed: fixed-date rules with weekend-observance
shifts, nth-weekday rules, and an Easter computation for Good Friday / Easter
Monday. A derived calendar does not silently go stale the way a hardcoded
date list does the moment it runs past its last entry.

Known limits, stated plainly rather than hidden:
* One-off closures (national days of mourning, unscheduled market-wide halts)
  cannot be derived and are not covered. `EXTRA_CLOSURES` exists for adding
  them by hand.
* ASX state-based holidays are excluded, which is correct - the exchange
  observes national holidays, not state ones.
* Early closes are included for the well-known scheduled cases only.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

Market = Literal["US", "ASX"]

US_TZ = ZoneInfo("America/New_York")
ASX_TZ = ZoneInfo("Australia/Sydney")

MARKET_TIMEZONES: dict[Market, ZoneInfo] = {"US": US_TZ, "ASX": ASX_TZ}

_REGULAR_HOURS: dict[Market, tuple[time, time]] = {
    "US": (time(9, 30), time(16, 0)),
    "ASX": (time(10, 0), time(16, 0)),
}


def regular_hours(market: Market) -> tuple[time, time]:
    """The market's ordinary open and close, in its OWN local time.

    Public because a caller that needs to place itself inside a session cannot
    otherwise do so without hardcoding one market's hours - which the research
    harness did, using 15:00 UTC on the grounds that it sits inside the US
    session. It does; the ASX trades 00:00-06:00 UTC, so every ASX order it
    produced was refused for being out of hours.
    """
    return _REGULAR_HOURS[market]


_EARLY_CLOSE_TIMES: dict[Market, time] = {
    "US": time(13, 0),
    "ASX": time(14, 10),
}

# Add one-off closures here (date -> markets closed). Derived rules cannot
# know about these; nothing else in this module needs changing to honour them.
EXTRA_CLOSURES: dict[date, frozenset[str]] = {}

# (fraction of the session elapsed at or below which this phase applies, name).
# Ported from the original app's SESSION_PHASES, which drew them from
# documented intraday volume patterns: heaviest volume in the first and last
# stretches, a lower-liquidity lull around the middle.
SESSION_PHASES: tuple[tuple[float, str], ...] = (
    (0.08, "Opening Volatility"),
    (0.33, "Morning Trend"),
    (0.68, "Midday Lull"),
    (0.88, "Afternoon"),
    (1.01, "Closing Session"),
)

# Phases eligible for unattended execution. Opening Volatility and Midday Lull
# are excluded: the first has the widest spreads of the session and the second
# the thinnest liquidity, and both are stretches where a fill can land
# materially away from the price a trade was sized around.
AUTONOMOUS_ELIGIBLE_PHASES: frozenset[str] = frozenset(
    {"Morning Trend", "Afternoon", "Closing Session"}
)


@dataclass(frozen=True, slots=True)
class MarketSession:
    market: Market
    is_open: bool
    phase: str | None
    local_time: datetime
    opens_at: datetime | None
    closes_at: datetime | None
    is_early_close: bool = False
    closed_reason: str | None = None

    @property
    def is_autonomous_eligible(self) -> bool:
        return self.is_open and self.phase in AUTONOMOUS_ELIGIBLE_PHASES

    @property
    def seconds_to_close(self) -> float | None:
        if not self.is_open or self.closes_at is None:
            return None
        return (self.closes_at - self.local_time).total_seconds()


def easter_sunday(year: int) -> date:
    """Anonymous Gregorian algorithm. Good Friday and Easter Monday are both
    market holidays on both exchanges and neither has a fixed date."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    lunar = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * lunar) // 451
    month, day = divmod(h + lunar - 7 * m + 114, 31)
    return date(year, month, day + 1)


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """nth (1-based) `weekday` of a month; n=-1 means the last one."""
    if n > 0:
        first = date(year, month, 1)
        offset = (weekday - first.weekday()) % 7
        return first + timedelta(days=offset + 7 * (n - 1))
    next_month = date(year + (month == 12), (month % 12) + 1, 1)
    last = next_month - timedelta(days=1)
    return last - timedelta(days=(last.weekday() - weekday) % 7)


def _observed_us(holiday: date) -> date:
    """NYSE observance: a Saturday holiday moves to the preceding Friday, a
    Sunday holiday to the following Monday."""
    if holiday.weekday() == 5:
        return holiday - timedelta(days=1)
    if holiday.weekday() == 6:
        return holiday + timedelta(days=1)
    return holiday


def _observed_au(holiday: date) -> date:
    """ASX observance: a weekend holiday moves forward to the next weekday."""
    if holiday.weekday() == 5:
        return holiday + timedelta(days=2)
    if holiday.weekday() == 6:
        return holiday + timedelta(days=1)
    return holiday


def us_holidays(year: int) -> set[date]:
    easter = easter_sunday(year)
    return {
        _observed_us(date(year, 1, 1)),  # New Year's Day
        _nth_weekday(year, 1, 0, 3),  # Martin Luther King Jr. Day
        _nth_weekday(year, 2, 0, 3),  # Washington's Birthday
        easter - timedelta(days=2),  # Good Friday
        _nth_weekday(year, 5, 0, -1),  # Memorial Day
        _observed_us(date(year, 6, 19)),  # Juneteenth
        _observed_us(date(year, 7, 4)),  # Independence Day
        _nth_weekday(year, 9, 0, 1),  # Labor Day
        _nth_weekday(year, 11, 3, 4),  # Thanksgiving
        _observed_us(date(year, 12, 25)),  # Christmas Day
    }


def asx_holidays(year: int) -> set[date]:
    easter = easter_sunday(year)
    christmas = _observed_au(date(year, 12, 25))
    # Boxing Day is pushed past Christmas Day's own observed date, so the two
    # never collapse onto the same weekday when Christmas falls on a weekend.
    boxing_day = _observed_au(date(year, 12, 26))
    if boxing_day <= christmas:
        boxing_day = christmas + timedelta(days=1)
    return {
        _observed_au(date(year, 1, 1)),  # New Year's Day
        _observed_au(date(year, 1, 26)),  # Australia Day
        easter - timedelta(days=2),  # Good Friday
        easter + timedelta(days=1),  # Easter Monday
        _observed_au(date(year, 4, 25)),  # ANZAC Day
        _nth_weekday(year, 6, 0, 2),  # King's Birthday
        christmas,
        boxing_day,
    }


def _holidays(market: Market, year: int) -> set[date]:
    return us_holidays(year) if market == "US" else asx_holidays(year)


def early_closes(market: Market, year: int) -> set[date]:
    """Scheduled half-days. Not exhaustive - NYSE occasionally adds one - but
    the recurring ones are here, and getting the close time wrong would skew
    every session-phase boundary for that day."""
    if market == "US":
        thanksgiving = _nth_weekday(year, 11, 3, 4)
        closes = {thanksgiving + timedelta(days=1)}  # Black Friday
        july_3 = date(year, 7, 3)
        if july_3.weekday() < 5 and _observed_us(date(year, 7, 4)) == date(year, 7, 4):
            closes.add(july_3)
        christmas_eve = date(year, 12, 24)
        if christmas_eve.weekday() < 5:
            closes.add(christmas_eve)
        return closes
    closes = set()
    for candidate in (date(year, 12, 24), date(year, 12, 31)):
        if candidate.weekday() < 5:
            closes.add(candidate)
    return closes


def trading_date(market: Market, now: datetime | None = None) -> date:
    """The exchange's own calendar date for a moment - the trading day (M111).

    A UTC date is not a trading day, and on the ASX the two only agree for half
    the year. Australian Eastern time is UTC+10 until the first Sunday in
    October and UTC+11 after it, so from 5 October 2026 the session runs 23:00
    UTC on the previous day to 05:00 UTC and crosses UTC midnight at 11:00
    AEDT - an hour after the open.

    Anything that means "which session is this" must come through here. Two
    things did not and were caught before that date: the daily-loss baseline,
    which would have re-armed mid-session, and the daily bar boundary.

    Deliberately the calendar DATE and not a session lookup. A moment outside
    market hours still belongs to a trading day for the purpose of keying a
    day's state, and `session_for` already answers the different question of
    whether the market is open.
    """
    moment = now or datetime.now(UTC)
    return moment.astimezone(MARKET_TIMEZONES[market]).date()


def is_trading_day(market: Market, day: date) -> bool:
    if day.weekday() >= 5:
        return False
    if market in EXTRA_CLOSURES.get(day, frozenset()):
        return False
    return day not in _holidays(market, day.year)


def closed_reason(market: Market, day: date) -> str | None:
    if day.weekday() >= 5:
        return "weekend"
    if market in EXTRA_CLOSURES.get(day, frozenset()):
        return "unscheduled closure"
    if day in _holidays(market, day.year):
        return "public holiday"
    return None


def session_phase(elapsed_fraction: float) -> str:
    for upper_bound, name in SESSION_PHASES:
        if elapsed_fraction <= upper_bound:
            return name
    return SESSION_PHASES[-1][1]


def session_for(market: Market, now: datetime | None = None) -> MarketSession:
    """The market's state right now, in its own local time."""
    tz = MARKET_TIMEZONES[market]
    local = now.astimezone(tz) if now is not None else datetime.now(tz)
    day = local.date()

    reason = closed_reason(market, day)
    if reason is not None:
        return MarketSession(
            market=market,
            is_open=False,
            phase=None,
            local_time=local,
            opens_at=None,
            closes_at=None,
            closed_reason=reason,
        )

    open_time, close_time = _REGULAR_HOURS[market]
    is_early = day in early_closes(market, day.year)
    if is_early:
        close_time = _EARLY_CLOSE_TIMES[market]

    opens_at = local.replace(hour=open_time.hour, minute=open_time.minute, second=0, microsecond=0)
    closes_at = local.replace(
        hour=close_time.hour, minute=close_time.minute, second=0, microsecond=0
    )

    if local < opens_at:
        return MarketSession(
            market=market,
            is_open=False,
            phase=None,
            local_time=local,
            opens_at=opens_at,
            closes_at=closes_at,
            is_early_close=is_early,
            closed_reason="before open",
        )
    if local > closes_at:
        return MarketSession(
            market=market,
            is_open=False,
            phase=None,
            local_time=local,
            opens_at=opens_at,
            closes_at=closes_at,
            is_early_close=is_early,
            closed_reason="after close",
        )

    span = (closes_at - opens_at).total_seconds()
    elapsed = (local - opens_at).total_seconds() / span if span > 0 else 1.0
    return MarketSession(
        market=market,
        is_open=True,
        phase=session_phase(elapsed),
        local_time=local,
        opens_at=opens_at,
        closes_at=closes_at,
        is_early_close=is_early,
    )


def open_markets(now: datetime | None = None) -> tuple[Market, ...]:
    """Which markets are in their regular session - can be both, one, or none."""
    markets: tuple[Market, ...] = ("US", "ASX")
    return tuple(market for market in markets if session_for(market, now).is_open)


def next_open(
    market: Market, now: datetime | None = None, search_days: int = 30
) -> datetime | None:
    """The next regular-session open, skipping weekends and holidays.

    Bounded rather than looping forever: if no trading day turns up within the
    search window something is wrong with the calendar, and returning None lets
    the caller say so instead of hanging.
    """
    tz = MARKET_TIMEZONES[market]
    local = now.astimezone(tz) if now is not None else datetime.now(tz)
    open_time, _ = _REGULAR_HOURS[market]

    for offset in range(search_days + 1):
        day = (local + timedelta(days=offset)).date()
        if not is_trading_day(market, day):
            continue
        candidate = datetime.combine(day, open_time, tzinfo=tz)
        if candidate > local:
            return candidate
    return None

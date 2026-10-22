"""ASX market hours, holidays and session phases (spec M13).

This is the piece the original ShareTrader app got approximately right and
explicitly flagged as incomplete: its hours check was a weekday + clock-time
comparison with no holiday awareness at all, so it believed the market was
open on Christmas and every ASX public holiday. That was
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

Market = Literal["ASX"]

ASX_TZ = ZoneInfo("Australia/Sydney")

MARKET_TIMEZONES: dict[Market, ZoneInfo] = {"ASX": ASX_TZ}

# The currency a market's prices and P&L are denominated in (M122).
#
# Here rather than in the ledger because it is a property of the exchange, and
# because the ledger is not the only thing that will need it. `closed_trades.csv`
# carried no currency at all: two US trades from the retired broker period sat in the
# same file the ASX trial appends to, and their USD net_pnl would have been
# summed with AUD net_pnl into one total that means nothing.
CURRENCY_BY_MARKET: dict[Market, str] = {"ASX": "AUD"}


def currency_for(market: Market) -> str:
    return CURRENCY_BY_MARKET[market]


_REGULAR_HOURS: dict[Market, tuple[time, time]] = {
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


# What the exchange is DOING, as distinct from whether continuous trading is
# available. `is_open` keeps its existing meaning - continuous trading is
# available - because every caller already assumes it, and redefining it would
# change the autonomy gate, the feed and the stand-down at once.
TradingState = Literal["pre_open", "opening_auction", "continuous", "closing_auction", "closed"]

# MEASURED, 21 August 2026 against the live paper Gateway and RE-MEASURED
# 9 September. IBKR reports the ASX as tradingHours 0959-1611 against
# liquidHours 0959-1600: an eleven-minute tail after continuous trading, which
# is the pre-CSPA and the closing auction. Unchanged across both probes and
# across a broker round trip to TWS and back.
# See docs/superpowers/specs/2026-09-09-asx-session-hours-raw.md.
_AUCTION_TAIL_MINUTES: dict[Market, int] = {"ASX": 11}

# A JUDGEMENT, not a measurement, and the difference matters. The ASX opens in
# staggered alphabetical groups across roughly the first ten minutes, so an
# early-alphabet symbol is trading while a late one is still in its auction.
# IBKR does NOT expose this: all fourteen contracts probed across the alphabet
# returned identical hours on both probe dates, and the delta at the open is
# zero. Ten minutes is a deliberately conservative blanket over a window the
# broker cannot confirm.
#
_OPENING_AUCTION_MINUTES: dict[Market, int] = {"ASX": 10}


def auction_tail_minutes(market: Market) -> int:
    """Minutes of auction after continuous trading ends.

    Public because pre-flight compares this against what IBKR reports, and a
    consumer reaching into `_AUCTION_TAIL_MINUTES` across a module boundary
    would be importing a private name to do it.
    """
    return _AUCTION_TAIL_MINUTES[market]


@dataclass(frozen=True, slots=True)
class MarketSession:
    market: Market
    is_open: bool
    phase: str | None
    # REQUIRED, with no default. Constructed in exactly four places, all in this
    # module, and a default here would be silently wrong wherever it was
    # omitted - the shape `ts=now` already had once.
    trading_state: TradingState
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
    """Anonymous Gregorian algorithm for the ASX Easter holidays."""
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


def _observed_au(holiday: date) -> date:
    """Weekend substitution for holidays the ASX observes on a weekday."""
    if holiday.weekday() == 5:
        return holiday + timedelta(days=2)
    if holiday.weekday() == 6:
        return holiday + timedelta(days=1)
    return holiday


def asx_holidays(year: int) -> set[date]:
    easter = easter_sunday(year)
    christmas = _observed_au(date(year, 12, 25))
    # Boxing Day is pushed past Christmas Day's own observed date, so the two
    # never collapse onto the same weekday when Christmas falls on a weekend.
    boxing_day = _observed_au(date(year, 12, 26))
    if boxing_day <= christmas:
        boxing_day = christmas + timedelta(days=1)
    holidays = {
        _observed_au(date(year, 1, 1)),  # New Year's Day
        _observed_au(date(year, 1, 26)),  # Australia Day
        easter - timedelta(days=2),  # Good Friday
        easter + timedelta(days=1),  # Easter Monday
        _nth_weekday(year, 6, 0, 2),  # King's Birthday
        christmas,
        boxing_day,
    }
    # ASX cash market does not substitute a weekday closure for weekend ANZAC
    # Day: 27 April 2026 and 26 April 2027 are trading days. ASX calendar:
    # https://www.asx.com.au/markets/market-resources/trading-hours-calendar/cash-market-trading-hours/trading-calendar
    anzac_day = date(year, 4, 25)
    if anzac_day.weekday() < 5:
        holidays.add(anzac_day)
    return holidays


def _holidays(market: Market, year: int) -> set[date]:
    return asx_holidays(year)


def early_closes(market: Market, year: int) -> set[date]:
    """Scheduled ASX half-days used for session-phase boundaries."""
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
            trading_state="closed",
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
            trading_state="pre_open",
            local_time=local,
            opens_at=opens_at,
            closes_at=closes_at,
            is_early_close=is_early,
            closed_reason="before open",
        )
    if local > closes_at:
        # The auction is a separate mechanism bolted to the end of continuous
        # trading, not a stretch of the session. `is_open` stays False through
        # it - a market order into a single-price auction fills at the auction
        # price - and only the REASON changes, so an operator reading a refusal
        # at 16:05 is told the exchange is mid-auction rather than shut.
        #
        # ⚠️ On an early close the tail is ASSUMED to be the same eleven
        # minutes after the earlier close. No half-day fell inside either
        # probe's six-day window, so there is nothing to assert it against.
        # Task 4's pre-flight comparison is what will surface it when one
        # arrives.
        auction_end = closes_at + timedelta(minutes=_AUCTION_TAIL_MINUTES[market])
        in_auction = local <= auction_end
        return MarketSession(
            market=market,
            is_open=False,
            phase=None,
            trading_state="closing_auction" if in_auction else "closed",
            local_time=local,
            opens_at=opens_at,
            closes_at=closes_at,
            is_early_close=is_early,
            closed_reason="closing auction" if in_auction else "after close",
        )

    span = (closes_at - opens_at).total_seconds()
    elapsed = (local - opens_at).total_seconds() / span if span > 0 else 1.0
    auction_ends = opens_at + timedelta(minutes=_OPENING_AUCTION_MINUTES[market])
    return MarketSession(
        market=market,
        is_open=True,
        phase=session_phase(elapsed),
        # Half-open: 10:10:00 exactly is continuous, not still in the auction.
        trading_state="opening_auction" if local < auction_ends else "continuous",
        local_time=local,
        opens_at=opens_at,
        closes_at=closes_at,
        is_early_close=is_early,
    )


def open_markets(now: datetime | None = None) -> tuple[Market, ...]:
    """Which market is in its regular session."""
    markets: tuple[Market, ...] = ("ASX",)
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

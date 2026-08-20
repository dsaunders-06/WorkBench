"""Tick -> OHLC bar aggregation (spec M14).

Until now both FeatureEngine and StrategyEngine recorded each tick as a
degenerate bar with open == high == low == close. Every indicator downstream
inherited that: ATR in particular collapsed to |close - prev_close|, a
tick-to-tick delta with no intrabar range in it at all. Since ATR sets the
stop distance, and the stop distance sets the position size, a meaningless
ATR meant a meaningless size - so this is a correctness fix at the base of
the stack rather than a refinement.

Two things this deliberately does NOT do:

* It does not emit a bar per tick. A bar closes on a clock boundary, so a
  quiet minute produces one bar and a busy minute also produces one bar.
* It does not silently drop empty intervals. A gap in a free intraday feed is
  a minute with no trade, not a minute that did not happen - `fill_gaps`
  carries the last close forward with zero volume, so a rolling window of N
  bars spans N real minutes rather than however long the last N trades took.
  That distinction is what makes "a 30-bar average" mean what it says.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, tzinfo
from typing import Any

import pandas as pd

BAR_COLUMNS = ("ts", "open", "high", "low", "close", "volume")

_DAILY_SECONDS = 86_400
_INTRADAY_GAP_FILL_BARS = 10


@dataclass(slots=True)
class Bar:
    ts: datetime  # the bar's opening boundary
    open: float
    high: float
    low: float
    close: float
    volume: float

    def as_dict(self) -> dict[str, object]:
        return {
            "ts": self.ts,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
        }


def as_utc(ts: Any) -> datetime:
    """A vendor timestamp as a timezone-aware UTC datetime.

    Sources disagree about both type and zone - pandas Timestamps, naive
    datetimes, local zones - and a naive value silently compared against an
    aware one is a crash or, worse, a bar filed under the wrong day.
    """
    stamp = pd.Timestamp(ts)
    stamp = stamp.tz_localize(UTC) if stamp.tzinfo is None else stamp.tz_convert(UTC)
    return stamp.to_pydatetime()


def floor_to_interval(ts: datetime, interval_seconds: float, tz: tzinfo | None = None) -> datetime:
    """The opening boundary of the bar this timestamp belongs to.

    Anchored to the epoch rather than to the first tick seen, so two symbols
    that started streaming at different moments still produce bars on the same
    boundaries - otherwise cross-sectional comparisons (relative strength,
    breadth, pairs) would be quietly comparing misaligned windows.

    `tz` changes the DAILY boundary only, to local midnight on that exchange
    (M111). A trading day is not 86,400 seconds from the epoch on a market that
    observes daylight saving: from 5 October 2026 the ASX session runs 23:00
    UTC to 05:00 UTC, and an epoch-anchored daily bar closes an hour after the
    open - one session becoming two partial bars, with today's high and low
    computed over that first hour.

    The epoch anchor is untouched for every intraday interval, and the
    cross-symbol alignment it exists for holds either way: every symbol in an
    aggregator shares one timezone, so they all floor to the same boundary.
    """
    if tz is not None and interval_seconds == _DAILY_SECONDS:
        local = ts.astimezone(tz)
        midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
        return midnight.astimezone(UTC)
    epoch_seconds = ts.timestamp()
    floored = epoch_seconds - (epoch_seconds % interval_seconds)
    return datetime.fromtimestamp(floored, tz=UTC)


class BarAggregator:
    """Accumulates ticks for one symbol into fixed-interval OHLC bars."""

    def __init__(
        self,
        interval_seconds: float = 60.0,
        max_bars: int = 500,
        max_gap_fill_bars: int | None = None,
        tz: tzinfo | None = None,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        self.interval_seconds = interval_seconds
        # The exchange whose local midnight ends a daily bar (M111). None keeps
        # the pure epoch anchor, which stays correct for every intraday
        # interval and for a market that does not shift.
        self.tz = tz
        self.max_bars = max_bars
        # Gap filling is bounded because not every gap is a quiet market. An
        # overnight close, a weekend or a holiday is a *session break*, and
        # filling one would invent thousands of flat bars that never traded -
        # both wrong and ruinously expensive. Short gaps are quiet minutes and
        # get filled; long ones are treated as a new session and do not.
        #
        # On a daily interval there is no such thing as a quiet minute: every
        # gap is a weekend or a holiday, so filling any of them invents days
        # the market did not open. Friday to Monday is a two-bar gap, well
        # inside the intraday allowance, so the default has to depend on the
        # interval rather than being one number for both.
        if max_gap_fill_bars is None:
            max_gap_fill_bars = 0 if interval_seconds >= _DAILY_SECONDS else _INTRADAY_GAP_FILL_BARS
        self.max_gap_fill_bars = max_gap_fill_bars
        self._completed: list[Bar] = []
        self._forming: Bar | None = None

    def seed(self, frame: pd.DataFrame, now: datetime | None = None) -> int:
        """Loads already-closed historical bars, returning how many were kept.

        The warm start (M27a) exists because every buffer in this application
        was built from live ticks starting at zero, which left a daily-bar
        system inert for ten weeks to three months at every process start.

        Two rules make seeding safe to mix with the live path:

        * It refuses once any bar exists. Seeded history must sit strictly
          before live ticks; interleaving them would put an older bar after a
          newer one and silently corrupt every rolling window computed from
          the buffer.
        * It keeps only bars whose interval has already closed. A vendor's
          daily bar for *today* is a partial session, so it is loaded as the
          *forming* bar rather than a completed one. Discarding it would lose
          the session's true open, high and low on any restart after the open -
          a process restarted at noon would believe the day began at noon -
          and admitting it as completed would leave today represented twice.
        """
        if self._completed or self._forming is not None:
            raise RuntimeError(
                "seed() must run before any tick: seeded history cannot be interleaved "
                "with live bars"
            )
        if frame.empty:
            return 0

        current_boundary = floor_to_interval(
            now or datetime.now(UTC), self.interval_seconds, self.tz
        )

        # Keyed by boundary so a vendor emitting two rows inside one interval
        # collapses to one bar rather than producing duplicate timestamps.
        by_boundary: dict[datetime, Bar] = {}
        columns = (frame[name] for name in BAR_COLUMNS)
        for raw_ts, open_, high, low, close, volume in zip(*columns, strict=True):
            boundary = floor_to_interval(as_utc(raw_ts), self.interval_seconds, self.tz)
            bar = Bar(
                ts=boundary,
                open=float(open_),
                high=float(high),
                low=float(low),
                close=float(close),
                volume=float(volume),
            )
            if boundary > current_boundary:
                continue  # the future: a vendor timestamp that cannot be right
            if boundary == current_boundary:
                self._forming = bar
                continue
            by_boundary[boundary] = bar

        self._completed = [by_boundary[key] for key in sorted(by_boundary)]
        self._trim()
        return len(self._completed)

    def prime_bar(self, bar: Bar) -> None:
        """Install an already-true OHLC bar as the FORMING bar (W2).

        The research harness has daily bars and no ticks, and this application
        builds bars FROM ticks. One tick per day would give high == low ==
        close, ATR would collapse to the tick-to-tick delta this module's tests
        already guard against, and ATR sets the stop distance which sets the
        position size - so every figure would be wrong and nothing would raise.

        Priming installs the real range, and the ordinary MarketDataEvent that
        follows folds in harmlessly: a daily close sits inside the day's range,
        so max(high, close) and min(low, close) change nothing. Evaluation then
        runs through the production path unmodified, which is the whole point -
        a harness that fed the strategy differently would be measuring a
        different system.

        Guarded as `seed` is. An older bar landing after a newer one silently
        corrupts every rolling window computed from this buffer, and a bar off
        its boundary is a bar filed under the wrong day.
        """
        boundary = floor_to_interval(bar.ts, self.interval_seconds, self.tz)
        if bar.ts != boundary:
            raise ValueError(
                f"prime_bar needs a bar on an interval boundary; {bar.ts} floors to {boundary}"
            )
        if self._forming is not None:
            if bar.ts <= self._forming.ts:
                raise RuntimeError(
                    "prime_bar must move forward: seeded and primed history cannot be "
                    "interleaved out of order"
                )
            self._completed.append(self._forming)
            self._trim()
        elif self._completed and bar.ts <= self._completed[-1].ts:
            raise RuntimeError(
                "prime_bar must move forward: seeded and primed history cannot be "
                "interleaved out of order"
            )
        self._forming = bar

    def add_tick(self, ts: datetime, price: float, volume: float = 0.0) -> Bar | None:
        """Feeds one tick. Returns the bar that just *closed*, if any.

        A returned bar is final and will not change again, which is what makes
        it safe for a strategy to act on. The forming bar keeps mutating.
        """
        boundary = floor_to_interval(ts, self.interval_seconds, self.tz)

        if self._forming is None:
            self._forming = Bar(boundary, price, price, price, price, volume)
            return None

        if boundary == self._forming.ts:
            self._forming.high = max(self._forming.high, price)
            self._forming.low = min(self._forming.low, price)
            self._forming.close = price
            self._forming.volume += volume
            return None

        if boundary < self._forming.ts:
            # Out-of-order tick. Folding it into the current bar would corrupt
            # a bar that has already been acted on, so it is dropped instead.
            return None

        closed = self._forming
        self._completed.append(closed)
        self._fill_gap_to(boundary, closed)
        self._forming = Bar(boundary, price, price, price, price, volume)
        self._trim()
        return closed

    def _fill_gap_to(self, boundary: datetime, previous: Bar) -> None:
        """Inserts flat bars for intervals in which nothing traded.

        Price is carried forward (a quiet minute means the price did not move,
        which is true) and volume is zero, never the carried-forward volume -
        repeating the last bar's volume would invent trades that did not occur
        and would corrupt any volume-based indicator.
        """
        step = timedelta(seconds=self.interval_seconds)
        missing = int((boundary - previous.ts).total_seconds() // self.interval_seconds) - 1
        if missing <= 0 or missing > self.max_gap_fill_bars:
            return  # a session break, not a quiet stretch

        cursor = previous.ts + step
        while cursor < boundary:
            self._completed.append(
                Bar(cursor, previous.close, previous.close, previous.close, previous.close, 0.0)
            )
            cursor += step

    def _trim(self) -> None:
        if len(self._completed) > self.max_bars:
            del self._completed[: len(self._completed) - self.max_bars]

    @property
    def forming(self) -> Bar | None:
        return self._forming

    def completed_bars(self) -> list[Bar]:
        return list(self._completed)

    def frame(self, include_forming: bool = True) -> pd.DataFrame:
        """Bars as a DataFrame, oldest first.

        The forming bar is included by default because that is what a live
        chart shows and what a strategy evaluating "right now" should see. Pass
        include_forming=False for anything that must only ever see final bars,
        such as a backtest boundary.
        """
        rows = [bar.as_dict() for bar in self._completed]
        if include_forming and self._forming is not None:
            rows.append(self._forming.as_dict())
        if not rows:
            return pd.DataFrame(columns=list(BAR_COLUMNS))
        return pd.DataFrame(rows)

    def __len__(self) -> int:
        return len(self._completed) + (1 if self._forming is not None else 0)


class MultiSymbolAggregator:
    """One BarAggregator per symbol, created on first sight of that symbol."""

    def __init__(
        self,
        interval_seconds: float = 60.0,
        max_bars: int = 500,
        max_gap_fill_bars: int | None = None,
        tz: tzinfo | None = None,
    ) -> None:
        self.interval_seconds = interval_seconds
        self.max_bars = max_bars
        self.max_gap_fill_bars = max_gap_fill_bars
        self.tz = tz
        self._by_symbol: dict[str, BarAggregator] = {}

    def add_tick(self, symbol: str, ts: datetime, price: float, volume: float = 0.0) -> Bar | None:
        return self.for_symbol(symbol).add_tick(ts, price, volume)

    def seed(self, symbol: str, frame: pd.DataFrame, now: datetime | None = None) -> int:
        return self.for_symbol(symbol).seed(frame, now=now)

    def prime_bar(self, symbol: str, bar: Bar) -> None:
        self.for_symbol(symbol).prime_bar(bar)

    def for_symbol(self, symbol: str) -> BarAggregator:
        aggregator = self._by_symbol.get(symbol)
        if aggregator is None:
            aggregator = BarAggregator(
                self.interval_seconds, self.max_bars, self.max_gap_fill_bars, self.tz
            )
            self._by_symbol[symbol] = aggregator
        return aggregator

    def frame(self, symbol: str, include_forming: bool = True) -> pd.DataFrame:
        return self.for_symbol(symbol).frame(include_forming=include_forming)

    def frame_if_present(self, symbol: str, include_forming: bool = True) -> pd.DataFrame | None:
        """The same frame `frame()` returns, without `for_symbol()`'s side
        effect of creating and storing an aggregator for a symbol this
        instance has never seen (positions panel brief review, M6).

        `frame()` is right for a live tick pipeline, where seeing a symbol
        for the first time is exactly when an aggregator should be created
        for it. It is wrong for a read-only caller - a display asking what
        bars already exist for a symbol it did not choose to start tracking
        - which must not be able to mutate this aggregator's state merely by
        looking.

        `None` when the symbol has never been seen, distinguishing "nothing
        recorded yet" from "an empty frame for a symbol we are tracking".
        """
        aggregator = self._by_symbol.get(symbol)
        if aggregator is None:
            return None
        return aggregator.frame(include_forming=include_forming)

    def symbols(self) -> list[str]:
        return list(self._by_symbol)

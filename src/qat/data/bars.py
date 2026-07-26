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
from datetime import UTC, datetime, timedelta

import pandas as pd

BAR_COLUMNS = ("ts", "open", "high", "low", "close", "volume")


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


def floor_to_interval(ts: datetime, interval_seconds: float) -> datetime:
    """The opening boundary of the bar this timestamp belongs to.

    Anchored to the epoch rather than to the first tick seen, so two symbols
    that started streaming at different moments still produce bars on the same
    boundaries - otherwise cross-sectional comparisons (relative strength,
    breadth, pairs) would be quietly comparing misaligned windows.
    """
    epoch_seconds = ts.timestamp()
    floored = epoch_seconds - (epoch_seconds % interval_seconds)
    return datetime.fromtimestamp(floored, tz=UTC)


class BarAggregator:
    """Accumulates ticks for one symbol into fixed-interval OHLC bars."""

    def __init__(
        self,
        interval_seconds: float = 60.0,
        max_bars: int = 500,
        max_gap_fill_bars: int = 10,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        self.interval_seconds = interval_seconds
        self.max_bars = max_bars
        # Gap filling is bounded because not every gap is a quiet market. An
        # overnight close, a weekend or a holiday is a *session break*, and
        # filling one would invent thousands of flat bars that never traded -
        # both wrong and ruinously expensive. Short gaps are quiet minutes and
        # get filled; long ones are treated as a new session and do not.
        self.max_gap_fill_bars = max_gap_fill_bars
        self._completed: list[Bar] = []
        self._forming: Bar | None = None

    def add_tick(self, ts: datetime, price: float, volume: float = 0.0) -> Bar | None:
        """Feeds one tick. Returns the bar that just *closed*, if any.

        A returned bar is final and will not change again, which is what makes
        it safe for a strategy to act on. The forming bar keeps mutating.
        """
        boundary = floor_to_interval(ts, self.interval_seconds)

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
        max_gap_fill_bars: int = 10,
    ) -> None:
        self.interval_seconds = interval_seconds
        self.max_bars = max_bars
        self.max_gap_fill_bars = max_gap_fill_bars
        self._by_symbol: dict[str, BarAggregator] = {}

    def add_tick(self, symbol: str, ts: datetime, price: float, volume: float = 0.0) -> Bar | None:
        return self.for_symbol(symbol).add_tick(ts, price, volume)

    def for_symbol(self, symbol: str) -> BarAggregator:
        aggregator = self._by_symbol.get(symbol)
        if aggregator is None:
            aggregator = BarAggregator(self.interval_seconds, self.max_bars, self.max_gap_fill_bars)
            self._by_symbol[symbol] = aggregator
        return aggregator

    def frame(self, symbol: str, include_forming: bool = True) -> pd.DataFrame:
        return self.for_symbol(symbol).frame(include_forming=include_forming)

    def symbols(self) -> list[str]:
        return list(self._by_symbol)

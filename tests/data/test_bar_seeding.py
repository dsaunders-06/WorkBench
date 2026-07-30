"""Warm-start seeding of the bar aggregators (M27a)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from qat.data.bars import BarAggregator, MultiSymbolAggregator

_DAY = 86_400.0
_NOW = datetime(2026, 7, 30, 15, 0, tzinfo=UTC)


def _daily_frame(days: int, last_day: datetime = _NOW, hour: int = 4) -> pd.DataFrame:
    """Daily bars in the shape a vendor returns them - Alpaca stamps each one
    at 04:00 UTC, not at the UTC day boundary the aggregator floors to."""
    rows = []
    for i in range(days):
        day = (last_day - timedelta(days=days - 1 - i)).replace(
            hour=hour, minute=0, second=0, microsecond=0
        )
        base = 100.0 + i
        rows.append(
            {
                "ts": day,
                "open": base,
                "high": base + 2.0,
                "low": base - 1.0,
                "close": base + 1.0,
                "volume": 1_000.0 + i,
            }
        )
    return pd.DataFrame(rows)


def test_seeded_bars_keep_their_real_ohlc():
    """The whole reason for a seed() rather than replaying ticks: one tick per
    day would give open == high == low == close, and ATR computed from that
    collapses to a close-to-close delta - which sets the stop, which sets the
    position size (M14)."""
    aggregator = BarAggregator(interval_seconds=_DAY)

    kept = aggregator.seed(_daily_frame(10), now=_NOW)

    assert kept == 9  # today's partial bar is excluded
    frame = aggregator.frame()
    assert frame["high"].iloc[-1] > frame["close"].iloc[-1]
    assert frame["low"].iloc[-1] < frame["open"].iloc[-1]


def test_todays_partial_bar_becomes_the_forming_bar():
    """A vendor's bar for today covers a session still in progress, so it is
    the forming bar, never a completed one. Completing it would represent today
    twice; discarding it would lose the session's open, high and low on any
    restart after the open."""
    aggregator = BarAggregator(interval_seconds=_DAY)
    aggregator.seed(_daily_frame(5), now=_NOW)

    boundaries = [bar.ts for bar in aggregator.completed_bars()]
    assert max(boundaries) == datetime(2026, 7, 29, tzinfo=UTC)

    forming = aggregator.forming
    assert forming is not None
    assert forming.ts == datetime(2026, 7, 30, tzinfo=UTC)


def test_a_midday_restart_keeps_the_days_open_high_and_low():
    """The one thing a warm start could genuinely lose. Restarted at noon
    without this, the aggregator believes the day opened at noon - and the
    day's range is what ATR, and therefore the stop and the position size, are
    computed from."""
    aggregator = BarAggregator(interval_seconds=_DAY)
    aggregator.seed(_daily_frame(5), now=_NOW)

    # The session continues after the restart.
    aggregator.add_tick(_NOW + timedelta(hours=1), 103.0, 5.0)

    forming = aggregator.forming
    assert forming is not None
    assert forming.open == 104.0  # the real open, not the restart price
    assert forming.high == 106.0  # the morning's high survived
    assert forming.close == 103.0  # and the latest tick still moves it


def test_seeding_refuses_once_a_tick_has_been_recorded():
    """Seeded history appended after live bars would put an older bar after a
    newer one and corrupt every rolling window read from the buffer."""
    aggregator = BarAggregator(interval_seconds=_DAY)
    aggregator.add_tick(_NOW, 500.0, 1.0)

    with pytest.raises(RuntimeError, match="before any tick"):
        aggregator.seed(_daily_frame(5), now=_NOW)


def test_live_ticks_extend_the_seeded_history_without_a_gap():
    """A day of intraday ticks folds into one forming daily bar with true
    OHLC, on top of history that ends the day before."""
    aggregator = BarAggregator(interval_seconds=_DAY)
    # Ends yesterday, so nothing is seeded into the forming slot.
    aggregator.seed(_daily_frame(10, last_day=_NOW - timedelta(days=1)), now=_NOW)
    seeded = len(aggregator.completed_bars())

    aggregator.add_tick(_NOW, 120.0, 10.0)
    aggregator.add_tick(_NOW + timedelta(hours=1), 125.0, 10.0)
    aggregator.add_tick(_NOW + timedelta(hours=2), 118.0, 10.0)

    forming = aggregator.forming
    assert forming is not None
    assert (forming.open, forming.high, forming.low, forming.close) == (120.0, 125.0, 118.0, 118.0)
    assert len(aggregator.completed_bars()) == seeded
    assert len(aggregator.frame()) == seeded + 1


def test_a_daily_interval_never_fills_a_weekend():
    """Friday to Monday is a two-bar gap, well inside the ten-bar intraday
    allowance. Filling it would invent days the market did not open."""
    aggregator = BarAggregator(interval_seconds=_DAY)
    friday = datetime(2026, 7, 24, 14, 0, tzinfo=UTC)
    monday = friday + timedelta(days=3)

    aggregator.add_tick(friday, 100.0, 1.0)
    aggregator.add_tick(monday, 101.0, 1.0)

    assert [bar.ts for bar in aggregator.completed_bars()] == [datetime(2026, 7, 24, tzinfo=UTC)]


def test_an_intraday_interval_still_fills_quiet_minutes():
    aggregator = BarAggregator(interval_seconds=60.0)
    start = datetime(2026, 7, 30, 14, 0, tzinfo=UTC)

    aggregator.add_tick(start, 100.0, 1.0)
    aggregator.add_tick(start + timedelta(minutes=3), 101.0, 1.0)

    assert len(aggregator.completed_bars()) == 3  # the traded bar plus two quiet minutes


def test_multi_symbol_seeding_is_per_symbol():
    aggregator = MultiSymbolAggregator(interval_seconds=_DAY)

    # The return is completed bars; the frame adds today's forming bar.
    assert aggregator.seed("SPY", _daily_frame(10), now=_NOW) == 9
    assert aggregator.seed("AAPL", _daily_frame(4), now=_NOW) == 3
    assert len(aggregator.frame("SPY")) == 10
    assert len(aggregator.frame("AAPL")) == 4
    assert aggregator.frame("MSFT").empty


def test_two_rows_inside_one_interval_collapse_to_one_bar():
    aggregator = BarAggregator(interval_seconds=_DAY)
    frame = _daily_frame(3)
    duplicated = pd.concat([frame, frame.tail(1).assign(close=999.0)], ignore_index=True)

    kept = aggregator.seed(duplicated, now=_NOW)

    assert kept == 2
    assert len({bar.ts for bar in aggregator.completed_bars()}) == 2

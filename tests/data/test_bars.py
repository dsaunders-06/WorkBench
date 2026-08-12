"""Tick -> OHLC aggregation (spec M14).

The property that matters: bars must have real intrabar range. The old
degenerate bars made ATR collapse to a tick-to-tick delta, and ATR sets the
stop distance which sets the position size.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from qat.data.bars import Bar, BarAggregator, MultiSymbolAggregator, floor_to_interval
from qat.data.features import compute_atr

BASE = datetime(2026, 7, 23, 14, 0, 0, tzinfo=UTC)


def _at(seconds: float) -> datetime:
    return BASE + timedelta(seconds=seconds)


def test_ticks_inside_one_interval_form_a_single_bar():
    agg = BarAggregator(interval_seconds=60)
    for offset, price in ((0, 100.0), (10, 103.0), (20, 98.0), (30, 101.0)):
        assert agg.add_tick(_at(offset), price, volume=5.0) is None

    bar = agg.forming
    assert bar is not None
    assert (bar.open, bar.high, bar.low, bar.close) == (100.0, 103.0, 98.0, 101.0)
    assert bar.volume == 20.0


def test_high_and_low_differ_from_the_close():
    """The whole point: a bar carries the range traded, not just a price."""
    agg = BarAggregator(interval_seconds=60)
    for offset, price in ((0, 100.0), (10, 110.0), (20, 90.0), (30, 100.0)):
        agg.add_tick(_at(offset), price)

    frame = agg.frame()
    assert frame["high"].iloc[-1] > frame["close"].iloc[-1]
    assert frame["low"].iloc[-1] < frame["close"].iloc[-1]


def test_atr_is_no_longer_a_tick_to_tick_delta():
    """Regression cover for the degenerate-bar bug. With open==high==low==close
    the true range is |close - prev_close|; with real bars it includes the
    intrabar span, which is strictly larger for a symbol that moves within
    the interval."""
    real = BarAggregator(interval_seconds=60)
    degenerate = BarAggregator(interval_seconds=60)

    for minute in range(30):
        base_price = 100.0 + minute * 0.1
        # Real: several ticks per bar, spanning a range.
        for offset, price in ((0, base_price), (20, base_price + 2), (40, base_price - 2)):
            real.add_tick(_at(minute * 60 + offset), price)
        # Degenerate: one tick per bar, so high == low == close.
        degenerate.add_tick(_at(minute * 60), base_price)

    real_frame = real.frame()
    degen_frame = degenerate.frame()
    real_atr = compute_atr(real_frame["high"], real_frame["low"], real_frame["close"]).iloc[-1]
    degen_atr = compute_atr(degen_frame["high"], degen_frame["low"], degen_frame["close"]).iloc[-1]

    assert real_atr > degen_atr
    assert real_atr > 0


def test_crossing_a_boundary_closes_the_bar_and_returns_it():
    agg = BarAggregator(interval_seconds=60)
    agg.add_tick(_at(0), 100.0)
    agg.add_tick(_at(30), 105.0)

    closed = agg.add_tick(_at(61), 106.0)

    assert closed is not None
    assert (closed.open, closed.high, closed.low, closed.close) == (100.0, 105.0, 100.0, 105.0)
    assert agg.forming is not None
    assert agg.forming.open == 106.0


def test_a_closed_bar_does_not_change_afterwards():
    """A strategy acting on a returned bar must be able to trust it is final."""
    agg = BarAggregator(interval_seconds=60)
    agg.add_tick(_at(0), 100.0)
    closed = agg.add_tick(_at(61), 200.0)
    assert closed is not None
    snapshot = (closed.open, closed.high, closed.low, closed.close)

    agg.add_tick(_at(70), 300.0)
    agg.add_tick(_at(80), 50.0)

    assert (closed.open, closed.high, closed.low, closed.close) == snapshot


def test_boundaries_are_anchored_to_the_epoch_not_the_first_tick():
    """Two symbols that start streaming at different moments must still align,
    or every cross-sectional comparison comes from misaligned windows."""
    early = BarAggregator(interval_seconds=60)
    late = BarAggregator(interval_seconds=60)
    early.add_tick(_at(3), 100.0)
    late.add_tick(_at(47), 100.0)

    assert early.forming is not None and late.forming is not None
    assert early.forming.ts == late.forming.ts


def test_floor_to_interval_is_stable():
    assert floor_to_interval(_at(0), 60) == floor_to_interval(_at(59), 60)
    assert floor_to_interval(_at(60), 60) != floor_to_interval(_at(59), 60)


# --- Gap filling --------------------------------------------------------------


def test_quiet_intervals_are_filled_so_n_bars_span_n_intervals():
    """A sparse feed omits quiet minutes. Left alone, a 30-bar window would
    span far more than 30 real minutes."""
    agg = BarAggregator(interval_seconds=60)
    agg.add_tick(_at(0), 100.0)
    agg.add_tick(_at(300), 110.0)  # five minutes later, nothing in between

    frame = agg.frame(include_forming=False)
    assert len(frame) == 5  # the original bar plus four filled ones
    spans = frame["ts"].diff().dropna().dt.total_seconds().unique()
    assert list(spans) == [60.0]


def test_filled_bars_carry_the_price_forward_and_zero_the_volume():
    """Carrying volume forward would invent trades that never happened."""
    agg = BarAggregator(interval_seconds=60)
    agg.add_tick(_at(0), 100.0, volume=500.0)
    agg.add_tick(_at(180), 100.0, volume=10.0)

    filled = agg.frame(include_forming=False).iloc[1:]
    assert (filled["close"] == 100.0).all()
    assert (filled["open"] == 100.0).all()
    assert (filled["volume"] == 0.0).all()


# --- Ordering and trimming ----------------------------------------------------


def test_a_long_gap_is_treated_as_a_session_break_not_a_quiet_stretch():
    """An overnight close is not sixteen hours of flat trading. Filling it
    would invent ~960 bars that never existed."""
    agg = BarAggregator(interval_seconds=60, max_gap_fill_bars=10)
    agg.add_tick(_at(0), 100.0)
    agg.add_tick(_at(16 * 60 * 60), 105.0)  # next morning

    assert len(agg.frame(include_forming=False)) == 1


def test_the_gap_fill_bound_is_respected_exactly():
    at_limit = BarAggregator(interval_seconds=60, max_gap_fill_bars=5)
    at_limit.add_tick(_at(0), 100.0)
    at_limit.add_tick(_at(6 * 60), 100.0)  # 5 missing bars - filled
    assert len(at_limit.frame(include_forming=False)) == 6

    over_limit = BarAggregator(interval_seconds=60, max_gap_fill_bars=5)
    over_limit.add_tick(_at(0), 100.0)
    over_limit.add_tick(_at(7 * 60), 100.0)  # 6 missing bars - not filled
    assert len(over_limit.frame(include_forming=False)) == 1


def test_an_out_of_order_tick_is_dropped_rather_than_corrupting_a_closed_bar():
    agg = BarAggregator(interval_seconds=60)
    agg.add_tick(_at(0), 100.0)
    agg.add_tick(_at(120), 200.0)
    before = agg.frame(include_forming=False).copy()

    assert agg.add_tick(_at(30), 999.0) is None

    after = agg.frame(include_forming=False)
    assert after.equals(before)


def test_history_is_trimmed_to_max_bars():
    agg = BarAggregator(interval_seconds=60, max_bars=10)
    for minute in range(50):
        agg.add_tick(_at(minute * 60), 100.0 + minute)
    assert len(agg.completed_bars()) <= 10


# --- Frames -------------------------------------------------------------------


def test_an_empty_aggregator_yields_an_empty_but_well_formed_frame():
    frame = BarAggregator().frame()
    assert list(frame.columns) == ["ts", "open", "high", "low", "close", "volume"]
    assert frame.empty


def test_the_forming_bar_can_be_excluded():
    agg = BarAggregator(interval_seconds=60)
    agg.add_tick(_at(0), 100.0)
    agg.add_tick(_at(61), 105.0)

    assert len(agg.frame(include_forming=True)) == 2
    assert len(agg.frame(include_forming=False)) == 1


def test_a_non_positive_interval_is_rejected():
    with pytest.raises(ValueError, match="must be positive"):
        BarAggregator(interval_seconds=0)


# --- Multi-symbol -------------------------------------------------------------


def test_symbols_are_aggregated_independently():
    multi = MultiSymbolAggregator(interval_seconds=60)
    multi.add_tick("AAPL", _at(0), 100.0)
    multi.add_tick("MSFT", _at(0), 400.0)
    multi.add_tick("AAPL", _at(10), 110.0)

    assert multi.frame("AAPL")["high"].iloc[-1] == 110.0
    assert multi.frame("MSFT")["high"].iloc[-1] == 400.0
    assert sorted(multi.symbols()) == ["AAPL", "MSFT"]


def test_an_unseen_symbol_yields_an_empty_frame_rather_than_raising():
    assert MultiSymbolAggregator().frame("NOPE").empty


# --- prime_bar: the research harness has bars and no ticks (W2) ---------------


def _daily(ts: datetime, o: float, h: float, low: float, c: float) -> Bar:
    return Bar(ts=ts, open=o, high=h, low=low, close=c, volume=1000.0)


def _day(n: int) -> datetime:
    """A daily boundary. Anchored to the epoch, as floor_to_interval is."""
    return floor_to_interval(datetime(2026, 1, 5 + n, 12, 0, tzinfo=UTC), 86_400.0)


def test_prime_bar_installs_the_true_ohlc_as_the_forming_bar():
    agg = BarAggregator(interval_seconds=86_400.0)

    agg.prime_bar(_daily(_day(0), 100.0, 110.0, 90.0, 105.0))

    assert agg.forming is not None
    assert (agg.forming.high, agg.forming.low) == (110.0, 90.0)


def test_a_tick_at_the_close_folds_in_without_flattening_the_bar():
    """The whole reason this seam works. A daily close sits inside the day's
    range, so max(high, close) and min(low, close) are no-ops."""
    agg = BarAggregator(interval_seconds=86_400.0)
    agg.prime_bar(_daily(_day(0), 100.0, 110.0, 90.0, 105.0))

    agg.add_tick(_day(0) + timedelta(hours=1), 105.0)

    assert agg.forming is not None
    assert (agg.forming.high, agg.forming.low, agg.forming.close) == (110.0, 90.0, 105.0)


def test_priming_the_next_day_closes_the_previous_bar():
    agg = BarAggregator(interval_seconds=86_400.0)
    agg.prime_bar(_daily(_day(0), 100.0, 110.0, 90.0, 105.0))

    agg.prime_bar(_daily(_day(1), 105.0, 115.0, 104.0, 112.0))

    completed = agg.completed_bars()
    assert [b.high for b in completed] == [110.0]
    assert agg.forming is not None
    assert agg.forming.high == 115.0


def test_priming_out_of_order_raises_rather_than_corrupting_the_window():
    """The same rule seed() enforces: an older bar after a newer one silently
    corrupts every rolling window computed from the buffer."""
    agg = BarAggregator(interval_seconds=86_400.0)
    agg.prime_bar(_daily(_day(1), 105.0, 115.0, 104.0, 112.0))

    with pytest.raises(RuntimeError):
        agg.prime_bar(_daily(_day(0), 100.0, 110.0, 90.0, 105.0))


def test_priming_a_bar_that_is_not_on_a_boundary_raises():
    """A bar filed under the wrong boundary is a bar filed under the wrong
    day, which is the hazard as_utc exists to prevent."""
    agg = BarAggregator(interval_seconds=86_400.0)
    off_boundary = _daily(_day(0) + timedelta(hours=3), 100.0, 110.0, 90.0, 105.0)

    with pytest.raises(ValueError):
        agg.prime_bar(off_boundary)


def test_primed_bars_keep_a_real_atr_where_single_ticks_would_not():
    """The reason the seam exists at all, asserted rather than asserted about."""
    agg = MultiSymbolAggregator(interval_seconds=86_400.0)
    for n in range(20):
        base = 100.0 + n
        agg.prime_bar("AAA", _daily(_day(n), base, base + 3.0, base - 3.0, base + 1.0))

    atr = compute_atr(
        agg.frame("AAA")["high"], agg.frame("AAA")["low"], agg.frame("AAA")["close"], 14
    )
    assert float(atr.iloc[-1]) > 1.0, "a flattened bar would give an ATR near zero"

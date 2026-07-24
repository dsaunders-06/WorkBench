from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

import pandas as pd

from qat.data.fundamentals import FundamentalSnapshot, MockFundamentalsSource
from qat.domain.backtester.signal_adapter import generate_signal_series
from qat.domain.strategies.trend_following import TrendFollowingStrategy


def _bars(closes: list[float]) -> pd.DataFrame:
    n = len(closes)
    start = datetime(2022, 1, 1)
    ts = [start + timedelta(days=i) for i in range(n)]
    return pd.DataFrame(
        {
            "ts": ts,
            "open": closes,
            "high": [c * 1.01 for c in closes],
            "low": [c * 0.99 for c in closes],
            "close": closes,
            "volume": [1_000_000.0] * n,
        }
    )


def _fundamentals(symbol: str = "AAA") -> FundamentalSnapshot:
    return asyncio.run(MockFundamentalsSource(seed=1).get_fundamentals(symbol))


def test_no_look_ahead_mutating_future_bars_does_not_change_past_signal():
    fundamentals = _fundamentals()
    closes = [100.0 + i * 0.5 for i in range(220)]
    bars_original = _bars(closes)

    strategy = TrendFollowingStrategy(fast_window=50, slow_window=200)
    signals_full = generate_signal_series(strategy, "AAA", bars_original, fundamentals)

    mutated_closes = closes[:151] + [c * 5.0 for c in closes[151:]]
    bars_mutated = _bars(mutated_closes)
    signals_mutated = generate_signal_series(strategy, "AAA", bars_mutated, fundamentals)

    assert signals_full.iloc[150] == signals_mutated.iloc[150]
    assert signals_full.iloc[:151].equals(signals_mutated.iloc[:151])


def test_warm_up_period_has_zero_exposure():
    fundamentals = _fundamentals()
    bars = _bars([100.0] * 10)
    strategy = TrendFollowingStrategy(fast_window=50, slow_window=200)

    signals = generate_signal_series(strategy, "AAA", bars, fundamentals)

    assert (signals == 0.0).all()


def test_uptrend_eventually_produces_positive_exposure():
    fundamentals = _fundamentals()
    closes = [100.0 + i * 0.5 for i in range(220)]
    bars = _bars(closes)
    strategy = TrendFollowingStrategy(fast_window=50, slow_window=200)

    signals = generate_signal_series(strategy, "AAA", bars, fundamentals)

    assert signals.iloc[-1] > 0.0

from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

from qat.domain.backtester.costs import CostModel
from qat.domain.backtester.sizing import FixedFractionalSizer
from qat.domain.backtester.vectorized_engine import VectorizedBacktester


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


def test_flat_signal_series_never_opens_a_position():
    bars = _bars([100.0 + i * 0.1 for i in range(60)])
    signals = pd.Series([0.0] * len(bars), index=pd.DatetimeIndex(bars["ts"]))
    engine = VectorizedBacktester(CostModel(5.0, 5.0), FixedFractionalSizer(0.01, 2.5))

    result = engine.run("AAA", bars, signals)

    assert result.trades == []
    assert (result.equity_curve == engine.starting_equity).all()


def test_sustained_buy_signal_in_uptrend_produces_profit_after_costs():
    bars = _bars([100.0 + i * 0.5 for i in range(60)])
    signals = pd.Series([1.0] * len(bars), index=pd.DatetimeIndex(bars["ts"]))
    engine = VectorizedBacktester(CostModel(1.0, 1.0), FixedFractionalSizer(0.01, 2.5))

    result = engine.run("AAA", bars, signals)

    assert result.equity_curve.iloc[-1] > engine.starting_equity
    assert len(result.trades) >= 1


def test_zero_cost_guardrail_warning_fires():
    bars = _bars([100.0 + i * 0.5 for i in range(60)])
    signals = pd.Series([1.0] * len(bars), index=pd.DatetimeIndex(bars["ts"]))
    engine = VectorizedBacktester(CostModel(0.0, 0.0), FixedFractionalSizer(0.01, 2.5))

    result = engine.run("AAA", bars, signals)

    assert any("Zero-cost" in w for w in result.warnings)


def test_high_sharpe_guardrail_warning_fires():
    closes = [100.0]
    for factor in [1.02, 1.01] * 40:
        closes.append(closes[-1] * factor)
    bars = _bars(closes)
    signals = pd.Series([1.0] * len(bars), index=pd.DatetimeIndex(bars["ts"]))
    engine = VectorizedBacktester(CostModel(0.0, 0.0), FixedFractionalSizer(0.01, 2.5))

    result = engine.run("AAA", bars, signals)

    assert any("Sharpe ratio" in w for w in result.warnings)


def test_direction_flip_closes_and_reopens_position():
    closes = [100.0 + i * 0.5 for i in range(40)] + [120.0 - i * 0.5 for i in range(40)]
    bars = _bars(closes)
    signals = pd.Series([1.0] * 40 + [-1.0] * 40, index=pd.DatetimeIndex(bars["ts"]))
    engine = VectorizedBacktester(CostModel(1.0, 1.0), FixedFractionalSizer(0.01, 2.5))

    result = engine.run("AAA", bars, signals)

    assert len(result.trades) >= 2

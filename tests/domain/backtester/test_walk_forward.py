from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

from qat.domain.backtester.costs import CostModel
from qat.domain.backtester.sizing import FixedFractionalSizer
from qat.domain.backtester.vectorized_engine import VectorizedBacktester
from qat.domain.backtester.walk_forward import run_walk_forward


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


def test_windows_split_correctly_and_do_not_overlap():
    bars = _bars([100.0 + i * 0.2 for i in range(300)])
    signals = pd.Series([1.0] * len(bars), index=pd.DatetimeIndex(bars["ts"]))
    engine = VectorizedBacktester(CostModel(2.0, 2.0), FixedFractionalSizer(0.01, 2.5))

    result = run_walk_forward(engine, "AAA", bars, signals, in_sample_bars=100, out_sample_bars=50)

    assert len(result.windows) == 4
    for i in range(1, len(result.windows)):
        assert result.windows[i].out_sample_start > result.windows[i - 1].out_sample_end


def test_stability_report_has_expected_keys():
    bars = _bars([100.0 + i * 0.2 for i in range(300)])
    signals = pd.Series([1.0] * len(bars), index=pd.DatetimeIndex(bars["ts"]))
    engine = VectorizedBacktester(CostModel(2.0, 2.0), FixedFractionalSizer(0.01, 2.5))

    result = run_walk_forward(engine, "AAA", bars, signals, in_sample_bars=100, out_sample_bars=50)

    assert set(result.metric_stability) == {"sharpe_mean", "sharpe_std", "num_windows"}
    assert result.metric_stability["num_windows"] == 4.0


def test_insufficient_data_returns_no_windows():
    bars = _bars([100.0] * 50)
    signals = pd.Series([0.0] * len(bars), index=pd.DatetimeIndex(bars["ts"]))
    engine = VectorizedBacktester(CostModel(2.0, 2.0), FixedFractionalSizer(0.01, 2.5))

    result = run_walk_forward(engine, "AAA", bars, signals, in_sample_bars=100, out_sample_bars=50)

    assert result.windows == []
    assert result.metric_stability["num_windows"] == 0.0

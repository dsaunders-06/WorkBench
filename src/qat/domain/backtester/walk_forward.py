"""Walk-forward evaluation: rolling in-sample/out-of-sample windows,
reporting metric stability across windows to surface overfitting (spec §G).

The 15 strategies (M3) are rule-based with fixed parameters, not fitted to
data, so there is no in-sample "training" step to re-run per window - the
in-sample slice is bookkeeping only (it records what period preceded each
out-of-sample test); the meaningful work is comparing the same causal
backtest's metrics across independent, non-overlapping out-of-sample windows.
"""

from __future__ import annotations

import pandas as pd

from qat.domain.backtester.results import WalkForwardResult, WalkForwardWindow
from qat.domain.backtester.vectorized_engine import VectorizedBacktester


def run_walk_forward(
    engine: VectorizedBacktester,
    symbol: str,
    bars: pd.DataFrame,
    signal_series: pd.Series,
    in_sample_bars: int,
    out_sample_bars: int,
    benchmark_prices: pd.Series | None = None,
) -> WalkForwardResult:
    bars = bars.reset_index(drop=True)
    signal_series = signal_series.reset_index(drop=True)
    total = len(bars)
    windows: list[WalkForwardWindow] = []

    start = 0
    while start + in_sample_bars + out_sample_bars <= total:
        in_start, in_end = start, start + in_sample_bars
        out_start, out_end = in_end, in_end + out_sample_bars

        out_bars = bars.iloc[out_start:out_end].reset_index(drop=True)
        out_signals = signal_series.iloc[out_start:out_end].reset_index(drop=True)
        out_signals.index = pd.DatetimeIndex(out_bars["ts"])

        out_benchmark = None
        if benchmark_prices is not None:
            out_benchmark = benchmark_prices.reset_index(drop=True).iloc[out_start:out_end].copy()
            out_benchmark.index = pd.DatetimeIndex(out_bars["ts"])

        result = engine.run(symbol, out_bars, out_signals, out_benchmark)

        windows.append(
            WalkForwardWindow(
                in_sample_start=bars["ts"].iloc[in_start],
                in_sample_end=bars["ts"].iloc[in_end - 1],
                out_sample_start=bars["ts"].iloc[out_start],
                out_sample_end=bars["ts"].iloc[out_end - 1],
                out_sample_result=result,
            )
        )
        start += out_sample_bars

    sharpe_values = [w.out_sample_result.metrics.get("sharpe", 0.0) for w in windows]
    stability = {
        "sharpe_mean": sum(sharpe_values) / len(sharpe_values) if sharpe_values else 0.0,
        "sharpe_std": float(pd.Series(sharpe_values).std()) if len(sharpe_values) > 1 else 0.0,
        "num_windows": float(len(windows)),
    }

    return WalkForwardResult(windows=windows, metric_stability=stability)

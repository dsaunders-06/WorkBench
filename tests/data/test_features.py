from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
import pytest

from qat.data.features import (
    FeatureBuilder,
    compute_atr,
    compute_breadth,
    compute_cross_sectional_zscore,
    compute_returns,
    compute_trend,
)


def _bars(
    closes: list[float], highs: list[float] | None = None, lows: list[float] | None = None
) -> pd.DataFrame:
    n = len(closes)
    ts = [datetime(2024, 1, 1) + timedelta(days=i) for i in range(n)]
    highs = highs or [c + 1 for c in closes]
    lows = lows or [c - 1 for c in closes]
    return pd.DataFrame(
        {
            "ts": ts,
            "open": closes,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": [100.0] * n,
        }
    )


def _same(a: float, b: float) -> None:
    if pd.isna(a) and pd.isna(b):
        return
    assert a == pytest.approx(b)


def test_compute_returns_is_pct_change():
    df = _bars([100.0, 110.0, 121.0])
    returns = compute_returns(df["close"])
    assert returns.iloc[1] == pytest.approx(0.10)
    assert returns.iloc[2] == pytest.approx(0.10)


def test_compute_atr_matches_manual_true_range():
    df = _bars([100.0, 102.0, 101.0], highs=[101.0, 104.0, 103.0], lows=[99.0, 100.0, 99.0])
    atr = compute_atr(df["high"], df["low"], df["close"], window=2)
    # TR0 = 101-99 = 2; TR1 = max(104-100, |104-100|, |100-100|) = 4; ATR[1] = mean(2, 4) = 3
    assert atr.iloc[1] == pytest.approx(3.0)


def test_no_look_ahead_for_returns_atr_and_trend():
    closes = [100.0 + i + (50.0 if i == 35 else 0.0) for i in range(40)]
    df = _bars(closes)

    full_returns = compute_returns(df["close"])
    full_atr = compute_atr(df["high"], df["low"], df["close"])
    full_trend = compute_trend(df["close"], window=10)

    for t in (5, 10, 20, 30):
        truncated = df.iloc[: t + 1]
        _same(compute_returns(truncated["close"]).iloc[-1], full_returns.iloc[t])
        _same(
            compute_atr(truncated["high"], truncated["low"], truncated["close"]).iloc[-1],
            full_atr.iloc[t],
        )
        _same(compute_trend(truncated["close"], window=10).iloc[-1], full_trend.iloc[t])


def test_compute_breadth_is_fraction_above_sma():
    panel = pd.DataFrame(
        {
            "AAA": [10.0, 10.0, 10.0, 20.0],
            "BBB": [10.0, 10.0, 10.0, 5.0],
        }
    )
    breadth = compute_breadth(panel, window=3)
    # at the last row: SMA over prior 3 rows is 10 for both; AAA (20) above, BBB (5) below
    assert breadth.iloc[-1] == pytest.approx(0.5)


def test_compute_cross_sectional_zscore_has_zero_row_mean():
    panel = pd.DataFrame({"AAA": [1.0, 2.0, 4.0], "BBB": [3.0, 2.0, 1.0], "CCC": [2.0, 5.0, 3.0]})
    z = compute_cross_sectional_zscore(panel)
    for _, row in z.iterrows():
        assert row.mean() == pytest.approx(0.0, abs=1e-9)


def test_compute_cross_sectional_zscore_is_nan_for_zero_variance_row():
    panel = pd.DataFrame({"AAA": [2.0], "BBB": [2.0], "CCC": [2.0]})
    z = compute_cross_sectional_zscore(panel)
    assert z.iloc[0].isna().all()


def test_feature_builder_returns_expected_keys():
    df = _bars([float(100 + i) for i in range(30)])
    builder = FeatureBuilder(vol_window=5, atr_window=5, trend_window=5)

    features = builder.build(df)

    assert set(features) == {"return_1d", "realized_vol", "atr", "trend_pct_above_sma"}
    assert all(isinstance(v, float) for v in features.values())


def test_feature_builder_handles_short_history_without_raising():
    df = _bars([100.0, 101.0])
    builder = FeatureBuilder()

    features = builder.build(df)

    assert features["atr"] == 0.0  # not enough rows for the default 14-bar window

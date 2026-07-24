"""Central feature computation (spec §D/§17.1).

Every function here is computed once, centrally, and is strictly causal:
each value at row t is a function of rows <= t only (pandas rolling/pct_change
never look forward), so truncating a series at t and recomputing yields the
same value at t as computing over the full series - this is the point-in-time
guarantee the no-look-ahead test in tests/data/test_features.py checks for.

Single-symbol functions take/return plain Series; the two cross-sectional
functions take a "panel" DataFrame (index=ts, columns=symbol) since breadth
and factor z-scores are meaningful only across the universe at a point in time.
"""

from __future__ import annotations

import pandas as pd


def compute_returns(close: pd.Series) -> pd.Series:
    return close.pct_change()


def compute_realized_vol(
    returns: pd.Series, window: int = 20, periods_per_year: int = 252
) -> pd.Series:
    annualised: pd.Series = returns.rolling(window=window).std() * (periods_per_year**0.5)
    return annualised


def compute_atr(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 14) -> pd.Series:
    prev_close = close.shift(1)
    true_range = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return true_range.rolling(window=window).mean()


def compute_trend(close: pd.Series, window: int = 50) -> pd.Series:
    """Percentage distance of close from its rolling SMA - positive means
    trading above trend (spec §7/§9: price vs 200-day SMA gates Bull regime)."""
    sma = close.rolling(window=window).mean()
    return (close - sma) / sma


def compute_breadth(panel_close: pd.DataFrame, window: int = 50) -> pd.Series:
    """Fraction of symbols trading above their own rolling SMA, per timestamp."""
    sma = panel_close.rolling(window=window).mean()
    above = panel_close.gt(sma)
    return above.mean(axis=1)


def compute_cross_sectional_zscore(panel: pd.DataFrame) -> pd.DataFrame:
    """Per-timestamp (row-wise) z-score across symbols (columns) - the
    sector/factor standardisation described in spec §D."""
    row_mean = panel.mean(axis=1)
    row_std = panel.std(axis=1)
    return panel.sub(row_mean, axis=0).div(row_std, axis=0)


def _last_or_default(series: pd.Series, default: float = 0.0) -> float:
    if series.empty:
        return default
    value = series.iloc[-1]
    return default if pd.isna(value) else float(value)


class FeatureBuilder:
    """Builds the FeatureEvent payload for a single symbol from its bar
    history (columns: ts, open, high, low, close, volume; sorted ascending)."""

    def __init__(self, vol_window: int = 20, atr_window: int = 14, trend_window: int = 50) -> None:
        self.vol_window = vol_window
        self.atr_window = atr_window
        self.trend_window = trend_window

    def build(self, bars: pd.DataFrame) -> dict[str, float]:
        close = bars["close"]
        returns = compute_returns(close)
        return {
            "return_1d": _last_or_default(returns),
            "realized_vol": _last_or_default(compute_realized_vol(returns, self.vol_window)),
            "atr": _last_or_default(compute_atr(bars["high"], bars["low"], close, self.atr_window)),
            "trend_pct_above_sma": _last_or_default(compute_trend(close, self.trend_window)),
        }

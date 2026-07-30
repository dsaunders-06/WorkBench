"""Stationary feature matrix for the regime HMM (spec §E, paper §11.2):
log returns, realized vol, VIX level, yield-curve slope, credit spread, and
market breadth - the six features spec §E names explicitly.

Feature rows are built incrementally, one per benchmark bar, using
whatever macro values are currently known at that point (macro data arrives
less often than daily bars, so the latest known reading is effectively
forward-filled onto the bar timeline - a standard, documented practice).
Breadth defaults to a neutral 0.5 when fewer than two symbols are being
tracked for it, or before breadth_window bars have accumulated.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from qat.data.features import compute_breadth, compute_realized_vol, compute_returns

FEATURE_NAMES = (
    "log_return",
    "realized_vol",
    "vix_level",
    "yield_curve_slope",
    "credit_spread",
    "breadth",
)
_NEUTRAL_BREADTH = 0.5


@dataclass
class RegimeFeatureBuilder:
    vol_window: int = 20
    breadth_window: int = 50

    _closes: list[float] = field(default_factory=list)
    _breadth_panel: dict[str, list[float]] = field(default_factory=dict)
    _rows: list[list[float]] = field(default_factory=list)

    _vix: float = 0.0
    _yield_curve_slope: float = 0.0
    _credit_spread: float = 0.0

    def update_macro(self, series: str, value: float) -> None:
        if series == "VIXCLS":
            self._vix = value
        elif series == "T10Y3M":
            self._yield_curve_slope = value
        elif series == "BAA10Y":
            self._credit_spread = value

    def add_benchmark_bar(
        self, close: float, breadth_prices: dict[str, float] | None = None
    ) -> None:
        self._closes.append(close)
        if breadth_prices:
            for symbol, price in breadth_prices.items():
                self._breadth_panel.setdefault(symbol, []).append(price)

        if len(self._closes) < 2:
            row = [
                0.0,
                0.0,
                self._vix,
                self._yield_curve_slope,
                self._credit_spread,
                _NEUTRAL_BREADTH,
            ]
        else:
            closes = pd.Series(self._closes)
            prev_close = closes.iloc[-2]
            log_return = float(np.log(closes.iloc[-1] / prev_close)) if prev_close > 0 else 0.0
            vol_series = compute_realized_vol(compute_returns(closes), window=self.vol_window)
            last_vol = vol_series.iloc[-1]
            realized_vol = float(last_vol) if not pd.isna(last_vol) else 0.0

            breadth = self._current_breadth()

            row = [
                log_return,
                realized_vol,
                self._vix,
                self._yield_curve_slope,
                self._credit_spread,
                breadth,
            ]

        self._rows.append(row)

    def replace_latest_bar(
        self, close: float, breadth_prices: dict[str, float] | None = None
    ) -> None:
        """Rewrites the most recent row in place.

        A feature row is one bar, but ticks arrive many times inside a bar.
        Appending per tick would put four hundred intraday rows a day into a
        matrix seeded with daily ones, which is the timeframe mismatch M27a
        exists to remove; freezing the row at the day's first tick would make
        the regime blind to the session it is classifying. So the current bar's
        row is rebuilt as its price moves, and only rolls over at the boundary.
        """
        if not self._rows:
            self.add_benchmark_bar(close, breadth_prices)
            return

        length = len(self._closes)
        self._closes.pop()
        self._rows.pop()
        for prices in self._breadth_panel.values():
            if len(prices) == length:
                prices.pop()
        self.add_benchmark_bar(close, breadth_prices)

    def _current_breadth(self) -> float:
        # only symbols that have reported on every bar so far are aligned/usable
        aligned = {
            symbol: prices
            for symbol, prices in self._breadth_panel.items()
            if len(prices) == len(self._closes)
        }
        if len(aligned) < 2:
            return _NEUTRAL_BREADTH
        panel = pd.DataFrame(aligned)
        if len(panel) < self.breadth_window:
            return _NEUTRAL_BREADTH
        last_breadth = compute_breadth(panel, window=self.breadth_window).iloc[-1]
        return _NEUTRAL_BREADTH if pd.isna(last_breadth) else float(last_breadth)

    def latest_row(self) -> np.ndarray | None:
        if not self._rows:
            return None
        return np.array(self._rows[-1], dtype=float)

    def feature_matrix(self) -> np.ndarray:
        if not self._rows:
            return np.empty((0, len(FEATURE_NAMES)))
        return np.array(self._rows, dtype=float)

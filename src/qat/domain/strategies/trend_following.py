"""Trend Following: 50/200 SMA cross, spread-scaled conviction (paper §4.1).

Suitable regimes: Bear, High-Vol, Recession - paper-explicit ("crisis alpha",
Table 9.1 lead strategies).
"""

from __future__ import annotations

from typing import Any, Literal

import pandas as pd

from qat.domain.events import SignalEvent
from qat.domain.regime import Regime
from qat.domain.strategies.base import FeatureSnapshot


class TrendFollowingStrategy:
    name = "trend_following"

    def __init__(self, fast_window: int = 50, slow_window: int = 200) -> None:
        self.fast_window = fast_window
        self.slow_window = slow_window

    def suitable_regimes(self) -> set[Regime]:
        return {Regime.BEAR, Regime.HIGH_VOL, Regime.RECESSION}

    def params(self) -> dict[str, Any]:
        return {"fast_window": self.fast_window, "slow_window": self.slow_window}

    def on_features(self, snapshot: FeatureSnapshot) -> list[SignalEvent]:
        close = snapshot.context.bars["close"]
        if len(close) < self.slow_window:
            return []
        fast_sma = close.rolling(self.fast_window).mean().iloc[-1]
        slow_sma = close.rolling(self.slow_window).mean().iloc[-1]
        if pd.isna(fast_sma) or pd.isna(slow_sma) or slow_sma == 0:
            return []
        spread = (fast_sma - slow_sma) / slow_sma
        if spread == 0:
            return []
        side: Literal["buy", "sell"] = "buy" if spread > 0 else "sell"
        conviction = min(1.0, abs(spread) * 10)
        return [
            SignalEvent(
                symbol=snapshot.symbol,
                side=side,
                conviction=conviction,
                strategy=self.name,
                meta={"fast_sma": float(fast_sma), "slow_sma": float(slow_sma)},
                ts=snapshot.as_of,
            )
        ]

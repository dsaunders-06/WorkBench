"""Volatility: vol-target exposure overlay expressed as an equity buy/sell
signal - conviction scaled by the realised-vol z-score vs its own trailing
average (paper §4.12). Real options structures (iron condors, tail hedges)
are out of scope for SignalEvent's equity-style buy/sell model - a
documented simplification (M3 plan item 7).

Suitable regimes: Sideways, Low-Vol - paper-explicit vol-selling leads.
"""

from __future__ import annotations

from typing import Any, Literal

import pandas as pd

from qat.domain.events import SignalEvent
from qat.domain.regime import Regime
from qat.domain.strategies.base import FeatureSnapshot


class VolatilityStrategy:
    name = "volatility"

    def __init__(self, lookback: int = 60, z_threshold: float = 1.0) -> None:
        self.lookback = lookback
        self.z_threshold = z_threshold

    def suitable_regimes(self) -> set[Regime]:
        return {Regime.SIDEWAYS, Regime.LOW_VOL}

    def params(self) -> dict[str, Any]:
        return {"lookback": self.lookback, "z_threshold": self.z_threshold}

    def on_features(self, snapshot: FeatureSnapshot) -> list[SignalEvent]:
        current_vol = snapshot.context.technical.get("realized_vol")
        if current_vol is None or pd.isna(current_vol):
            return []
        close = snapshot.context.bars["close"]
        if len(close) < self.lookback + 20:
            return []
        returns = close.pct_change()
        rolling_vol = returns.rolling(20).std() * (252**0.5)
        history = rolling_vol.iloc[-self.lookback :].dropna()
        if len(history) < 20:
            return []
        mean_vol, std_vol = history.mean(), history.std()
        if std_vol == 0 or pd.isna(std_vol):
            return []
        z = (current_vol - mean_vol) / std_vol
        if abs(z) < self.z_threshold:
            return []

        # low relative vol -> favourable carry/vol-selling conditions -> increase exposure
        side: Literal["buy", "sell"] = "buy" if z < 0 else "sell"
        conviction = min(1.0, abs(z) / 3.0)
        return [
            SignalEvent(
                symbol=snapshot.symbol,
                side=side,
                conviction=conviction,
                strategy=self.name,
                meta={"vol_zscore": float(z), "mode": "vol_target_overlay"},
                ts=snapshot.as_of,
            )
        ]

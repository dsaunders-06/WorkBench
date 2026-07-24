"""Mean Reversion: short-horizon RSI(2-5) extremes (paper §4.9).

Suitable regimes: Sideways only - paper-explicit, and this strategy must be
disabled in strong-trend regimes (spec's explicit test requirement). Regime
gating alone is a coarse control, so on_features additionally suppresses
signals whenever the symbol's own trend feature is strong - defense in
depth, not solely relying on the engine having gated it correctly.
"""

from __future__ import annotations

from typing import Any, Literal

import pandas as pd

from qat.domain.events import SignalEvent
from qat.domain.regime import Regime
from qat.domain.strategies.base import FeatureSnapshot


def _rsi(close: pd.Series, window: int) -> float | None:
    delta = close.diff()
    gains = delta.clip(lower=0.0)
    losses = -delta.clip(upper=0.0)
    avg_gain = gains.rolling(window).mean().iloc[-1]
    avg_loss = losses.rolling(window).mean().iloc[-1]
    if pd.isna(avg_gain) or pd.isna(avg_loss):
        return None
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return float(100.0 - (100.0 / (1.0 + rs)))


class MeanReversionStrategy:
    name = "mean_reversion"

    def __init__(
        self,
        rsi_window: int = 3,
        oversold: float = 10.0,
        overbought: float = 90.0,
        strong_trend_threshold: float = 0.05,
    ) -> None:
        self.rsi_window = rsi_window
        self.oversold = oversold
        self.overbought = overbought
        self.strong_trend_threshold = strong_trend_threshold

    def suitable_regimes(self) -> set[Regime]:
        return {Regime.SIDEWAYS}

    def params(self) -> dict[str, Any]:
        return {
            "rsi_window": self.rsi_window,
            "oversold": self.oversold,
            "overbought": self.overbought,
            "strong_trend_threshold": self.strong_trend_threshold,
        }

    def on_features(self, snapshot: FeatureSnapshot) -> list[SignalEvent]:
        trend = abs(snapshot.context.technical.get("trend_pct_above_sma", 0.0))
        if trend >= self.strong_trend_threshold:
            return []  # strong trend: stays off regardless of the regime label

        rsi = _rsi(snapshot.context.bars["close"], self.rsi_window)
        if rsi is None:
            return []

        side: Literal["buy", "sell"]
        if rsi <= self.oversold:
            side = "buy"
        elif rsi >= self.overbought:
            side = "sell"
        else:
            return []

        conviction = min(1.0, abs(rsi - 50.0) / 50.0)
        return [
            SignalEvent(
                symbol=snapshot.symbol,
                side=side,
                conviction=conviction,
                strategy=self.name,
                meta={"rsi": rsi},
                ts=snapshot.as_of,
            )
        ]

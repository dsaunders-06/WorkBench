"""Breakout: Donchian N-day high breakout confirmed by expanding volume
(paper §4.11).

Suitable regimes: Bull - paper-explicit (the paper's avoid column excludes
this from Sideways/High-Vol).
"""

from __future__ import annotations

from typing import Any

from qat.domain.events import SignalEvent
from qat.domain.regime import Regime
from qat.domain.strategies.base import FeatureSnapshot


class BreakoutStrategy:
    name = "breakout"

    def __init__(self, channel_window: int = 20, volume_multiple: float = 1.5) -> None:
        self.channel_window = channel_window
        self.volume_multiple = volume_multiple

    def suitable_regimes(self) -> set[Regime]:
        return {Regime.BULL}

    def params(self) -> dict[str, Any]:
        return {"channel_window": self.channel_window, "volume_multiple": self.volume_multiple}

    def on_features(self, snapshot: FeatureSnapshot) -> list[SignalEvent]:
        bars = snapshot.context.bars
        if len(bars) < self.channel_window + 1:
            return []
        prior_high = bars["high"].iloc[-(self.channel_window + 1) : -1].max()
        last_close = bars["close"].iloc[-1]
        if last_close <= prior_high:
            return []
        avg_volume = bars["volume"].iloc[-(self.channel_window + 1) : -1].mean()
        last_volume = bars["volume"].iloc[-1]
        if avg_volume <= 0 or last_volume < avg_volume * self.volume_multiple:
            return []

        breakout_pct = (last_close - prior_high) / prior_high
        conviction = min(1.0, breakout_pct * 20)
        return [
            SignalEvent(
                symbol=snapshot.symbol,
                side="buy",
                conviction=conviction,
                strategy=self.name,
                meta={"stop_price": float(prior_high), "channel_high": float(prior_high)},
                ts=snapshot.as_of,
            )
        ]

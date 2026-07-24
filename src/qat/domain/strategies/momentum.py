"""Momentum: cross-sectional 12-1 month return, long the top decile (paper §4.2).

Suitable regimes: Bull, Low-Vol, Recovery - paper-explicit.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from qat.domain.events import SignalEvent
from qat.domain.regime import Regime
from qat.domain.strategies.base import FeatureSnapshot


class MomentumStrategy:
    name = "momentum"

    def __init__(
        self, lookback_days: int = 252, skip_days: int = 21, top_decile: float = 0.1
    ) -> None:
        self.lookback_days = lookback_days
        self.skip_days = skip_days
        self.top_decile = top_decile

    def suitable_regimes(self) -> set[Regime]:
        return {Regime.BULL, Regime.LOW_VOL, Regime.RECOVERY}

    def params(self) -> dict[str, Any]:
        return {
            "lookback_days": self.lookback_days,
            "skip_days": self.skip_days,
            "top_decile": self.top_decile,
        }

    def _trailing_return(self, close: pd.Series) -> float | None:
        needed = self.lookback_days + self.skip_days
        if len(close) < needed:
            return None
        start = close.iloc[-needed]
        end = close.iloc[-self.skip_days - 1] if self.skip_days > 0 else close.iloc[-1]
        if start == 0:
            return None
        return float(end / start - 1.0)

    def on_features(self, snapshot: FeatureSnapshot) -> list[SignalEvent]:
        scores: dict[str, float] = {}
        for symbol, context in snapshot.universe.items():
            score = self._trailing_return(context.bars["close"])
            if score is not None:
                scores[symbol] = score
        if snapshot.symbol not in scores or len(scores) < 2:
            return []

        ranked = sorted(scores.values())
        cutoff_index = max(0, int(len(ranked) * (1 - self.top_decile)) - 1)
        cutoff = ranked[cutoff_index]
        own_score = scores[snapshot.symbol]
        if own_score < cutoff:
            return []

        conviction = min(1.0, max(0.0, own_score))
        return [
            SignalEvent(
                symbol=snapshot.symbol,
                side="buy",
                conviction=conviction,
                strategy=self.name,
                meta={"trailing_return": own_score},
                ts=snapshot.as_of,
            )
        ]

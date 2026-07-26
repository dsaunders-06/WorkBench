"""Quality: cross-sectional composite of profitability (ROE, ROIC) and low
leverage, long the top quintile (paper §4.7).

Suitable regimes: Bear, High-Vol, Recession - paper-explicit.
"""

from __future__ import annotations

from typing import Any

from qat.data.fundamentals import FundamentalSnapshot
from qat.domain.events import SignalEvent
from qat.domain.regime import Regime
from qat.domain.strategies.base import FeatureSnapshot, unavailable

_REQUIRED = ("roe", "roic", "debt_to_equity")


class QualityStrategy:
    name = "quality"

    def __init__(self, top_quintile: float = 0.2) -> None:
        self.top_quintile = top_quintile

    def suitable_regimes(self) -> set[Regime]:
        return {Regime.BEAR, Regime.HIGH_VOL, Regime.RECESSION}

    def params(self) -> dict[str, Any]:
        return {"top_quintile": self.top_quintile}

    @staticmethod
    def _score(f: FundamentalSnapshot) -> float:
        # Non-None by construction: callers gate on _REQUIRED first.
        debt_to_equity = f.debt_to_equity or 0.0
        leverage_penalty = debt_to_equity / (1.0 + debt_to_equity)
        return (f.roe or 0.0) + (f.roic or 0.0) - leverage_penalty

    def on_features(self, snapshot: FeatureSnapshot) -> list[SignalEvent]:
        # A symbol with no published profitability is not low quality, it is
        # unmeasured - so it is left out of the ranking rather than scored at
        # the bottom of it.
        scores = {
            symbol: self._score(context.fundamentals)
            for symbol, context in snapshot.universe.items()
            if not unavailable(self.name, context, *_REQUIRED)
        }
        if snapshot.symbol not in scores or len(scores) < 2:
            return []

        ranked = sorted(scores.values(), reverse=True)
        cutoff_index = max(0, int(len(ranked) * self.top_quintile) - 1)
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
                meta={"quality_score": own_score},
                ts=snapshot.as_of,
            )
        ]

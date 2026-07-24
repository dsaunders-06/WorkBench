"""Dividend Growth: long streak of consecutive increases, payout covered by
FCF (paper §4.8).

Suitable regimes: Bear, Recession, Low-Vol - Bear/Recession are
paper-explicit ("dividend"); Low-Vol is inferred (paper's "carry" lead maps
to dividend income).
"""

from __future__ import annotations

from typing import Any

from qat.domain.events import SignalEvent
from qat.domain.regime import Regime
from qat.domain.strategies.base import FeatureSnapshot


class DividendGrowthStrategy:
    name = "dividend_growth"

    def __init__(self, min_streak_years: int = 10, max_payout_ratio: float = 0.75) -> None:
        self.min_streak_years = min_streak_years
        self.max_payout_ratio = max_payout_ratio

    def suitable_regimes(self) -> set[Regime]:
        return {Regime.BEAR, Regime.RECESSION, Regime.LOW_VOL}

    def params(self) -> dict[str, Any]:
        return {
            "min_streak_years": self.min_streak_years,
            "max_payout_ratio": self.max_payout_ratio,
        }

    def on_features(self, snapshot: FeatureSnapshot) -> list[SignalEvent]:
        f = snapshot.context.fundamentals
        passes = (
            f.dividend_growth_streak_years >= self.min_streak_years
            and f.payout_ratio <= self.max_payout_ratio
            and f.fcf_yield > 0
        )
        if not passes:
            return []
        conviction = min(1.0, f.dividend_growth_streak_years / 25.0)
        return [
            SignalEvent(
                symbol=snapshot.symbol,
                side="buy",
                conviction=conviction,
                strategy=self.name,
                meta={
                    "streak_years": f.dividend_growth_streak_years,
                    "payout_ratio": f.payout_ratio,
                },
                ts=snapshot.as_of,
            )
        ]

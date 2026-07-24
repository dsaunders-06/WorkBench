"""Growth: sustained EPS growth + ROIC quality overlay + valuation sanity cap
(paper §4.4).

Suitable regimes: Bull, Low-Vol - paper-explicit.
"""

from __future__ import annotations

from typing import Any

from qat.domain.events import SignalEvent
from qat.domain.regime import Regime
from qat.domain.strategies.base import FeatureSnapshot


class GrowthStrategy:
    name = "growth"

    def __init__(
        self, min_eps_growth: float = 0.15, min_roic: float = 0.10, max_peg: float = 3.0
    ) -> None:
        self.min_eps_growth = min_eps_growth
        self.min_roic = min_roic
        self.max_peg = max_peg

    def suitable_regimes(self) -> set[Regime]:
        return {Regime.BULL, Regime.LOW_VOL}

    def params(self) -> dict[str, Any]:
        return {
            "min_eps_growth": self.min_eps_growth,
            "min_roic": self.min_roic,
            "max_peg": self.max_peg,
        }

    def on_features(self, snapshot: FeatureSnapshot) -> list[SignalEvent]:
        f = snapshot.context.fundamentals
        passes = (
            f.eps_growth_yoy >= self.min_eps_growth
            and f.roic >= self.min_roic
            and 0 < f.peg_ratio <= self.max_peg
        )
        if not passes:
            return []
        conviction = min(1.0, f.eps_growth_yoy / 0.40)
        return [
            SignalEvent(
                symbol=snapshot.symbol,
                side="buy",
                conviction=conviction,
                strategy=self.name,
                meta={"eps_growth_yoy": f.eps_growth_yoy, "roic": f.roic},
                ts=snapshot.as_of,
            )
        ]

"""Growth: sustained EPS growth + ROIC quality overlay + valuation sanity cap
(paper §4.4).

Suitable regimes: Bull, Low-Vol - paper-explicit.
"""

from __future__ import annotations

from typing import Any

from qat.domain.events import SignalEvent
from qat.domain.regime import Regime
from qat.domain.strategies.base import FeatureSnapshot, unavailable

_REQUIRED = ("eps_growth_yoy", "roic", "peg_ratio")


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
        if unavailable(self.name, snapshot.context, *_REQUIRED):
            return []
        f = snapshot.context.fundamentals
        eps_growth, roic, peg = f.eps_growth_yoy, f.roic, f.peg_ratio
        if eps_growth is None or roic is None or peg is None:
            return []  # unreachable after the guard; narrows the optionals

        passes = (
            eps_growth >= self.min_eps_growth and roic >= self.min_roic and 0 < peg <= self.max_peg
        )
        if not passes:
            return []
        conviction = min(1.0, eps_growth / 0.40)
        return [
            SignalEvent(
                symbol=snapshot.symbol,
                side="buy",
                conviction=conviction,
                strategy=self.name,
                meta={"eps_growth_yoy": eps_growth, "roic": roic},
                ts=snapshot.as_of,
            )
        ]

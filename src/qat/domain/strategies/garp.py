"""GARP (Growth At a Reasonable Price): PEG 0-1.5, EPS growth 10-20%, ROE
floor, leverage cap (paper §4.6).

Not explicitly in the paper's regime table (a growth/value blend) -
suitable regimes inferred as Bull+Recovery.
"""

from __future__ import annotations

from typing import Any

from qat.domain.events import SignalEvent
from qat.domain.regime import Regime
from qat.domain.strategies.base import FeatureSnapshot, unavailable

_REQUIRED = ("peg_ratio", "eps_growth_yoy", "roe", "debt_to_equity")


class GarpStrategy:
    name = "garp"

    def __init__(
        self,
        max_peg: float = 1.5,
        min_eps_growth: float = 0.10,
        max_eps_growth: float = 0.20,
        min_roe: float = 0.10,
        max_debt_to_equity: float = 1.5,
    ) -> None:
        self.max_peg = max_peg
        self.min_eps_growth = min_eps_growth
        self.max_eps_growth = max_eps_growth
        self.min_roe = min_roe
        self.max_debt_to_equity = max_debt_to_equity

    def suitable_regimes(self) -> set[Regime]:
        return {Regime.BULL, Regime.RECOVERY}

    def params(self) -> dict[str, Any]:
        return {
            "max_peg": self.max_peg,
            "min_eps_growth": self.min_eps_growth,
            "max_eps_growth": self.max_eps_growth,
            "min_roe": self.min_roe,
            "max_debt_to_equity": self.max_debt_to_equity,
        }

    def on_features(self, snapshot: FeatureSnapshot) -> list[SignalEvent]:
        if unavailable(self.name, snapshot.context, *_REQUIRED):
            return []
        f = snapshot.context.fundamentals
        peg, eps_growth, roe, leverage = f.peg_ratio, f.eps_growth_yoy, f.roe, f.debt_to_equity
        if peg is None or eps_growth is None or roe is None or leverage is None:
            return []  # unreachable after the guard; narrows the optionals

        passes = (
            0 < peg <= self.max_peg
            and self.min_eps_growth <= eps_growth <= self.max_eps_growth
            and roe >= self.min_roe
            and leverage <= self.max_debt_to_equity
        )
        if not passes:
            return []
        conviction = min(1.0, (self.max_peg - peg) / self.max_peg)
        return [
            SignalEvent(
                symbol=snapshot.symbol,
                side="buy",
                conviction=conviction,
                strategy=self.name,
                meta={"peg_ratio": peg, "eps_growth_yoy": eps_growth},
                ts=snapshot.as_of,
            )
        ]

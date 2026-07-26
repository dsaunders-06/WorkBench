"""Value: cross-sectional cheapness composite (book/market, earnings yield,
EV/EBIT inverted, FCF yield) with a quality floor to avoid value traps
(paper §4.5).

Suitable regimes: Recovery, Sideways - Recovery is paper-explicit; Sideways
is a reasonable inference (range-bound accumulation of cheap names).
"""

from __future__ import annotations

from typing import Any

from qat.data.fundamentals import FundamentalSnapshot
from qat.domain.events import SignalEvent
from qat.domain.regime import Regime
from qat.domain.strategies.base import FeatureSnapshot, unavailable

# Every term of the cheapness composite plus the quality floor. EV/EBIT is not
# required: _cheapness already treats a missing one as contributing nothing,
# which is a defensible reading of "no enterprise value published".
_REQUIRED = ("roic", "book_to_market", "earnings_yield", "fcf_yield")


class ValueStrategy:
    name = "value"

    def __init__(self, top_quintile: float = 0.2, min_roic: float = 0.05) -> None:
        self.top_quintile = top_quintile
        self.min_roic = min_roic

    def suitable_regimes(self) -> set[Regime]:
        return {Regime.RECOVERY, Regime.SIDEWAYS}

    def params(self) -> dict[str, Any]:
        return {"top_quintile": self.top_quintile, "min_roic": self.min_roic}

    @staticmethod
    def _cheapness(f: FundamentalSnapshot) -> float:
        inverse_ev_ebit = 1.0 / f.ev_to_ebit if f.ev_to_ebit else 0.0
        # Non-None by construction: callers gate on _REQUIRED first.
        return (
            (f.book_to_market or 0.0)
            + (f.earnings_yield or 0.0)
            + (f.fcf_yield or 0.0)
            + inverse_ev_ebit
        )

    def on_features(self, snapshot: FeatureSnapshot) -> list[SignalEvent]:
        scores: dict[str, float] = {}
        for symbol, context in snapshot.universe.items():
            # A symbol we cannot value is excluded from the ranking entirely,
            # rather than scored as if it were expensive. Ranking it at zero
            # would let a genuinely cheap company be beaten by an ETF that has
            # no book value to compare.
            if unavailable(self.name, context, *_REQUIRED):
                continue
            roic = context.fundamentals.roic
            if roic is not None and roic >= self.min_roic:
                scores[symbol] = self._cheapness(context.fundamentals)
        if snapshot.symbol not in scores or len(scores) < 2:
            return []

        ranked = sorted(scores.values(), reverse=True)  # higher score = cheaper
        cutoff_index = max(0, int(len(ranked) * self.top_quintile) - 1)
        cutoff = ranked[cutoff_index]
        own_score = scores[snapshot.symbol]
        if own_score < cutoff:
            return []

        conviction = min(1.0, max(0.0, own_score / 2.0))
        return [
            SignalEvent(
                symbol=snapshot.symbol,
                side="buy",
                conviction=conviction,
                strategy=self.name,
                meta={"cheapness_score": own_score},
                ts=snapshot.as_of,
            )
        ]

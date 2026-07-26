"""Multi-Factor (recommended core): cross-sectional composite of value,
momentum, quality and low-volatility z-scores, long the top-ranked names
(paper §4.15). Always active regardless of regime - a mild regime scalar is
applied only downstream (risk engine, M6), never factor timing here.

Suitable regimes: all seven - paper-explicit ("mild regime scalar only, no
factor timing"); this is the one strategy the spec requires to always run.
"""

from __future__ import annotations

from typing import Any

from qat.domain.events import SignalEvent
from qat.domain.regime import ALL_REGIMES, Regime
from qat.domain.strategies.base import FeatureSnapshot, unavailable

# The fundamental half of the composite. Momentum and low-vol come from price
# and are always computable, so they are not gated here.
_REQUIRED = ("book_to_market", "earnings_yield", "fcf_yield", "roe", "roic", "debt_to_equity")


class MultiFactorStrategy:
    name = "multi_factor"

    def __init__(self, top_quintile: float = 0.2) -> None:
        self.top_quintile = top_quintile

    def suitable_regimes(self) -> set[Regime]:
        return set(ALL_REGIMES)

    def params(self) -> dict[str, Any]:
        return {"top_quintile": self.top_quintile}

    @staticmethod
    def _zscore(values: dict[str, float]) -> dict[str, float]:
        if len(values) < 2:
            return dict.fromkeys(values, 0.0)
        mean = sum(values.values()) / len(values)
        variance = sum((v - mean) ** 2 for v in values.values()) / len(values)
        std = variance**0.5
        if std == 0:
            return dict.fromkeys(values, 0.0)
        return {symbol: (v - mean) / std for symbol, v in values.items()}

    def on_features(self, snapshot: FeatureSnapshot) -> list[SignalEvent]:
        value_raw: dict[str, float] = {}
        momentum_raw: dict[str, float] = {}
        quality_raw: dict[str, float] = {}
        low_vol_raw: dict[str, float] = {}

        # Only symbols whose fundamental factors are all available can be
        # ranked. Letting an unmeasurable symbol through would give it the
        # z-score mean on two of the four factors - a placeholder competing on
        # equal terms with a measurement, and invisible in the output.
        eligible = {
            symbol: context
            for symbol, context in snapshot.universe.items()
            if not unavailable(self.name, context, *_REQUIRED)
        }
        if snapshot.symbol not in eligible:
            return []

        for symbol, context in eligible.items():
            f = context.fundamentals
            value_raw[symbol] = (
                (f.book_to_market or 0.0) + (f.earnings_yield or 0.0) + (f.fcf_yield or 0.0)
            )
            leverage = f.debt_to_equity or 0.0
            quality_raw[symbol] = (f.roe or 0.0) + (f.roic or 0.0) - leverage / (1.0 + leverage)
            momentum = context.technical.get("return_1d")
            vol = context.technical.get("realized_vol")
            if momentum is not None:
                momentum_raw[symbol] = momentum
            if vol is not None:
                low_vol_raw[symbol] = -vol  # invert: lower vol is better

        value_z = self._zscore(value_raw)
        momentum_z = self._zscore(momentum_raw)
        quality_z = self._zscore(quality_raw)
        low_vol_z = self._zscore(low_vol_raw)

        composite: dict[str, float] = {}
        for symbol in eligible:
            parts = [z.get(symbol, 0.0) for z in (value_z, momentum_z, quality_z, low_vol_z)]
            composite[symbol] = sum(parts) / len(parts)

        if snapshot.symbol not in composite or len(composite) < 2:
            return []
        ranked = sorted(composite.values(), reverse=True)
        cutoff_index = max(0, int(len(ranked) * self.top_quintile) - 1)
        cutoff = ranked[cutoff_index]
        own_score = composite[snapshot.symbol]
        if own_score < cutoff:
            return []

        conviction = min(1.0, max(0.0, (own_score + 2.0) / 4.0))
        return [
            SignalEvent(
                symbol=snapshot.symbol,
                side="buy",
                conviction=conviction,
                strategy=self.name,
                meta={"composite_score": own_score},
                ts=snapshot.as_of,
            )
        ]

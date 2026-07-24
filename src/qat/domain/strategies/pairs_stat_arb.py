"""Pairs/Stat-Arb: rolling-correlation partner search + spread z-score entry
(paper §4.13). Uses a correlation-based proxy rather than a formal
Engle-Granger cointegration test (statsmodels isn't a dependency yet) - a
documented simplification (M3 plan item 7).

Suitable regimes: Sideways, High-Vol - paper-explicit ("market-neutral pairs").
"""

from __future__ import annotations

from typing import Any, Literal

import pandas as pd

from qat.domain.events import SignalEvent
from qat.domain.regime import Regime
from qat.domain.strategies.base import FeatureSnapshot


class PairsStatArbStrategy:
    name = "pairs_stat_arb"

    def __init__(
        self, lookback: int = 60, entry_z: float = 2.0, min_correlation: float = 0.7
    ) -> None:
        self.lookback = lookback
        self.entry_z = entry_z
        self.min_correlation = min_correlation

    def suitable_regimes(self) -> set[Regime]:
        return {Regime.SIDEWAYS, Regime.HIGH_VOL}

    def params(self) -> dict[str, Any]:
        return {
            "lookback": self.lookback,
            "entry_z": self.entry_z,
            "min_correlation": self.min_correlation,
        }

    def _find_partner(self, snapshot: FeatureSnapshot) -> tuple[str, pd.Series, float] | None:
        own_close = snapshot.context.bars["close"]
        if len(own_close) < self.lookback:
            return None
        own_window = own_close.iloc[-self.lookback :].reset_index(drop=True)

        best: tuple[str, pd.Series, float] | None = None
        for symbol, context in snapshot.universe.items():
            if symbol == snapshot.symbol:
                continue
            other_close = context.bars["close"]
            if len(other_close) < self.lookback:
                continue
            other_window = other_close.iloc[-self.lookback :].reset_index(drop=True)
            correlation = own_window.corr(other_window)
            if pd.isna(correlation) or correlation < self.min_correlation:
                continue
            if best is None or correlation > best[2]:
                best = (symbol, other_window, float(correlation))
        return best

    def on_features(self, snapshot: FeatureSnapshot) -> list[SignalEvent]:
        partner = self._find_partner(snapshot)
        if partner is None:
            return []
        partner_symbol, partner_close, correlation = partner

        own_close = snapshot.context.bars["close"].iloc[-self.lookback :].reset_index(drop=True)
        spread = own_close - partner_close
        mean_spread, std_spread = spread.mean(), spread.std()
        if std_spread == 0 or pd.isna(std_spread):
            return []
        z = (spread.iloc[-1] - mean_spread) / std_spread
        if abs(z) < self.entry_z:
            return []

        side: Literal["buy", "sell"] = "sell" if z > 0 else "buy"  # spread too rich -> sell it
        conviction = min(1.0, abs(z) / 4.0)
        return [
            SignalEvent(
                symbol=snapshot.symbol,
                side=side,
                conviction=conviction,
                strategy=self.name,
                meta={
                    "partner_symbol": partner_symbol,
                    "spread_zscore": float(z),
                    "correlation": correlation,
                },
                ts=snapshot.as_of,
            )
        ]

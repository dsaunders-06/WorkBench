"""CAN SLIM: EPS growth + acceleration, RS>=80, near 52-week high, ownership
floor, uptrend filter (paper §4.3).

Suitable regimes: Bull, Recovery - paper-explicit.

Simplifications (M3 plan item 7): "rising" institutional ownership is
approximated as a point-in-time floor (no ownership-trend history tracked
yet); the market-uptrend filter uses the symbol's own trend feature as a
proxy for a broader market-index confirmation (no separate index feed wired).
"""

from __future__ import annotations

from typing import Any

from qat.domain.events import SignalEvent
from qat.domain.regime import Regime
from qat.domain.strategies.base import FeatureSnapshot, unavailable

_REQUIRED = (
    "eps_growth_yoy",
    "eps_growth_accelerating",
    "relative_strength_rank",
    "institutional_ownership_pct",
)


class CanSlimStrategy:
    name = "can_slim"

    def __init__(
        self,
        min_eps_growth: float = 0.20,
        min_rs_rank: float = 80.0,
        max_pct_below_52w_high: float = 0.10,
        min_institutional_ownership: float = 0.20,
    ) -> None:
        self.min_eps_growth = min_eps_growth
        self.min_rs_rank = min_rs_rank
        self.max_pct_below_52w_high = max_pct_below_52w_high
        self.min_institutional_ownership = min_institutional_ownership

    def suitable_regimes(self) -> set[Regime]:
        return {Regime.BULL, Regime.RECOVERY}

    def params(self) -> dict[str, Any]:
        return {
            "min_eps_growth": self.min_eps_growth,
            "min_rs_rank": self.min_rs_rank,
            "max_pct_below_52w_high": self.max_pct_below_52w_high,
            "min_institutional_ownership": self.min_institutional_ownership,
        }

    def on_features(self, snapshot: FeatureSnapshot) -> list[SignalEvent]:
        context = snapshot.context
        if unavailable(self.name, context, *_REQUIRED):
            return []
        fundamentals = context.fundamentals
        eps_growth = fundamentals.eps_growth_yoy
        accelerating = fundamentals.eps_growth_accelerating
        rs_rank = fundamentals.relative_strength_rank
        ownership = fundamentals.institutional_ownership_pct
        if eps_growth is None or accelerating is None or rs_rank is None or ownership is None:
            return []  # unreachable after the guard; narrows the optionals

        close = context.bars["close"]
        if len(close) < 2:
            return []

        window = min(len(close), 252)
        high_52w = close.iloc[-window:].max()
        last_close = close.iloc[-1]
        if high_52w <= 0:
            return []
        pct_below_high = (high_52w - last_close) / high_52w

        market_uptrend = context.technical.get("trend_pct_above_sma", 0.0) > 0.0

        passes = (
            eps_growth >= self.min_eps_growth
            and accelerating
            and rs_rank >= self.min_rs_rank
            and pct_below_high <= self.max_pct_below_52w_high
            and ownership >= self.min_institutional_ownership
            and market_uptrend
        )
        if not passes:
            return []

        conviction = min(1.0, rs_rank / 100.0)
        return [
            SignalEvent(
                symbol=snapshot.symbol,
                side="buy",
                conviction=conviction,
                strategy=self.name,
                meta={
                    "eps_growth_yoy": eps_growth,
                    "rs_rank": rs_rank,
                    "pct_below_52w_high": pct_below_high,
                },
                ts=snapshot.as_of,
            )
        ]

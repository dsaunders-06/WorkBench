"""Swing Trading: pullback-to-EMA20-then-reclaim in an EMA20>EMA50 uptrend,
ATR-based stop/target proposed in signal metadata (paper §4.10).

Suitable regimes: Sideways - paper-explicit.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from qat.data.features import compute_atr
from qat.domain.events import SignalEvent
from qat.domain.regime import Regime
from qat.domain.strategies.base import FeatureSnapshot


class SwingStrategy:
    name = "swing"

    def __init__(
        self,
        fast_window: int = 20,
        slow_window: int = 50,
        atr_window: int = 14,
        atr_stop_multiple: float = 2.5,
        reward_risk: float = 2.0,
    ) -> None:
        self.fast_window = fast_window
        self.slow_window = slow_window
        self.atr_window = atr_window
        self.atr_stop_multiple = atr_stop_multiple
        self.reward_risk = reward_risk

    def suitable_regimes(self) -> set[Regime]:
        return {Regime.SIDEWAYS}

    def params(self) -> dict[str, Any]:
        return {
            "fast_window": self.fast_window,
            "slow_window": self.slow_window,
            "atr_window": self.atr_window,
            "atr_stop_multiple": self.atr_stop_multiple,
            "reward_risk": self.reward_risk,
        }

    def on_features(self, snapshot: FeatureSnapshot) -> list[SignalEvent]:
        bars = snapshot.context.bars
        if len(bars) < max(self.slow_window, self.atr_window) + 2:
            return []
        close = bars["close"]
        ema_fast = close.ewm(span=self.fast_window, adjust=False).mean()
        ema_slow = close.ewm(span=self.slow_window, adjust=False).mean()
        in_uptrend = ema_fast.iloc[-1] > ema_slow.iloc[-1]

        # --- Exit first (M14) ------------------------------------------------
        # A held position is asked a different question than an empty one: not
        # "is this a good entry" but "does the reason I am holding still hold".
        # Checked before the entry logic and on the *bare* crossover with no
        # minimum-gap buffer, because the costly error differs by direction -
        # a marginally-false exit gives up some upside, a marginally-late exit
        # keeps a broken position. Being quick to protect is the safer error.
        held = snapshot.held_quantity()
        if held > 0:
            if not in_uptrend:
                return [
                    SignalEvent(
                        symbol=snapshot.symbol,
                        side="sell",
                        conviction=1.0,
                        strategy=self.name,
                        meta={
                            "exit_reason": "trend_broken",
                            "ema_fast": float(ema_fast.iloc[-1]),
                            "ema_slow": float(ema_slow.iloc[-1]),
                        },
                        ts=snapshot.as_of,
                    )
                ]
            # Still trending: hold. The resting broker stop and the take-profit
            # attached at entry handle the other two ways out of this position.
            return []

        if not in_uptrend:
            return []  # not in an uptrend

        prior_close, prior_fast = close.iloc[-2], ema_fast.iloc[-2]
        last_close, last_fast = close.iloc[-1], ema_fast.iloc[-1]
        pulled_back = prior_close <= prior_fast
        reclaimed = last_close > last_fast
        if not (pulled_back and reclaimed):
            return []

        atr = compute_atr(bars["high"], bars["low"], close, self.atr_window).iloc[-1]
        if pd.isna(atr) or atr <= 0:
            return []
        stop_price = float(last_close - self.atr_stop_multiple * atr)
        risk = last_close - stop_price
        target_price = float(last_close + self.reward_risk * risk)
        conviction = min(1.0, max(0.1, (last_close - last_fast) / last_fast * 20))

        return [
            SignalEvent(
                symbol=snapshot.symbol,
                side="buy",
                conviction=conviction,
                strategy=self.name,
                meta={"stop_price": stop_price, "target_price": target_price, "atr": float(atr)},
                ts=snapshot.as_of,
            )
        ]

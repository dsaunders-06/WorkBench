"""Swing Trading: pullback-to-EMA20-then-reclaim in an EMA20>EMA50 uptrend,
ATR-based stop/target proposed in signal metadata (paper §4.10).

Suitable regimes: Sideways, Bull, Low-Vol, Recovery. The paper names Sideways
alone, and this deliberately departs from it - see suitable_regimes below for
the measurement that prompted it and the operator decision that authorised it.
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
        """Widened from the paper's Sideways-only, 30 July 2026, by operator
        decision - the one change here that alters which trades happen.

        Measured over the 300 real sessions ending 29 July 2026, the regime
        engine classified Sideways on 6.2% of them: bull 32.0%, bear 26.6%,
        high-vol 24.9%, low-vol 10.4%, sideways 6.2%. So the only promoted
        strategy in the system was eligible about one session in sixteen, and
        the zero-signal sessions of 28 and 29 July were the ordinary case
        rather than an anomaly.

        A pullback to EMA20 inside an EMA20>EMA50 uptrend is a trend-continuation
        setup, and its own entry condition already requires the uptrend. Bull and
        Low-Vol - "calm, often trending" in paper §9.1 - are where that setup
        most naturally lives, so excluding them gated the strategy out of the
        regimes it was designed for. Recovery joins them for coherence with
        Momentum's risk-on set; it did not occur once in the measured window,
        so it changes nothing empirically.

        Bear, High-Vol and Recession stay excluded: buying a pullback long-only
        into those is knife-catching, and it is the half of the gate worth
        keeping.

        Note that the exposure scalar travels with the label - Bull and Low-Vol
        are 1.0 against Sideways' 0.7 - so this widens position size as well as
        eligibility.
        """
        return {Regime.SIDEWAYS, Regime.BULL, Regime.LOW_VOL, Regime.RECOVERY}

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

"""Drives a single-symbol-compatible M3 Strategy bar-by-bar to produce a
target-exposure series for the vectorized engine (spec §G).

At each bar i, the strategy only ever sees bars[:i+1] (and a
single-symbol universe of just itself) - this is what makes the no-look-ahead
property in test_signal_adapter.py checkable: mutating bars after i must
never change the signal computed at i.

Cross-sectional strategies (Momentum, Value, Quality, Pairs, Sector Rotation,
Multi-Factor) need real peers in the universe and will simply emit no
signal here (target exposure stays 0) - multi-asset backtesting is a
documented future extension, not a bug in this adapter.
"""

from __future__ import annotations

import pandas as pd

from qat.data.features import FeatureBuilder
from qat.data.fundamentals import FundamentalSnapshot
from qat.domain.strategies.base import FeatureSnapshot, Strategy, SymbolContext


def generate_signal_series(
    strategy: Strategy,
    symbol: str,
    bars: pd.DataFrame,
    fundamentals: FundamentalSnapshot,
    feature_builder: FeatureBuilder | None = None,
    min_history: int = 2,
) -> pd.Series:
    feature_builder = feature_builder or FeatureBuilder()
    bars = bars.reset_index(drop=True)

    exposures: list[float] = []
    current_exposure = 0.0
    for i in range(len(bars)):
        if i + 1 < min_history:
            exposures.append(current_exposure)
            continue

        history = bars.iloc[: i + 1]
        technical = feature_builder.build(history)
        context = SymbolContext(
            symbol=symbol, bars=history, technical=technical, fundamentals=fundamentals
        )
        snapshot = FeatureSnapshot(
            symbol=symbol,
            as_of=history["ts"].iloc[-1],
            context=context,
            universe={symbol: context},
        )
        signals = strategy.on_features(snapshot)
        if signals:
            signal = signals[0]
            current_exposure = signal.conviction if signal.side == "buy" else -signal.conviction
        exposures.append(current_exposure)

    return pd.Series(exposures, index=pd.DatetimeIndex(bars["ts"]), name="target_exposure")

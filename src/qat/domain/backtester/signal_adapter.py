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

**Long-only, because the live system is** (M33). A sell signal used to map to
MINUS conviction - a short - and it means close the position: swing's carries
`exit_reason=trend_broken`. Measured on AAPL, mean_reversion spent 48% of the
series short and volatility 45%, while the live OMS submits buys and
sells-to-close only and has no path to opening a short at all.

So the backtester was measuring a book this system is structurally incapable
of holding, and the promotion gate was reading the result. A backtest whose
answer cannot be acted on is worse than no backtest: it is an answer to a
question nobody asked, presented beside answers that are real.
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
            # Flat on a sell, not short. See the module docstring: this is what
            # the live OMS can actually do with the signal.
            current_exposure = signal.conviction if signal.side == "buy" else 0.0
        exposures.append(current_exposure)

    return pd.Series(exposures, index=pd.DatetimeIndex(bars["ts"]), name="target_exposure")

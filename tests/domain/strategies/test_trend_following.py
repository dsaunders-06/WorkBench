from __future__ import annotations

from _helpers import make_context, make_snapshot

from qat.domain.regime import Regime
from qat.domain.strategies.trend_following import TrendFollowingStrategy


def test_suitable_regimes():
    strat = TrendFollowingStrategy()
    assert strat.suitable_regimes() == {Regime.BEAR, Regime.HIGH_VOL, Regime.RECESSION}


def test_uptrend_emits_buy():
    closes = [100.0 + i * 0.5 for i in range(220)]
    universe = {"AAA": make_context("AAA", closes)}
    snapshot = make_snapshot("AAA", universe)

    signals = TrendFollowingStrategy(fast_window=50, slow_window=200).on_features(snapshot)

    assert len(signals) == 1
    assert signals[0].side == "buy"


def test_downtrend_emits_sell():
    closes = [200.0 - i * 0.5 for i in range(220)]
    universe = {"AAA": make_context("AAA", closes)}
    snapshot = make_snapshot("AAA", universe)

    signals = TrendFollowingStrategy(fast_window=50, slow_window=200).on_features(snapshot)

    assert len(signals) == 1
    assert signals[0].side == "sell"


def test_insufficient_history_emits_nothing():
    universe = {"AAA": make_context("AAA", [100.0] * 10)}
    snapshot = make_snapshot("AAA", universe)

    assert TrendFollowingStrategy().on_features(snapshot) == []

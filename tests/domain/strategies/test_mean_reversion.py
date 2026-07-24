from __future__ import annotations

from _helpers import make_context, make_snapshot

from qat.domain.regime import Regime
from qat.domain.strategies.mean_reversion import MeanReversionStrategy


def test_suitable_regimes():
    assert MeanReversionStrategy().suitable_regimes() == {Regime.SIDEWAYS}


def test_oversold_bounce_emits_buy_in_ranging_market():
    closes = [100.0] * 30 + [95.0, 90.0, 85.0]
    universe = {"AAA": make_context("AAA", closes)}
    snapshot = make_snapshot("AAA", universe)

    signals = MeanReversionStrategy(rsi_window=3).on_features(snapshot)

    assert len(signals) == 1
    assert signals[0].side == "buy"


def test_disabled_when_trend_is_strong_even_if_rsi_extreme():
    closes = [100.0 + i * 2.0 for i in range(60)]
    universe = {"AAA": make_context("AAA", closes)}
    snapshot = make_snapshot("AAA", universe)

    signals = MeanReversionStrategy(strong_trend_threshold=0.05).on_features(snapshot)

    assert signals == []

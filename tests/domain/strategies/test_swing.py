from __future__ import annotations

from _helpers import make_context, make_snapshot

from qat.domain.regime import Regime
from qat.domain.strategies.swing import SwingStrategy


def test_suitable_regimes():
    assert SwingStrategy().suitable_regimes() == {Regime.SIDEWAYS}


def test_pullback_and_reclaim_in_uptrend_emits_buy_with_stop_and_target():
    base = [100.0 + i * 0.5 for i in range(60)]
    dip = base[-1] * 0.95
    reclaim = base[-1] * 1.02
    closes = base + [dip, reclaim]

    universe = {"AAA": make_context("AAA", closes)}
    snapshot = make_snapshot("AAA", universe)

    signals = SwingStrategy(fast_window=20, slow_window=50, atr_window=14).on_features(snapshot)

    assert len(signals) == 1
    assert signals[0].side == "buy"
    assert "stop_price" in signals[0].meta
    assert "target_price" in signals[0].meta
    assert signals[0].meta["stop_price"] < signals[0].meta["target_price"]


def test_no_pullback_emits_nothing():
    closes = [100.0 + i * 0.5 for i in range(60)]
    universe = {"AAA": make_context("AAA", closes)}
    snapshot = make_snapshot("AAA", universe)

    assert SwingStrategy().on_features(snapshot) == []

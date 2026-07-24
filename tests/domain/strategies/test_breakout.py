from __future__ import annotations

from _helpers import make_context, make_snapshot

from qat.domain.regime import Regime
from qat.domain.strategies.breakout import BreakoutStrategy


def test_suitable_regimes():
    assert BreakoutStrategy().suitable_regimes() == {Regime.BULL}


def test_donchian_breakout_with_volume_expansion_emits_buy():
    closes = [100.0] * 20 + [110.0]
    highs = [100.5] * 20 + [111.0]
    volumes = [1_000_000.0] * 20 + [3_000_000.0]

    universe = {"AAA": make_context("AAA", closes, highs=highs, volumes=volumes)}
    snapshot = make_snapshot("AAA", universe)

    signals = BreakoutStrategy(channel_window=20, volume_multiple=1.5).on_features(snapshot)

    assert len(signals) == 1
    assert signals[0].side == "buy"
    assert signals[0].meta["stop_price"] == 100.5


def test_no_breakout_emits_nothing():
    universe = {"AAA": make_context("AAA", [100.0] * 21)}
    snapshot = make_snapshot("AAA", universe)

    assert BreakoutStrategy().on_features(snapshot) == []

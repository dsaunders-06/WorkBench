from __future__ import annotations

from _helpers import make_context, make_snapshot

from qat.domain.regime import Regime
from qat.domain.strategies.momentum import MomentumStrategy


def test_suitable_regimes():
    assert MomentumStrategy().suitable_regimes() == {Regime.BULL, Regime.LOW_VOL, Regime.RECOVERY}


def test_top_performer_emits_buy():
    n = 300
    top = [100.0 * (1.01**i) for i in range(n)]
    flats = {f"F{i}": [100.0] * n for i in range(9)}

    universe = {"TOP": make_context("TOP", top)}
    universe.update({symbol: make_context(symbol, closes) for symbol, closes in flats.items()})
    snapshot = make_snapshot("TOP", universe)

    signals = MomentumStrategy(lookback_days=252, skip_days=21, top_decile=0.1).on_features(
        snapshot
    )

    assert len(signals) == 1
    assert signals[0].side == "buy"


def test_bottom_performer_emits_nothing():
    n = 300
    top = [100.0 * (1.01**i) for i in range(n)]
    bottom = [100.0 * (0.999**i) for i in range(n)]
    flats = {f"F{i}": [100.0] * n for i in range(8)}

    universe = {"TOP": make_context("TOP", top), "BOTTOM": make_context("BOTTOM", bottom)}
    universe.update({symbol: make_context(symbol, closes) for symbol, closes in flats.items()})
    snapshot = make_snapshot("BOTTOM", universe)

    assert (
        MomentumStrategy(lookback_days=252, skip_days=21, top_decile=0.1).on_features(snapshot)
        == []
    )


def test_insufficient_history_emits_nothing():
    universe = {"AAA": make_context("AAA", [100.0] * 10)}
    snapshot = make_snapshot("AAA", universe)

    assert MomentumStrategy().on_features(snapshot) == []

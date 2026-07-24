from __future__ import annotations

from _helpers import make_context, make_fundamentals, make_snapshot

from qat.domain.regime import Regime
from qat.domain.strategies.growth import GrowthStrategy


def test_suitable_regimes():
    assert GrowthStrategy().suitable_regimes() == {Regime.BULL, Regime.LOW_VOL}


def test_strong_growth_quality_and_reasonable_peg_emits_buy():
    fundamentals = make_fundamentals("AAA", eps_growth_yoy=0.25, roic=0.15, peg_ratio=1.5)
    universe = {"AAA": make_context("AAA", [100.0, 101.0, 102.0], fundamentals=fundamentals)}
    snapshot = make_snapshot("AAA", universe)

    signals = GrowthStrategy().on_features(snapshot)

    assert len(signals) == 1
    assert signals[0].side == "buy"


def test_weak_growth_emits_nothing():
    fundamentals = make_fundamentals("AAA", eps_growth_yoy=0.02, roic=0.15, peg_ratio=1.5)
    universe = {"AAA": make_context("AAA", [100.0, 101.0, 102.0], fundamentals=fundamentals)}
    snapshot = make_snapshot("AAA", universe)

    assert GrowthStrategy().on_features(snapshot) == []

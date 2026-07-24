from __future__ import annotations

from _helpers import make_context, make_fundamentals, make_snapshot

from qat.domain.regime import Regime
from qat.domain.strategies.garp import GarpStrategy


def test_suitable_regimes():
    assert GarpStrategy().suitable_regimes() == {Regime.BULL, Regime.RECOVERY}


def test_within_garp_band_emits_buy():
    fundamentals = make_fundamentals(
        "AAA", peg_ratio=1.0, eps_growth_yoy=0.15, roe=0.15, debt_to_equity=0.5
    )
    universe = {"AAA": make_context("AAA", [100.0, 101.0], fundamentals=fundamentals)}
    snapshot = make_snapshot("AAA", universe)

    signals = GarpStrategy().on_features(snapshot)

    assert len(signals) == 1
    assert signals[0].side == "buy"


def test_peg_too_high_emits_nothing():
    fundamentals = make_fundamentals(
        "AAA", peg_ratio=3.0, eps_growth_yoy=0.15, roe=0.15, debt_to_equity=0.5
    )
    universe = {"AAA": make_context("AAA", [100.0, 101.0], fundamentals=fundamentals)}
    snapshot = make_snapshot("AAA", universe)

    assert GarpStrategy().on_features(snapshot) == []

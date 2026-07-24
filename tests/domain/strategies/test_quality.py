from __future__ import annotations

from _helpers import make_context, make_fundamentals, make_snapshot

from qat.domain.regime import Regime
from qat.domain.strategies.quality import QualityStrategy


def test_suitable_regimes():
    assert QualityStrategy().suitable_regimes() == {Regime.BEAR, Regime.HIGH_VOL, Regime.RECESSION}


def _universe():
    high_q = make_fundamentals("HIGHQ", roe=0.30, roic=0.25, debt_to_equity=0.1)
    low_q = make_fundamentals("LOWQ", roe=0.02, roic=0.01, debt_to_equity=2.0)
    return {
        "HIGHQ": make_context("HIGHQ", [100.0, 101.0], fundamentals=high_q),
        "LOWQ": make_context("LOWQ", [100.0, 101.0], fundamentals=low_q),
    }


def test_highest_quality_name_emits_buy():
    universe = _universe()
    snapshot = make_snapshot("HIGHQ", universe)

    signals = QualityStrategy(top_quintile=0.5).on_features(snapshot)

    assert len(signals) == 1


def test_lowest_quality_name_emits_nothing():
    universe = _universe()
    snapshot = make_snapshot("LOWQ", universe)

    assert QualityStrategy(top_quintile=0.5).on_features(snapshot) == []

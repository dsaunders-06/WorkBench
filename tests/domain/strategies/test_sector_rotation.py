from __future__ import annotations

from _helpers import make_context, make_fundamentals, make_snapshot

from qat.domain.regime import Regime
from qat.domain.strategies.sector_rotation import SectorRotationStrategy


def _universe():
    leader_closes = [100.0 + i * 1.0 for i in range(60)]
    laggard_closes = [100.0 - i * 0.1 for i in range(60)]
    leader_fund = make_fundamentals("LEAD", sector="Technology")
    laggard_fund = make_fundamentals("LAG", sector="Energy")
    return {
        "LEAD": make_context("LEAD", leader_closes, fundamentals=leader_fund),
        "LAG": make_context("LAG", laggard_closes, fundamentals=laggard_fund),
    }


def test_suitable_regimes():
    assert SectorRotationStrategy().suitable_regimes() == {Regime.RECOVERY}


def test_leading_sector_trending_name_emits_buy():
    universe = _universe()
    snapshot = make_snapshot("LEAD", universe)

    signals = SectorRotationStrategy(top_sectors=1).on_features(snapshot)

    assert len(signals) == 1
    assert signals[0].meta["sector"] == "Technology"


def test_lagging_sector_name_emits_nothing():
    universe = _universe()
    snapshot = make_snapshot("LAG", universe)

    assert SectorRotationStrategy(top_sectors=1).on_features(snapshot) == []

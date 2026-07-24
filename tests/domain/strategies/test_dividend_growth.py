from __future__ import annotations

from _helpers import make_context, make_fundamentals, make_snapshot

from qat.domain.regime import Regime
from qat.domain.strategies.dividend_growth import DividendGrowthStrategy


def test_suitable_regimes():
    assert DividendGrowthStrategy().suitable_regimes() == {
        Regime.BEAR,
        Regime.RECESSION,
        Regime.LOW_VOL,
    }


def test_long_covered_streak_emits_buy():
    fundamentals = make_fundamentals(
        "AAA", dividend_growth_streak_years=15, payout_ratio=0.5, fcf_yield=0.04
    )
    universe = {"AAA": make_context("AAA", [100.0, 101.0], fundamentals=fundamentals)}
    snapshot = make_snapshot("AAA", universe)

    signals = DividendGrowthStrategy().on_features(snapshot)

    assert len(signals) == 1
    assert signals[0].side == "buy"


def test_short_streak_emits_nothing():
    fundamentals = make_fundamentals(
        "AAA", dividend_growth_streak_years=2, payout_ratio=0.5, fcf_yield=0.04
    )
    universe = {"AAA": make_context("AAA", [100.0, 101.0], fundamentals=fundamentals)}
    snapshot = make_snapshot("AAA", universe)

    assert DividendGrowthStrategy().on_features(snapshot) == []

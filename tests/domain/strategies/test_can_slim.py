from __future__ import annotations

from _helpers import make_context, make_fundamentals, make_snapshot

from qat.domain.regime import Regime
from qat.domain.strategies.can_slim import CanSlimStrategy


def test_suitable_regimes():
    assert CanSlimStrategy().suitable_regimes() == {Regime.BULL, Regime.RECOVERY}


def test_passing_all_criteria_emits_buy():
    closes = [100.0 + i * 0.2 for i in range(260)]
    fundamentals = make_fundamentals(
        "AAA",
        eps_growth_yoy=0.30,
        eps_growth_accelerating=True,
        relative_strength_rank=90.0,
        institutional_ownership_pct=0.5,
    )
    universe = {"AAA": make_context("AAA", closes, fundamentals=fundamentals)}
    snapshot = make_snapshot("AAA", universe)

    signals = CanSlimStrategy().on_features(snapshot)

    assert len(signals) == 1
    assert signals[0].side == "buy"


def test_failing_eps_growth_emits_nothing():
    closes = [100.0 + i * 0.2 for i in range(260)]
    fundamentals = make_fundamentals(
        "AAA", eps_growth_yoy=0.05, eps_growth_accelerating=True, relative_strength_rank=90.0
    )
    universe = {"AAA": make_context("AAA", closes, fundamentals=fundamentals)}
    snapshot = make_snapshot("AAA", universe)

    assert CanSlimStrategy().on_features(snapshot) == []

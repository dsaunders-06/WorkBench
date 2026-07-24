from __future__ import annotations

import random

from _helpers import make_context, make_snapshot

from qat.domain.regime import Regime
from qat.domain.strategies.volatility import VolatilityStrategy


def test_suitable_regimes():
    assert VolatilityStrategy().suitable_regimes() == {Regime.SIDEWAYS, Regime.LOW_VOL}


def test_recent_calm_after_volatile_history_emits_buy():
    rng = random.Random(0)  # nosec B311 - deterministic test fixture, not crypto
    volatile = [100.0]
    for _ in range(100):
        volatile.append(volatile[-1] * (1 + rng.uniform(-0.05, 0.05)))
    calm = [volatile[-1]]
    for _ in range(30):
        calm.append(calm[-1] * (1 + rng.uniform(-0.001, 0.001)))
    closes = volatile + calm[1:]

    universe = {"AAA": make_context("AAA", closes)}
    snapshot = make_snapshot("AAA", universe)

    signals = VolatilityStrategy(lookback=60, z_threshold=0.5).on_features(snapshot)

    assert len(signals) == 1
    assert signals[0].side == "buy"


def test_insufficient_history_emits_nothing():
    universe = {"AAA": make_context("AAA", [100.0] * 10)}
    snapshot = make_snapshot("AAA", universe)

    assert VolatilityStrategy().on_features(snapshot) == []

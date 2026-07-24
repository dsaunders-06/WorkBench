from __future__ import annotations

from _helpers import make_context, make_snapshot

from qat.domain.regime import Regime
from qat.domain.strategies.pairs_stat_arb import PairsStatArbStrategy


def test_suitable_regimes():
    assert PairsStatArbStrategy().suitable_regimes() == {Regime.SIDEWAYS, Regime.HIGH_VOL}


def test_diverged_correlated_pair_emits_signal():
    n = 80
    base = [100.0 + i * 0.3 for i in range(n)]
    partner = [50.0 + i * 0.15 for i in range(n)]
    base = base[:-5] + [b * 1.15 for b in base[-5:]]

    universe = {"BASE": make_context("BASE", base), "PARTNER": make_context("PARTNER", partner)}
    snapshot = make_snapshot("BASE", universe)

    signals = PairsStatArbStrategy(lookback=60, entry_z=1.5, min_correlation=0.5).on_features(
        snapshot
    )

    assert len(signals) == 1
    assert signals[0].meta["partner_symbol"] == "PARTNER"


def test_no_correlated_partner_emits_nothing():
    n = 80
    base = [100.0 + i * 0.3 for i in range(n)]
    unrelated = [50.0 + ((-1) ** i) * 5 for i in range(n)]

    universe = {"BASE": make_context("BASE", base), "OTHER": make_context("OTHER", unrelated)}
    snapshot = make_snapshot("BASE", universe)

    assert PairsStatArbStrategy(min_correlation=0.9).on_features(snapshot) == []

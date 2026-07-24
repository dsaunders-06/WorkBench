from __future__ import annotations

from _helpers import make_context, make_fundamentals, make_snapshot

from qat.domain.regime import Regime
from qat.domain.strategies.value import ValueStrategy


def test_suitable_regimes():
    assert ValueStrategy().suitable_regimes() == {Regime.RECOVERY, Regime.SIDEWAYS}


def test_cheapest_name_with_quality_floor_emits_buy():
    cheap = make_fundamentals(
        "CHEAP", book_to_market=1.4, earnings_yield=0.10, fcf_yield=0.08, ev_to_ebit=6.0, roic=0.10
    )
    expensive = make_fundamentals(
        "EXP", book_to_market=0.2, earnings_yield=0.01, fcf_yield=0.0, ev_to_ebit=30.0, roic=0.10
    )
    universe = {
        "CHEAP": make_context("CHEAP", [100.0, 101.0], fundamentals=cheap),
        "EXP": make_context("EXP", [100.0, 101.0], fundamentals=expensive),
    }
    snapshot = make_snapshot("CHEAP", universe)

    signals = ValueStrategy(top_quintile=0.5).on_features(snapshot)

    assert len(signals) == 1
    assert signals[0].side == "buy"


def test_low_quality_cheap_name_is_filtered_by_roic_floor():
    cheap_trap = make_fundamentals(
        "TRAP", book_to_market=2.0, earnings_yield=0.15, fcf_yield=0.10, ev_to_ebit=5.0, roic=0.0
    )
    universe = {"TRAP": make_context("TRAP", [100.0, 101.0], fundamentals=cheap_trap)}
    snapshot = make_snapshot("TRAP", universe)

    assert ValueStrategy(min_roic=0.05).on_features(snapshot) == []

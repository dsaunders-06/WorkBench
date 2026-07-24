from __future__ import annotations

from _helpers import make_context, make_fundamentals, make_snapshot

from qat.domain.regime import ALL_REGIMES
from qat.domain.strategies.multi_factor import MultiFactorStrategy


def _universe():
    strong = make_fundamentals(
        "STRONG",
        book_to_market=1.2,
        earnings_yield=0.10,
        fcf_yield=0.08,
        roe=0.25,
        roic=0.20,
        debt_to_equity=0.2,
    )
    weak = make_fundamentals(
        "WEAK",
        book_to_market=0.1,
        earnings_yield=0.01,
        fcf_yield=-0.01,
        roe=0.01,
        roic=0.01,
        debt_to_equity=2.0,
    )
    strong_closes = [100.0 + i * 0.1 for i in range(40)]
    weak_closes = [100.0 - i * 0.1 for i in range(40)]
    return {
        "STRONG": make_context("STRONG", strong_closes, fundamentals=strong),
        "WEAK": make_context("WEAK", weak_closes, fundamentals=weak),
    }


def test_suitable_regimes_is_all_seven():
    regimes = MultiFactorStrategy().suitable_regimes()
    assert regimes == set(ALL_REGIMES)
    assert len(regimes) == 7


def test_best_composite_name_emits_buy():
    universe = _universe()
    snapshot = make_snapshot("STRONG", universe)

    signals = MultiFactorStrategy(top_quintile=0.5).on_features(snapshot)

    assert len(signals) == 1
    assert signals[0].side == "buy"


def test_worst_composite_name_emits_nothing():
    universe = _universe()
    snapshot = make_snapshot("WEAK", universe)

    assert MultiFactorStrategy(top_quintile=0.5).on_features(snapshot) == []

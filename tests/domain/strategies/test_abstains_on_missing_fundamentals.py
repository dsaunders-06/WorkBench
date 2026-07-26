"""Every fundamentals-driven strategy abstains rather than guessing (spec M18).

Before M18 the mock answered all sixteen fields for every symbol, so these
strategies happily ranked an index ETF on an invented return on equity and
nothing in the output said so. These tests pin the replacement behaviour: a
missing input produces no signal, per field, per strategy.

The per-field parametrisation is the point. A single "abstains when everything
is missing" test would pass just as well against a strategy that only checked
one field, leaving the other gates reading None.
"""

from __future__ import annotations

import pytest
from _helpers import make_context, make_fundamentals, make_snapshot

from qat.domain.strategies.can_slim import CanSlimStrategy
from qat.domain.strategies.dividend_growth import DividendGrowthStrategy
from qat.domain.strategies.garp import GarpStrategy
from qat.domain.strategies.growth import GrowthStrategy
from qat.domain.strategies.multi_factor import MultiFactorStrategy
from qat.domain.strategies.quality import QualityStrategy
from qat.domain.strategies.value import ValueStrategy

# Values chosen so each strategy's gates all pass - the abstention under test
# is then unambiguously caused by the field being blanked, not by a threshold.
_QUALIFYING = {
    # Exactly 0.20 because GARP caps EPS growth at 0.20 while CAN SLIM requires
    # at least 0.20 - the one value that satisfies every strategy at once.
    "eps_growth_yoy": 0.20,
    "eps_growth_accelerating": True,
    "peg_ratio": 1.0,
    "roe": 0.30,
    "roic": 0.25,
    "debt_to_equity": 0.2,
    "book_to_market": 0.9,
    "earnings_yield": 0.09,
    "ev_to_ebit": 8.0,
    "fcf_yield": 0.07,
    "dividend_yield": 0.03,
    "dividend_growth_streak_years": 20,
    "payout_ratio": 0.4,
    "institutional_ownership_pct": 0.65,
    "relative_strength_rank": 95.0,
}

_RISING = [100.0 + i for i in range(60)]
_FLAT = [100.0] * 60

_CASES = [
    (GarpStrategy, "peg_ratio"),
    (GarpStrategy, "eps_growth_yoy"),
    (GarpStrategy, "roe"),
    (GarpStrategy, "debt_to_equity"),
    (GrowthStrategy, "eps_growth_yoy"),
    (GrowthStrategy, "roic"),
    (GrowthStrategy, "peg_ratio"),
    (CanSlimStrategy, "eps_growth_yoy"),
    (CanSlimStrategy, "eps_growth_accelerating"),
    (CanSlimStrategy, "relative_strength_rank"),
    (CanSlimStrategy, "institutional_ownership_pct"),
    (DividendGrowthStrategy, "dividend_growth_streak_years"),
    (DividendGrowthStrategy, "payout_ratio"),
    (DividendGrowthStrategy, "fcf_yield"),
]


def _single_symbol_snapshot(**field_overrides):
    fundamentals = make_fundamentals("AAA", **{**_QUALIFYING, **field_overrides})
    universe = {"AAA": make_context("AAA", _RISING, fundamentals=fundamentals)}
    return make_snapshot("AAA", universe)


@pytest.mark.parametrize(("strategy_cls", "field"), _CASES)
def test_single_symbol_strategy_abstains_when_a_required_field_is_missing(strategy_cls, field):
    strategy = strategy_cls()

    with_field = strategy.on_features(_single_symbol_snapshot())
    without_field = strategy.on_features(_single_symbol_snapshot(**{field: None}))

    assert with_field, f"{strategy.name} should signal when {field} is present - test is not valid"
    assert without_field == [], f"{strategy.name} must abstain when {field} is missing"


# --- cross-sectional strategies ---------------------------------------------


# A weaker but fully measurable company. Present so the cross-sectional
# strategies have a real ranking to do: they need at least two comparable
# symbols, so a universe of one measurable name plus ETFs would produce no
# signal for a reason that has nothing to do with M18.
_WEAKER = {
    **_QUALIFYING,
    "roe": 0.05,
    "roic": 0.06,  # still above Value's 0.05 quality floor
    "debt_to_equity": 1.5,
    "book_to_market": 0.10,
    "earnings_yield": 0.01,
    "fcf_yield": 0.005,
}


def _mixed_universe(missing_field: str | None = None):
    """Six measurable companies and five symbols missing `missing_field`.

    Enough of each that the top-quintile cutoff has something to bite on, and
    that a strategy wrongly ranking the unmeasurable names cannot pass by
    accident.
    """
    universe = {
        "GOOD": make_context("GOOD", _RISING, fundamentals=make_fundamentals("GOOD", **_QUALIFYING))
    }
    for index in range(5):
        symbol = f"OK{index}"
        universe[symbol] = make_context(
            symbol, _FLAT, fundamentals=make_fundamentals(symbol, **_WEAKER)
        )
    for index in range(5):
        symbol = f"ETF{index}"
        overrides = dict(_QUALIFYING)
        if missing_field is not None:
            overrides[missing_field] = None
        universe[symbol] = make_context(
            symbol, _FLAT, fundamentals=make_fundamentals(symbol, **overrides)
        )
    return universe


def _measurable_signals(strategy, universe) -> list:
    return [
        signal
        for symbol in universe
        if not symbol.startswith("ETF")
        for signal in strategy.on_features(make_snapshot(symbol, universe))
    ]


@pytest.mark.parametrize(
    ("strategy_cls", "field"),
    [
        (ValueStrategy, "roic"),
        (ValueStrategy, "book_to_market"),
        (ValueStrategy, "earnings_yield"),
        (ValueStrategy, "fcf_yield"),
        (QualityStrategy, "roe"),
        (QualityStrategy, "roic"),
        (QualityStrategy, "debt_to_equity"),
        (MultiFactorStrategy, "book_to_market"),
        (MultiFactorStrategy, "roe"),
        (MultiFactorStrategy, "debt_to_equity"),
    ],
)
def test_cross_sectional_strategy_abstains_on_a_symbol_it_cannot_measure(strategy_cls, field):
    strategy = strategy_cls()
    universe = _mixed_universe(missing_field=field)

    signals = strategy.on_features(make_snapshot("ETF0", universe))

    assert signals == [], f"{strategy.name} must not rank ETF0 with {field} missing"


@pytest.mark.parametrize("strategy_cls", [ValueStrategy, QualityStrategy, MultiFactorStrategy])
def test_abstention_is_per_symbol_not_global(strategy_cls):
    """Dropping the whole ranking because one ETF cannot be scored would
    silently disable the strategy for any watchlist containing an ETF - which
    is most of them."""
    strategy = strategy_cls()
    # roic is required by all three; roe, for instance, is not used by Value at
    # all, so blanking it would prove nothing about that strategy.
    universe = _mixed_universe(missing_field="roic")

    signals = _measurable_signals(strategy, universe)

    assert signals, f"{strategy.name} should still evaluate the symbols it can measure"
    assert all(not signal.symbol.startswith("ETF") for signal in signals)


@pytest.mark.parametrize("strategy_cls", [ValueStrategy, QualityStrategy, MultiFactorStrategy])
def test_an_unmeasurable_symbol_cannot_win_on_its_remaining_fields(strategy_cls):
    """The failure this milestone replaces: a symbol scored on figures it does
    not really have, beating a company measured on figures it does.

    The ETFs here carry values that would top every ranking, and are missing
    exactly one required field.
    """
    strategy = strategy_cls()
    universe = _mixed_universe()
    for index in range(5):
        symbol = f"ETF{index}"
        universe[symbol] = make_context(
            symbol,
            _RISING,
            fundamentals=make_fundamentals(
                symbol,
                **{
                    **_QUALIFYING,
                    "roic": None,  # required by all three
                    "roe": 0.99,
                    "book_to_market": 5.0,
                    "earnings_yield": 0.5,
                    "fcf_yield": 0.5,
                },
            ),
        )

    for index in range(5):
        assert strategy.on_features(make_snapshot(f"ETF{index}", universe)) == []
    assert _measurable_signals(strategy, universe), "a measurable name should still be ranked"

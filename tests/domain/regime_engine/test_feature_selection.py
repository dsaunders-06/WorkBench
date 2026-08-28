"""The matrix emits the columns it is told to, and by default exactly today's six.

Milestone C, Task 1. A feature is made absent by a `Settings` value, never a
branch - the rule `ablation.py` already states for rails, and which it records
`if enabled(...)` guards as REJECTED for.

⚠️ **`regime_features` is a SIZING INPUT.** The regime label sets the exposure
scalar. The default here must be byte-identical to the six columns that shipped
before it existed, and if an existing regime test changes behaviour that means
the default is NOT being applied - stop rather than adjust the test.
"""

from __future__ import annotations

import pytest

from qat.config import Settings
from qat.domain.regime_engine.feature_matrix import FEATURE_NAMES, RegimeFeatureBuilder


def _fed(builder: RegimeFeatureBuilder) -> RegimeFeatureBuilder:
    builder.update_macro("VIXCLS", 15.5)
    builder.update_macro("T10Y3M", 0.81)
    builder.update_macro("BAA10Y", 1.62)
    for close in (100.0, 101.0, 102.0):
        builder.add_benchmark_bar(close)
    return builder


def test_the_default_is_todays_six_columns_unchanged() -> None:
    assert Settings(_env_file=None).regime_features == FEATURE_NAMES
    assert _fed(RegimeFeatureBuilder()).feature_matrix().shape[1] == len(FEATURE_NAMES)


def test_a_narrowed_list_emits_only_those_columns() -> None:
    wanted = ("log_return", "realized_vol", "vix_level")
    matrix = _fed(RegimeFeatureBuilder(features=wanted)).feature_matrix()

    assert matrix.shape[1] == 3


def test_the_vix_column_still_carries_vix_when_others_are_dropped() -> None:
    """⚠️ Narrowing must SELECT columns, not truncate the row. Truncation leaves
    every remaining column holding its neighbour's value, which reads as a
    working matrix and is a different measurement entirely."""
    matrix = _fed(RegimeFeatureBuilder(features=("log_return", "vix_level"))).feature_matrix()

    assert matrix[-1, 1] == pytest.approx(15.5)


def test_the_order_asked_for_is_the_order_emitted() -> None:
    """The list is ORDERED because the matrix is positional and the HMM is
    fitted on column order. Two runs whose lists differ only in order build
    different matrices and are silently incomparable."""
    matrix = _fed(RegimeFeatureBuilder(features=("credit_spread", "vix_level"))).feature_matrix()

    assert matrix[-1, 0] == pytest.approx(1.62)
    assert matrix[-1, 1] == pytest.approx(15.5)


def test_dropping_credit_spread_leaves_the_rest_intact() -> None:
    """Item 66's first ablation: `credit_spread` is `BAA10Y`, a US series
    measuring +0.004 against forward ASX volatility. Removing it must disturb
    nothing else."""
    kept = tuple(f for f in FEATURE_NAMES if f != "credit_spread")
    matrix = _fed(RegimeFeatureBuilder(features=kept)).feature_matrix()

    assert matrix.shape[1] == len(FEATURE_NAMES) - 1
    assert matrix[-1, kept.index("vix_level")] == pytest.approx(15.5)
    assert matrix[-1, kept.index("yield_curve_slope")] == pytest.approx(0.81)

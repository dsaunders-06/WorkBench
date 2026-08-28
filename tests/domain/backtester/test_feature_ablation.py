"""Which regime features may be ablated, and which are refused (Milestone C).

A feature is made absent by a `Settings` value, never a branch - the rule
`ablation.py` states for rails, and which records `if enabled(...)` guards in
the decision path as REJECTED.

⚠️ `log_return` and `realized_vol` are refused by name. `hmm_core` reads their
state statistics and `fusion.score_from_hmm` turns those into the z-scores that
decide which fitted state is called bull. Removing either would not drop a
signal - it would RENAME every label, and the run would look entirely normal.
Refused loudly, the way `_TWO_CONSUMERS` refuses `apply_costs_in_paper`.
"""

from __future__ import annotations

import pytest

from qat.config import Settings
from qat.domain.backtester.ablation import (
    FEATURES,
    UNABLATABLE_FEATURES,
    UnablatableFeature,
    UnablatableRail,
    feature_settings,
)
from qat.domain.regime_engine.feature_matrix import FEATURE_NAMES


def _base() -> Settings:
    return Settings(_env_file=None)


def test_disabling_nothing_returns_the_columns_untouched() -> None:
    assert feature_settings(_base(), []).regime_features == FEATURE_NAMES


def test_an_ablated_feature_is_absent_and_the_rest_keep_their_order() -> None:
    narrowed = feature_settings(_base(), ["vix_level"]).regime_features

    assert "vix_level" not in narrowed
    assert narrowed == tuple(f for f in FEATURE_NAMES if f != "vix_level")


def test_credit_spread_is_ablatable() -> None:
    """Item 66's first question. `credit_spread` is `BAA10Y`, a US series
    measuring +0.004 against forward ASX volatility, feeding a sizing input on a
    94-stock Australian book."""
    assert "credit_spread" in FEATURES
    assert "credit_spread" not in feature_settings(_base(), ["credit_spread"]).regime_features


@pytest.mark.parametrize("structural", ["log_return", "realized_vol"])
def test_the_two_structural_columns_are_refused_by_name(structural: str) -> None:
    with pytest.raises(UnablatableFeature, match="bull"):
        feature_settings(_base(), [structural])


@pytest.mark.parametrize("structural", ["log_return", "realized_vol"])
def test_the_refusal_says_what_to_ablate_instead(structural: str) -> None:
    """A refusal that does not name an alternative sends the reader back to the
    source to find out what IS allowed."""
    with pytest.raises(UnablatableFeature) as excinfo:
        feature_settings(_base(), [structural])

    assert "credit_spread" in str(excinfo.value)


def test_an_unknown_feature_is_named_never_ignored() -> None:
    """Silently running a baseline twice and reporting no difference is
    indistinguishable from a feature that costs nothing."""
    with pytest.raises(UnablatableFeature, match="asx_vix_z"):
        feature_settings(_base(), ["asx_vix_z"])


def test_a_rail_name_is_refused_here_rather_than_quietly_doing_nothing() -> None:
    """⚠️ `--feature cost_to_risk` is the easy typo: a real name, wrong arm.
    Without this it would narrow nothing, run two identical baselines, and
    report no difference - which reads as 'the feature costs nothing'."""
    with pytest.raises(UnablatableFeature) as excinfo:
        feature_settings(_base(), ["cost_to_risk"])

    message = str(excinfo.value)
    assert "cost_to_risk" in message
    # ⚠️ The HINT, not just the refusal. An earlier version of this test asserted
    # only that it raised - which it does with or without the hint, so it could
    # not fail for the thing it is named after. Falsifying the hint left it
    # green, which is how that was found.
    assert "RAIL" in message and "--rail" in message, (
        "the refusal does not tell the operator this is a rail and which arm takes it, "
        "so a real name in the wrong arm sends them to the source"
    )


def test_its_exception_is_distinct_from_the_rail_one() -> None:
    """Its own class rather than a reuse of `UnablatableRail`, so a caller can
    tell a rail problem from a feature problem without parsing a message."""
    assert not issubclass(UnablatableRail, UnablatableFeature)
    assert not issubclass(UnablatableFeature, UnablatableRail)


def test_the_result_is_revalidated_not_copied() -> None:
    """`model_copy(update=...)` writes fields without running validators, so a
    bad value would surface far away or not at all."""
    assert isinstance(feature_settings(_base(), ["breadth"]), Settings)


def test_the_tables_do_not_overlap_or_omit() -> None:
    """⚠️ Every column is either ablatable or refused WITH A REASON. A column in
    neither table would be rejected as 'unknown', which is true but unhelpful,
    and a column in both would make the refusal unreachable."""
    assert set(FEATURES) | set(UNABLATABLE_FEATURES) == set(FEATURE_NAMES)
    assert not set(FEATURES) & set(UNABLATABLE_FEATURES)

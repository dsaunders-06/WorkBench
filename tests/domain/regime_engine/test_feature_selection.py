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


def test_the_state_stats_follow_the_named_columns_not_positions() -> None:
    """⚠️ Task 2, and the one where a mistake RENAMES rather than degrades.

    hmmlearn numbers states arbitrarily. `mean_return` and `mean_vol` are how a
    state index acquires a NAME: `fusion.score_from_hmm` turns them into the
    z-scores that decide which fitted state is bull and which is bear. Read the
    wrong column and every label still appears, referring to something else.

    Here `vix_level` sits at position 0, where `_LOG_RETURN_COL = 0` used to
    look. A positional read would report a mean return of about 15.5.
    """
    import numpy as np

    from qat.domain.regime_engine.hmm_core import HMMRegimeModel

    features = ("vix_level", "log_return", "realized_vol")
    model = HMMRegimeModel(n_states=2, features=features)
    matrix = np.tile(np.array([[15.5, 0.01, 0.20], [16.0, -0.01, 0.40]]), (40, 1))

    model.fit(matrix)
    # `state_signatures` is a property computed during fit; the raw-units means
    # are what `fusion.score_from_hmm` consumes.
    for signature in model.state_signatures.values():
        assert abs(signature.mean_return) < 1.0, (
            f"mean_return is {signature.mean_return}, which is the VIX column - the stats "
            f"are being read by position, so every label now means something else"
        )
        assert 0.0 <= signature.mean_vol < 1.0


def test_the_default_columns_are_still_read_where_they_always_were() -> None:
    """The no-op half: with the default list, positions 0 and 1 are exactly
    what the constants used to hard-code."""
    from qat.domain.regime_engine.hmm_core import HMMRegimeModel

    model = HMMRegimeModel(n_states=2)

    assert model._return_col == 0
    assert model._vol_col == 1


def test_the_engine_passes_the_configured_columns_to_both_consumers() -> None:
    """⚠️ THE WIRING, and it is the whole point of Tasks 1 and 2.

    Both previous tasks are inert unless the engine actually hands
    `settings.regime_features` to the builder AND the model. Items 59 and 67
    were both a mechanism that worked with nothing driving it, and both were
    green at the unit layer while the caller did nothing.

    Asserted on BOTH consumers: a builder narrowed without the model would fit
    an N-column matrix while reading state statistics from the six-column
    positions, which is the label-renaming failure Task 2 exists to prevent.
    """
    from qat.domain.bus import EventBus
    from qat.domain.regime_engine.engine import RegimeEngine

    wanted = ("log_return", "realized_vol", "vix_level")
    engine = RegimeEngine(EventBus(), benchmark_symbol="STW.AX", features=wanted)

    assert engine._feature_builder.features == wanted
    assert engine._hmm.features == wanted


def test_the_engine_defaults_to_the_six_it_always_had() -> None:
    from qat.domain.bus import EventBus
    from qat.domain.regime_engine.engine import RegimeEngine

    engine = RegimeEngine(EventBus(), benchmark_symbol="STW.AX")

    assert engine._feature_builder.features == FEATURE_NAMES
    assert engine._hmm.features == FEATURE_NAMES


def test_the_runtime_hands_the_setting_to_the_engine() -> None:
    """⚠️ ONE LAYER FURTHER OUT, and it was missed on the first pass.

    The engine-level test above goes red if the ENGINE stops forwarding the
    columns. It stays GREEN if `runtime.py` stops passing the SETTING - which is
    the assembly point where the app actually decides, and where a `Settings`
    value that nothing reads would look exactly like a working feature.

    Read from source rather than by constructing a Runtime: building one needs a
    broker, a bus and a live config, and the defect being guarded is a missing
    ARGUMENT - which lives in the text, not in behaviour a stub would exercise.
    """
    import ast
    from pathlib import Path

    import qat

    source = (Path(qat.__file__).parent / "presentation" / "runtime.py").read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if name != "RegimeEngine":
            continue
        passed = {kw.arg for kw in node.keywords}
        assert "features" in passed, (
            "runtime.py builds the RegimeEngine without `features`, so "
            "`settings.regime_features` is a setting nothing reads and both Milestone C "
            "tasks are inert in the running app"
        )
        return
    raise AssertionError(
        "no RegimeEngine(...) call found in runtime.py - this guard has gone stale"
    )

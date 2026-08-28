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


def test_the_manifest_carries_terminal_equity_and_the_ablated_feature(tmp_path) -> None:
    """Task 4. `terminal_equity` is the only figure that MOVES when a regime
    feature moves - trades, win% and R are all scale-free, and a feature changes
    position SIZE."""
    from qat.domain.backtester.manifest import build_manifest, read_manifest

    manifest = build_manifest(
        data_dir=tmp_path,
        disabled=[],
        universe=["BHP.AX"],
        starting_equity=100_000.0,
        terminal_equity=104_250.0,
        disabled_feature="credit_spread",
        regime_features=("log_return", "realized_vol"),
    )
    manifest.write(tmp_path / "manifest.json")
    reread = read_manifest(tmp_path / "manifest.json")

    assert reread.terminal_equity == pytest.approx(104_250.0)
    assert reread.disabled_feature == "credit_spread"
    assert reread.regime_features == ("log_return", "realized_vol")


def test_a_manifest_without_the_new_fields_reads_back_as_unknown(tmp_path) -> None:
    """⚠️ `None`, never 0.0 or (). A run written before these fields existed did
    not measure them, and a substituted zero would assert a terminal equity of
    nothing - M73's `var_95=0.0` scar."""
    from qat.domain.backtester.manifest import build_manifest, read_manifest

    manifest = build_manifest(
        data_dir=tmp_path, disabled=[], universe=["BHP.AX"], starting_equity=100_000.0
    )
    path = tmp_path / "manifest.json"
    manifest.write(path)

    import json

    raw = json.loads(path.read_text(encoding="utf-8"))
    for field_name in ("terminal_equity", "disabled_feature", "regime_features"):
        raw.pop(field_name, None)
    path.write_text(json.dumps(raw), encoding="utf-8")

    reread = read_manifest(path)
    assert reread.terminal_equity is None
    assert reread.disabled_feature is None
    assert reread.regime_features is None


def test_the_regime_path_round_trips(tmp_path) -> None:
    """One writer, one reader, used by the harness AND the tests - a test that
    re-implements the CSV format is a second definition of it."""
    from qat.domain.backtester.run_comparison import read_regime_path, write_regime_path

    rows = [("2026-08-26T00:00:00+00:00", "bull", 1.0), ("2026-08-27T00:00:00+00:00", "bear", 0.5)]
    write_regime_path(tmp_path, rows)

    assert read_regime_path(tmp_path) == rows


def test_a_missing_regime_path_is_empty_not_an_error(tmp_path) -> None:
    """A run that never started the regime engine wrote none - the ablated arm
    of `--rail regime_gate` is exactly that."""
    from qat.domain.backtester.run_comparison import read_regime_path

    assert read_regime_path(tmp_path) == []


def test_the_replay_session_honours_the_configured_columns() -> None:
    """⚠️ THE WIRING THAT WAS MISSING, and it invalidated four measurements.

    `replay_session.py` built its RegimeEngine WITHOUT `features`, so every
    `--feature` run used the default six columns whatever `regime_features`
    said. Both arms were byte-identical and the comparator reported NOT
    EXERCISED - truthful about the arms, meaningless about the feature.

    ⚠️ It was found by ablating `breadth`, an ASX-derived CONTROL, and getting
    the identical result to `credit_spread`. A control earned its place in one
    run, and the three "measurements" taken before it were worthless.

    Read from source, like the runtime guard: the defect is a missing ARGUMENT,
    which lives in the text, and constructing a full ReplaySession needs a bar
    index, a data_dir and an absorbed-fills file that have nothing to do with it.
    """
    import ast
    from pathlib import Path

    import qat

    source = (Path(qat.__file__).parent / "domain" / "backtester" / "replay_session.py").read_text(
        encoding="utf-8"
    )
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if name != "RegimeEngine":
            continue
        assert "features" in {kw.arg for kw in node.keywords}, (
            "replay_session builds its RegimeEngine without `features`, so the replay "
            "ignores regime_features and every --feature comparison runs two identical "
            "arms and reports NOT EXERCISED"
        )
        return
    raise AssertionError("no RegimeEngine(...) call found in replay_session.py")

"""What a feature comparison may and may not be quoted as saying (Milestone C).

The sibling of `compare_runs`, and it leads with a GUARD for the same reason:
if the LABEL never differed between the arms there was nothing for the feature
to change, and any difference is noise wearing its name. A zero gets quoted and
a caveat does not.

⚠️ **The headline is TERMINAL EQUITY, not R.** `compare_runs._arm()` reports
trades, win%, R-mean and R-total - every one scale-free. A regime feature moves
the exposure scalar, which moves position SIZE, so a feature that halved every
position leaves all four of those identical. The one thing the rail report
prints is the one thing that cannot see a feature.
"""

from __future__ import annotations

import json
from pathlib import Path

from qat.domain.backtester.manifest import build_manifest
from qat.domain.backtester.run_comparison import compare_feature_runs, write_regime_path


def _arm(directory: Path, labels: list[str], equity: float, features: list[str]) -> Path:
    """⚠️ Built through `build_manifest` and `write`, never hand-rolled JSON.

    The first version of this fixture wrote the dict by hand and omitted
    `fill_model`, which `read_manifest` requires - so every test failed on the
    FIXTURE rather than on the thing under test. Worse, a hand-built manifest is
    a second definition of the format, which is precisely what
    `write_regime_path` exists to prevent for the regime path.
    """
    directory.mkdir(parents=True, exist_ok=True)
    write_regime_path(
        directory,
        [(f"2026-08-{i + 1:02d}T00:00:00+00:00", label, 1.0) for i, label in enumerate(labels)],
    )
    build_manifest(
        data_dir=directory,
        disabled=[],
        universe=["BHP.AX"],
        starting_equity=100_000.0,
        terminal_equity=equity,
        disabled_feature=None,
        regime_features=features,
    ).write(directory / "manifest.json")
    return directory


_ON = ["log_return", "realized_vol", "credit_spread"]
_OFF = ["log_return", "realized_vol"]


def test_an_unmoved_label_suppresses_every_number(tmp_path) -> None:
    """⚠️ THE GUARD. Nothing changed, so the equity difference is noise wearing
    the feature's name and is suppressed ENTIRELY rather than printed beside a
    caveat."""
    base = _arm(tmp_path / "b", ["bull", "bull"], 105_000.0, _ON)
    abl = _arm(tmp_path / "a", ["bull", "bull"], 98_000.0, _OFF)

    report = compare_feature_runs(base, abl, "credit_spread")

    assert "NOT EXERCISED" in report
    assert "98,000" not in report and "98000" not in report
    assert "105,000" not in report and "105000" not in report


def test_a_not_exercised_result_is_reported_as_an_ANSWER(tmp_path) -> None:
    """Item 66. A column whose removal never moves the label contributes nothing
    to the label - that is a finding to act on, not a failed run."""
    base = _arm(tmp_path / "b", ["bull", "bull"], 105_000.0, _ON)
    abl = _arm(tmp_path / "a", ["bull", "bull"], 98_000.0, _OFF)

    report = compare_feature_runs(base, abl, "credit_spread")

    assert "contributes nothing to the label" in report


def test_a_moved_label_reports_equity_first_then_the_bars(tmp_path) -> None:
    base = _arm(tmp_path / "b", ["bull", "bull"], 105_000.0, _ON)
    abl = _arm(tmp_path / "a", ["bull", "bear"], 98_000.0, _OFF)

    report = compare_feature_runs(base, abl, "credit_spread")

    assert "NOT EXERCISED" not in report
    assert "105,000" in report and "98,000" in report
    assert "1 of 2" in report and "50" in report


def test_a_feature_still_enabled_in_the_ablated_arm_is_refused(tmp_path) -> None:
    """Cheap to cause by passing the wrong directory, and invisible unless
    something checks."""
    base = _arm(tmp_path / "b", ["bull", "bear"], 105_000.0, _ON)
    abl = _arm(tmp_path / "a", ["bull", "bull"], 98_000.0, _ON)

    assert "STILL ENABLED" in compare_feature_runs(base, abl, "credit_spread")


def test_the_report_prints_its_date_range(tmp_path) -> None:
    """⚠️ The 26 August lesson: a three-day calendar slip understated an effect
    NINEFOLD - 2.7% against a true 23.0%. No number here is believable without
    the window it was measured over."""
    base = _arm(tmp_path / "b", ["bull", "bear"], 105_000.0, _ON)
    abl = _arm(tmp_path / "a", ["bull", "bull"], 98_000.0, _OFF)

    report = compare_feature_runs(base, abl, "credit_spread")

    assert "2026-08-01" in report and "2026-08-02" in report


def test_arms_of_different_lengths_are_refused(tmp_path) -> None:
    """⚠️ Two paths of different lengths cannot be compared bar for bar, and
    zipping them would silently compare day 3 of one against day 4 of the other
    - the calendar-slip failure with a different cause."""
    base = _arm(tmp_path / "b", ["bull", "bear", "bull"], 105_000.0, _ON)
    abl = _arm(tmp_path / "a", ["bull", "bull"], 98_000.0, _OFF)

    report = compare_feature_runs(base, abl, "credit_spread")

    assert "NOT COMPARABLE" in report
    assert "3" in report and "2" in report


def test_a_missing_terminal_equity_suppresses_the_headline(tmp_path) -> None:
    """`None` means the run did not record it. Printing 0.00 would assert an
    account worth nothing - M73's scar."""
    base = _arm(tmp_path / "b", ["bull", "bear"], 105_000.0, _ON)
    abl = _arm(tmp_path / "a", ["bull", "bull"], 98_000.0, _OFF)
    raw = json.loads((abl / "manifest.json").read_text(encoding="utf-8"))
    del raw["terminal_equity"]
    (abl / "manifest.json").write_text(json.dumps(raw), encoding="utf-8")

    report = compare_feature_runs(base, abl, "credit_spread")

    assert "not recorded" in report
    # ⚠️ The DELTA must be suppressed, not the digits. An earlier version
    # asserted `"0.00" not in report`, which is false for a legitimate
    # 105,000.00 - an over-broad substring assertion that fails on correct
    # output is its own hazard.
    assert "delta" not in report, (
        "a delta was printed with only one arm's equity known, which asserts a "
        "difference against a number that was never measured"
    )

r"""The stale-figure check must not cry wolf (found while tidying, 28 August).

`handoff_state.py` warns when `docs/HANDOFF.md` states a suite size that no
longer matches. Its pattern was `[\d,]+ tests`, and on 28 August its ENTIRE
output was one false positive: item 22's note that a change "broke 134 tests",
which is a count of what FAILED and is still true.

⚠️ **A checker whose only output is a line you have to know to ignore is a
checker that gets ignored** - and the real stale figure goes past with it. Item
20 makes the same argument about allowlists two days earlier.

⚠️ **And the fix must not overreach in the other direction.** The handoff also
writes "2,903 passed", which this script CANNOT verify: `test_totals` only
collects, so there is no passed count, and comparing it against the collected
total would be wrong by exactly the skip count on every run. A number that
cannot be checked is left alone rather than checked against the nearest number
to hand.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_MODULE = Path(__file__).resolve().parents[2] / "scripts" / "handoff_state.py"
_spec = importlib.util.spec_from_file_location("handoff_state_under_test", _MODULE)
assert _spec and _spec.loader
handoff_state = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(handoff_state)


@pytest.fixture
def handoff(tmp_path, monkeypatch):
    def write(text: str) -> Path:
        path = tmp_path / "HANDOFF.md"
        path.write_text(text, encoding="utf-8")
        monkeypatch.setattr(handoff_state, "HANDOFF", path)
        return path

    return write


def test_a_stale_collected_total_is_reported(handoff) -> None:
    handoff("| Suite | 2,903 passed, 25 skipped (2,929 collected) |")

    stale = handoff_state.stale_figures_in_handoff("2,946 collected")

    assert len(stale) == 1 and "2,929" in stale[0]


def test_a_current_collected_total_is_not_reported(handoff) -> None:
    handoff("| Suite | 2,946 passed, 26 skipped (2,946 collected) |")

    assert handoff_state.stale_figures_in_handoff("2,946 collected") == []


def test_a_historical_failure_count_is_not_a_stale_suite_size(handoff) -> None:
    """⚠️ THE FALSE POSITIVE THIS EXISTS FOR, quoted from item 22."""
    handoff("    ⚠️ **The suite caught a change that broke 134 tests**, and mypy")

    assert handoff_state.stale_figures_in_handoff("2,946 collected") == []


def test_a_passed_count_is_left_alone(handoff) -> None:
    """It differs from `collected` by the skips, so checking it here would
    report a stale figure on every run of a perfectly current handoff."""
    handoff("  Suite 2,920 passed / 26 skipped.")

    assert handoff_state.stale_figures_in_handoff("2,946 collected") == []


def test_nothing_is_claimed_when_the_collection_itself_failed(handoff) -> None:
    """`test_totals` returns 'could not collect' when pytest does not answer.
    Reporting every figure as stale off a failed collection would be the
    loudest possible way to say nothing."""
    handoff("| Suite | 2,929 collected |")

    assert handoff_state.stale_figures_in_handoff("could not collect") == []

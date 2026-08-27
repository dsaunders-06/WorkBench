"""Neither advisory screen may drop an argument the other supplies (item 61).

⚠️ **This guards the CALL SITES, and that is the whole point.** The existing
guard, `test_both_screens_get_the_same_fetched_material`, compares what
`build_advisory_context` FETCHES for itself - symbol, next_earnings, news - and
is silent about what a caller SUPPLIES. Its sibling test says so outright:

    `fundamentals` and `position` are SUPPLIED by the caller, not fetched, so
    asserting the two calls agree on them proves nothing when both default to
    empty

So the suite already knew supplied fields default to empty, and nothing checked
that the Workbench supplied them. It did not. On 27 August the operator ran a
backtest on SUN.AX and read an AI note opening "Given no current positions and
lacking portfolio risk metrics" while the account held 3,192 SUN.AX - because
`positions`, `risk_metrics`, `verdict` and `position` were simply not passed,
each defaulted to None, and nothing errored.

Read from the SOURCE rather than by calling the screens, deliberately: a stub
runtime hands both call sites the same empty account, so a behavioural test
would pass against the very bug it is meant to catch. What went wrong here is
an argument that is not written, and the place that fact lives is the source.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[2] / "src" / "qat" / "presentation"
_CALL = "build_advisory_context"

# Differences that are legitimate, each with the reason it is legitimate. A new
# entry here is a claim that one screen genuinely cannot supply something, and
# should be argued for in review rather than added to make this pass.
_ADVISOR_ONLY = {
    # There is no operator question on the Workbench - the note is unprompted
    # commentary on a backtest.
    "operator_question",
}
_WORKBENCH_ONLY = {
    # The Advisor has no backtest to describe.
    "candidate_signal",
    "backtest_stats",
}


def _keywords(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if name != _CALL:
            continue
        found |= {kw.arg for kw in node.keywords if kw.arg is not None}
    return found


@pytest.fixture(scope="module")
def advisor_kwargs() -> set[str]:
    return _keywords(_SRC / "ai_advisor.py")


@pytest.fixture(scope="module")
def workbench_kwargs() -> set[str]:
    return _keywords(_SRC / "workbench.py")


def test_both_call_sites_were_actually_found(advisor_kwargs, workbench_kwargs) -> None:
    """Or the two tests below pass by comparing two empty sets, which is the
    failure mode of every source-reading guard."""
    assert advisor_kwargs, "no build_advisory_context call parsed out of ai_advisor.py"
    assert workbench_kwargs, "no build_advisory_context call parsed out of workbench.py"


def test_the_workbench_drops_nothing_the_advisor_supplies(advisor_kwargs, workbench_kwargs) -> None:
    missing = advisor_kwargs - workbench_kwargs - _ADVISOR_ONLY
    assert not missing, (
        f"the Workbench's AI note is formed without {sorted(missing)}, which the Advisor "
        f"supplies for the same company. Each defaults to empty and nothing errors, so the "
        f"model is told the account holds nothing (item 61)."
    )


def test_the_advisor_drops_nothing_the_workbench_supplies(advisor_kwargs, workbench_kwargs) -> None:
    """The other direction, because this defect has now appeared twice in one
    call - the regime arguments first, the account facts second - and only one
    direction was ever checked."""
    missing = workbench_kwargs - advisor_kwargs - _WORKBENCH_ONLY
    assert not missing, f"the Advisor is formed without {sorted(missing)}"

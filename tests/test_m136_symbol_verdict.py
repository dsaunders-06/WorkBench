"""Both screens ask about a symbol; both must be given the same material.

The Workbench passed `regime_label="unknown"` while the Advisor passed the live
regime, so the two could reach different views of one company at one moment for
no stated reason. One builder is what stops that returning - two copies drift,
and the one that drifts is the one nobody is reading.

The macro fields are deliberately NOT part of that material; see the test below
that pins the decision rather than leaving a gap for someone to "fix".
"""

from __future__ import annotations

import pytest

from qat.presentation.advisory_inputs import build_advisory_context

# The material the builder FETCHES for itself. Both screens must receive the
# same of it, because differing on it is what let the two reach different views
# of one company.
_FETCHED = ("symbol", "next_earnings", "news")


@pytest.mark.asyncio
async def test_both_screens_get_the_same_fetched_material(advisory_runtime):
    """`advisory_runtime` is a stub runtime; see the conftest fixture."""
    advisor = await build_advisory_context(
        advisory_runtime, "BHP.AX", operator_question="is it cheap?"
    )
    workbench = await build_advisory_context(
        advisory_runtime, "BHP.AX", candidate_signal={"strategy": "swing"}
    )

    for field in _FETCHED:
        assert getattr(advisor, field) == getattr(workbench, field), field


@pytest.mark.asyncio
async def test_supplied_material_is_carried_through_unswapped(advisory_runtime):
    """`fundamentals` and `position` are SUPPLIED by the caller, not fetched, so
    asserting the two calls agree on them proves nothing when both default to
    empty - which is what an earlier version of this file did, twice.

    Passing different values and checking each lands where it was put is the
    version that can fail: it catches a builder that swapped two arguments, or
    dropped one, which the equality form could not see."""
    context = await build_advisory_context(
        advisory_runtime,
        "BHP.AX",
        fundamentals={"pe": 14.2},
        position={"entry_price": 40.0, "pnl_r": -0.21},
    )

    assert context.fundamentals == {"pe": 14.2}
    assert context.position == {"entry_price": 40.0, "pnl_r": -0.21}
    assert context.fundamentals != context.position


@pytest.mark.asyncio
async def test_the_workbench_no_longer_claims_the_regime_is_unknown(advisory_runtime):
    context = await build_advisory_context(
        advisory_runtime, "BHP.AX", regime_label="low_vol", regime_probs={"low_vol": 0.6}
    )
    assert context.regime_label == "low_vol"


@pytest.mark.asyncio
async def test_the_macro_fields_stay_empty_and_that_is_deliberate(advisory_runtime):
    """Not an oversight. `compute_macro_signal` needs an awaited bars fetch and
    the Regime Monitor computes it only on demand, so there is no current value
    to pass and wiring one here would mean a vendor call per question. Pinned
    so the next reader finds the decision rather than the gap."""
    context = await build_advisory_context(advisory_runtime, "BHP.AX")
    assert context.macro_signal == {}
    assert context.macro_series == {}


@pytest.mark.asyncio
async def test_one_question_fetches_the_news_once(advisory_runtime):
    """The Advisor used to fetch news TWICE per question - once for the sources
    block it shows the operator, once inside the builder for the model.

    `news_for` calls the vendor live every time and degrades silently to [] on
    failure, so two round trips milliseconds apart can disagree: a story
    publishes between them, or the second fails where the first succeeded. The
    operator would then be shown stories the model never received - M126's
    defect exactly, reproduced inside one screen.

    Counting the fetches is the only way to see it; the displayed text and the
    context agree in the happy path either way."""
    calls: list[str] = []

    class _CountingSource:
        def fetch(self, symbol: str) -> list:
            calls.append(symbol)
            return []

    advisory_runtime.news_source = _CountingSource()

    await build_advisory_context(advisory_runtime, "BHP.AX")

    assert calls == ["BHP.AX"], f"expected exactly one fetch, got {len(calls)}"

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

_PER_SYMBOL = ("symbol", "next_earnings", "news", "fundamentals", "position")


@pytest.mark.asyncio
async def test_both_screens_get_the_same_per_symbol_material(advisory_runtime):
    """`advisory_runtime` is a stub runtime; see conftest note in Step 3."""
    advisor = await build_advisory_context(
        advisory_runtime, "BHP.AX", operator_question="is it cheap?"
    )
    workbench = await build_advisory_context(
        advisory_runtime, "BHP.AX", candidate_signal={"strategy": "swing"}
    )

    for field in _PER_SYMBOL:
        assert getattr(advisor, field) == getattr(workbench, field), field


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

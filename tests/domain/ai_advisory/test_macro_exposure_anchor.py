"""The model proposing an exposure scalar must be told what the scale MEANS
(item 62).

Found by the operator on 27 August. The Regime Monitor rendered, one line above
the other:

    Deterministic read (STW.AX): Risk-On ... Exposure hint 1.00.
    Proposed exposure scalar: 0.40  (proposal only - not applied)

⚠️ **The model that produced 0.40 was never shown the 1.00.** `MacroSignal`
computes `exposure_hint` as a property, the screen renders it, and
`to_dict()` - the ONLY part of the signal that reaches the prompt - does not
carry it. So the screen invites a comparison between two numbers where only one
side had the relevant input.

⚠️ **And 0.40 is not a value the macro read can produce.** There are two
exposure vocabularies in this codebase and they are different scales:

    MACRO_REGIME_EXPOSURE_HINT  risk_on 1.0  neutral 0.85  caution 0.6  risk_off 0.3
    _EXPOSURE_SCALARS           bull 1.0 ... sideways 0.7  bear 0.5  high_vol 0.4 ...

0.40 exists only in the second, which belongs to the HMM regime engine and is
not what this screen is proposing a revision to. The schema allows any float in
[0, 1] and the prompt named neither table, so the figure could not be checked
against anything.

**This is NOT item 61.** `get_macro_assessment` passes `positions={}` on
purpose, and says why: *"this is a market-wide question, and keeping positions
out is what lets LLMRouter send it to the general slot rather than forcing the
sensitive one."* That is a considered routing decision, not an omission.
"""

from __future__ import annotations

import pandas as pd
import pytest

from qat.domain.ai_advisory.context import AdvisoryContext
from qat.domain.ai_advisory.prompts import build_macro_analysis_prompt
from qat.domain.macro_analysis.signal import (
    MACRO_REGIME_EXPOSURE_HINT,
    MIN_BARS_FOR_MACRO_SIGNAL,
    compute_macro_signal,
)


def _context(signal) -> AdvisoryContext:
    """`AdvisoryContext`'s required arguments spelled out once. The macro path
    passes empty positions and risk metrics DELIBERATELY - see this module's
    docstring - so an empty here mirrors production rather than papering over
    item 61."""
    return AdvisoryContext(
        symbol="ASX",
        regime_label="bull",
        regime_probs={"bull": 0.47},
        positions={},
        risk_metrics={},
        candidate_signal={},
        macro_signal=signal.to_dict(),
    )


def _signal(trend: float = 1.0):
    """A real `MacroSignal` from real bars - never a hand-built stub, because
    what is under test is what `to_dict` chooses to carry."""
    n = MIN_BARS_FOR_MACRO_SIGNAL + 10
    closes = [100.0 * (trend ** (i / n)) for i in range(n)]
    bars = pd.DataFrame({"close": closes})
    signal = compute_macro_signal(bars)
    assert signal is not None
    return signal


def test_the_exposure_hint_reaches_the_prompt() -> None:
    """The defect. The screen shows the operator a deterministic exposure hint
    and asks the model for a scalar beside it; the model must see the hint."""
    payload = _signal().to_dict()

    assert "exposure_hint" in payload, (
        "MacroSignal.to_dict() does not carry exposure_hint, so the model proposing a "
        "scalar has never seen the one the deterministic read justifies (item 62)."
    )


def test_the_hint_carried_is_the_one_the_screen_renders() -> None:
    """Carrying a DIFFERENT number would be worse than carrying none - the
    operator would be comparing the model against a figure nobody showed it."""
    signal = _signal()

    assert signal.to_dict()["exposure_hint"] == pytest.approx(signal.exposure_hint)
    assert signal.exposure_hint == MACRO_REGIME_EXPOSURE_HINT[signal.suggested_regime]


def test_the_prompt_names_the_scale_the_proposal_is_on() -> None:
    """`suggested_exposure_scalar` is `Field(ge=0.0, le=1.0)` and nothing else,
    so without this the model is free-picking a number on no stated scale."""
    prompt = build_macro_analysis_prompt(_context(_signal()))

    for regime, hint in MACRO_REGIME_EXPOSURE_HINT.items():
        assert regime in prompt, f"the prompt does not name the {regime} anchor"
        assert f"{hint:.2f}" in prompt, f"the prompt does not give {regime}'s value"


def test_the_prompt_says_the_scalar_is_a_revision_of_the_hint() -> None:
    """Not merely "here is a table". The model has to know its number is on the
    SAME scale as the hint, or naming the table just adds four more numbers it
    is free to ignore."""
    prompt = build_macro_analysis_prompt(_context(_signal()))

    assert "exposure_hint" in prompt
    assert "same scale" in prompt.lower()


def test_the_regime_engine_scale_is_not_named() -> None:
    """⚠️ The OTHER table must stay out. `_EXPOSURE_SCALARS` belongs to the HMM
    regime engine, which owns `RiskEngine.regime_scalar` and is deliberately the
    only writer of it. Showing the model a second scale is how 0.40 - a value
    that exists only there - came to be proposed on a screen that cannot produce
    it."""
    prompt = build_macro_analysis_prompt(_context(_signal()))

    for hmm_only in ("high_vol", "recession", "sideways"):
        assert hmm_only not in prompt, f"the macro prompt names {hmm_only}, an HMM regime"

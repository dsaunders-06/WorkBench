"""The narrative prompt must ask the model to weigh what is already held (item 65).

Fell out of item 61's confirmation on 28 August. The audit line proved the
context carried all ten positions and `SUN.AX ... IS held`, and the Workbench
note still made no reference to the holding.

That was the model's choice, not missing data - and it was a reasonable choice,
because `build_regime_narrative_prompt` asks for "the current market regime and
what it implies for positioning" and **never asks it to weigh EXISTING
exposure**. It has the position and no instruction to use it.

⚠️ Item 61 was justified partly on the model being able to temper a
recommendation with concentration and existing exposure. Supplying the facts
without asking for them delivers half of that.

⚠️ **This does NOT make the note a risk control.** The rails decide; the note
comments. The prompt says so, so that a model told to consider exposure does not
start reporting on it as though it were enforcing anything.
"""

from __future__ import annotations

import pytest

from qat.domain.ai_advisory.context import AdvisoryContext
from qat.domain.ai_advisory.prompts import build_regime_narrative_prompt


def _context(**overrides) -> AdvisoryContext:
    base = {
        "symbol": "SUN.AX",
        "regime_label": "bull",
        "regime_probs": {"bull": 0.47},
        "positions": {"SUN.AX": 3192.0, "A2M.AX": 9636.0},
        "risk_metrics": {},
        "candidate_signal": {},
    }
    return AdvisoryContext(**{**base, **overrides})


def test_the_prompt_asks_the_model_to_weigh_existing_exposure() -> None:
    prompt = build_regime_narrative_prompt(_context())

    lowered = prompt.lower()
    assert "already held" in lowered or "existing exposure" in lowered, (
        "the prompt never asks the model to weigh what the account already holds, so it "
        "receives the positions and has no instruction to use them (item 65)"
    )


def test_it_names_concentration_rather_than_gesturing_at_risk() -> None:
    """ "Consider risk" is not an instruction. The specific thing an operator
    wants tempered is a recommendation on a name they are already heavy in."""
    assert "concentration" in build_regime_narrative_prompt(_context()).lower()


def test_it_says_the_note_is_commentary_and_not_a_rail() -> None:
    """⚠️ The line that stops this becoming worse than the gap it fills. Telling
    a model to weigh exposure invites it to sound like a control; the rails
    decide, and the note must not read as though it had."""
    lowered = build_regime_narrative_prompt(_context()).lower()

    assert "not a risk control" in lowered or "does not decide" in lowered


def test_the_positions_still_reach_the_prompt() -> None:
    """The instruction is worthless without the data - which is item 61, and is
    what this builds on rather than replaces."""
    assert "SUN.AX" in build_regime_narrative_prompt(_context())


def test_an_empty_book_does_not_invite_an_invented_holding() -> None:
    """⚠️ A standing instruction to weigh exposure, given an empty positions
    dict, is an invitation to discuss a position that does not exist. The
    instruction must be conditional on there being one."""
    prompt = build_regime_narrative_prompt(_context(positions={}))

    lowered = prompt.lower()
    assert "already held" not in lowered and "concentration" not in lowered, (
        "the exposure instruction is unconditional, so a flat account is told to weigh "
        "holdings it does not have"
    )


@pytest.mark.parametrize("held", [{"BHP.AX": 10.0}, {"SUN.AX": 3192.0, "A2M.AX": 9636.0}])
def test_the_instruction_appears_whenever_anything_is_held(held: dict[str, float]) -> None:
    """Not only when the symbol under discussion is held: concentration is about
    the BOOK, and a note on SUN.AX should still weigh five financials of ten."""
    assert "concentration" in build_regime_narrative_prompt(_context(positions=held)).lower()

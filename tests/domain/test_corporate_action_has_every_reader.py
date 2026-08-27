"""Every screen where this matters reads it, and a test says so (M39, R1).

The generic guard in `test_computed_values_have_readers` asserts that SOMETHING
in `src/` reads a computed value. **That is a weaker claim than this one**, and
the difference is the whole history of the defect it was built for:
`is_synthetic` had a reader from M40 - the language model - and the operator did
not see it until M72. A guard that accepts any reader would have passed it for
two milestones.

So this names the modules. A corporate action visible on the Risk Console and
nowhere else is the same defect with a new name, and the operator's requirement
was explicit: the state cannot be lost moving across screens where it matters
most, and it has to be available to autonomous decision-making.

A file scan, deliberately. It proves the wiring exists; the rendering tests in
`tests/presentation/test_corporate_action_visibility.py` prove it reaches a
widget. Both are needed - M63's orphaned grid row passed every logic test it
had.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import qat

_SRC = Path(qat.__file__).parent

# Where a pending corporate action bears on what the operator or the model is
# about to decide. Each entry is a claim about consequence, not a wish list.
_MUST_READ = {
    "presentation/dashboard.py": "the first screen, and where a held position is listed",
    "presentation/risk_console.py": "the screen that answers why an order was refused",
    "presentation/blotter.py": "where the adjustment itself appears as an order",
    "presentation/workbench.py": "where a proposal must not read as clean",
    "presentation/screener.py": "where a candidate must not read as clean",
    # ⚠️ WAS `presentation/ai_advisor.py`. The read moved to `advisory_account.py`
    # in item 61, and the entry moved WITH it rather than being deleted - a
    # guard that quietly stops naming a file is this module's own stated
    # failure mode. The claim is unchanged and now covers MORE: the Advisor
    # was the only screen whose PROMPT carried these notes, and both do now.
    # `workbench.py` keeps its own separate entry above because its read at
    # `:328` feeds the DISPLAY, which is a different consequence.
    "presentation/advisory_account.py": "the model must not reason about a share count "
    "about to change - and BOTH advisory screens now reason from this one read",
    "domain/performance/reports.py": "the daily report is read when nobody watched the session",
}


@pytest.mark.parametrize("module", sorted(_MUST_READ))
def test_the_module_reads_the_pending_action(module):
    source = (_SRC / module).read_text(encoding="utf-8")

    assert "pending_action" in source, (
        f"{module} does not read pending_action, and it must: {_MUST_READ[module]}. "
        f"A corporate action visible on one screen and not the others is the defect this "
        f"project has already found six times."
    )


def test_the_list_names_modules_that_exist():
    """An allowlist naming a file that has been renamed is how a guard quietly
    stops covering anything - the M78 lesson about M75's colour guard."""
    for module in _MUST_READ:
        assert (_SRC / module).exists(), module


def test_every_entry_gives_a_reason():
    """The reason is what a later reader argues with, and it is the only thing
    separating this list from a rubber stamp."""
    for module, reason in _MUST_READ.items():
        assert len(reason) > 25, f"{module} needs a real reason, not a label"


# The indirection the entry above introduces, pinned. A guard that names the
# module holding the read is worth nothing if the screens stop reaching it, and
# "the read exists somewhere" is precisely the weaker claim this file's own
# docstring rejects.
_MUST_REACH_THE_ACCOUNT_FACTS = {
    "presentation/ai_advisor.py": "the Advisor's prompt",
    "presentation/workbench.py": "the Workbench's AI note - which had NO account "
    "facts at all until item 61",
}


@pytest.mark.parametrize("module", sorted(_MUST_REACH_THE_ACCOUNT_FACTS))
def test_both_advisory_screens_reach_the_shared_account_facts(module):
    source = (_SRC / module).read_text(encoding="utf-8")
    assert "advisory_account" in source, (
        f"{module} no longer reaches advisory_account, so {_MUST_REACH_THE_ACCOUNT_FACTS[module]} "
        f"has lost the pending corporate action along with every other account fact (item 61)."
    )

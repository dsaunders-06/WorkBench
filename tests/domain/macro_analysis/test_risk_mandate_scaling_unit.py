"""`SB` - the baseline scaling unit, chosen as a named mandate.

Phase 1 of `docs/superpowers/specs/2026-09-08-macro-regime-matrix-design.md`.
Every exposure shift the 7-regime matrix proposes is scaled by `SB`, so it is
the single most consequential constant in the calculation.

Operator definition, 8 September 2026: *"The baseline multiplier used to scale
exposure shifts. Total portfolio swings are dynamic and can exceed this value
during extreme market stress to ensure adequate downside protection."*

⚠️ NOT A CAP, AND THE TESTS BELOW MUST NOT IMPLY ONE. An earlier version of this
file called SB a "safety buffer" that "caps the maximum exposure change at
+/- SB", and the arithmetic never kept that promise: `((RV - HV) / HV) * SB` is
unbounded above in a BEAR regime, RECOVERY adds a flat 0.05 on top, SHOCK is a
flat 0.10 and RECESSION halves the baseline outright. On a moderate mandate a
bear market with RV at three times HV computes a 40% cut.

That behaviour is INTENDED - a downside response that stopped at the unit would
under-protect in exactly the conditions it exists for - so the DEFINITION
changed rather than the maths, and the constants were renamed with it. A name
carrying the word "buffer" re-teaches the misconception to every later reader.

⚠️ A NAMED MANDATE, NOT A FREE FLOAT, at the operator's direction. "Why is the
unit 0.27?" has no answer a reader can audit; "the account is on a conservative
mandate" does. The same reasoning `trading_mode` and `execution_mode` follow.
"""

from __future__ import annotations

import pytest

from qat.config import Settings
from qat.domain.macro_analysis.signal import MANDATE_SCALING_UNIT, scaling_unit_for


def test_the_default_mandate_is_moderate() -> None:
    """0.20, the operator's stated baseline."""
    assert Settings(_env_file=None).macro_risk_mandate == "moderate"
    assert scaling_unit_for(Settings(_env_file=None).macro_risk_mandate) == 0.20


@pytest.mark.parametrize(
    ("mandate", "unit"),
    [("conservative", 0.10), ("moderate", 0.20), ("aggressive", 0.35)],
)
def test_each_mandate_carries_its_stated_unit(mandate: str, unit: float) -> None:
    assert scaling_unit_for(mandate) == unit
    assert Settings(_env_file=None, macro_risk_mandate=mandate).macro_risk_mandate == mandate


def test_the_mandates_are_ordered_by_appetite() -> None:
    """⚠️ Pinned as a RELATIONSHIP, not three constants. A future edit that made
    conservative looser than moderate would pass three separate equality tests
    and still be nonsense."""
    assert (
        MANDATE_SCALING_UNIT["conservative"]
        < MANDATE_SCALING_UNIT["moderate"]
        < MANDATE_SCALING_UNIT["aggressive"]
    )


def test_an_unknown_mandate_is_refused_rather_than_defaulted() -> None:
    """⚠️ Falling back to moderate on an unrecognised value would run an account
    on a responsiveness nobody chose, and say nothing. A startup error is the
    honest failure - the operator finds out before the open, not after."""
    with pytest.raises(ValueError):
        Settings(_env_file=None, macro_risk_mandate="reckless")

    with pytest.raises(KeyError):
        scaling_unit_for("reckless")


def test_every_unit_is_a_fraction_not_a_percentage() -> None:
    """⚠️ 0.20 and 20.0 differ by a hundred times in every formula that consumes
    this. The matrix multiplies by SB directly."""
    assert all(0.0 < value < 1.0 for value in MANDATE_SCALING_UNIT.values())

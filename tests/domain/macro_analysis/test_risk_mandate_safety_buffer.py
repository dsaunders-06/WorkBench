"""`SB` - the safety buffer, chosen as a named mandate rather than a number.

Phase 1 of `docs/superpowers/specs/2026-09-08-macro-regime-matrix-design.md`.
Every lift and cut in the 7-regime matrix is scaled by `SB`, so it is the single
most consequential constant in the whole calculation.

⚠️ A NAMED MANDATE, NOT A FREE FLOAT, at the operator's direction. Three fixed
appetites - conservative 0.10, moderate 0.20, aggressive 0.35 - because "why is
the buffer 0.27?" has no answer a reader can audit, where "the account is on a
conservative mandate" does. The same reasoning `trading_mode` and
`execution_mode` already follow.

⚠️ AND THE MANDATE DESCRIPTIONS PROMISE A CAP THE DOCUMENT'S MATH DOES NOT KEEP.
Each is written as "caps the maximum exposure change at +/- SB". That holds for
the two LIFT regimes, where `(HV - RV) / HV` cannot exceed 1 while RV is
positive. It does NOT hold for:

  * BEAR, where `Cut = ((RV - HV) / HV) * SB` and `(RV - HV) / HV` is unbounded
    above - RV at three times HV gives a cut of 2 * SB, double the stated cap;
  * RECOVERY, which adds a flat 0.05 kicker ON TOP of the buffer;
  * SHOCK, a flat 0.10 regardless of SB;
  * RECESSION, `BM * 0.50`, which ignores SB entirely.

These tests pin the mandate values only. Whether the cap is ENFORCED is a Phase 3
decision recorded in the spec, and is deliberately not assumed here.
"""

from __future__ import annotations

import pytest

from qat.config import Settings
from qat.domain.macro_analysis.signal import MANDATE_SAFETY_BUFFER, safety_buffer_for


def test_the_default_mandate_is_moderate() -> None:
    """0.20, the operator's stated baseline."""
    assert Settings(_env_file=None).macro_risk_mandate == "moderate"
    assert safety_buffer_for(Settings(_env_file=None).macro_risk_mandate) == 0.20


@pytest.mark.parametrize(
    ("mandate", "buffer"),
    [("conservative", 0.10), ("moderate", 0.20), ("aggressive", 0.35)],
)
def test_each_mandate_carries_its_stated_buffer(mandate: str, buffer: float) -> None:
    assert safety_buffer_for(mandate) == buffer
    assert Settings(_env_file=None, macro_risk_mandate=mandate).macro_risk_mandate == mandate


def test_the_mandates_are_ordered_by_appetite() -> None:
    """⚠️ Pinned as a RELATIONSHIP, not three constants. A future edit that made
    conservative looser than moderate would pass three separate equality tests
    and still be nonsense."""
    assert (
        MANDATE_SAFETY_BUFFER["conservative"]
        < MANDATE_SAFETY_BUFFER["moderate"]
        < MANDATE_SAFETY_BUFFER["aggressive"]
    )


def test_an_unknown_mandate_is_refused_rather_than_defaulted() -> None:
    """⚠️ Falling back to moderate on an unrecognised value would run an account
    on a buffer nobody chose, and say nothing. A startup error is the honest
    failure - the operator finds out before the market opens, not after."""
    with pytest.raises(ValueError):
        Settings(_env_file=None, macro_risk_mandate="reckless")

    with pytest.raises(KeyError):
        safety_buffer_for("reckless")


def test_every_buffer_is_a_fraction_not_a_percentage() -> None:
    """⚠️ 0.20 and 20.0 differ by a hundred times in every formula that consumes
    this. The matrix multiplies by SB directly."""
    assert all(0.0 < value < 1.0 for value in MANDATE_SAFETY_BUFFER.values())

"""What `BM` is, derived from the rails rather than picked.

`decide` requires a baseline and deliberately refuses to default one. The
docstring says why: it used to fall back to `MacroSignal.exposure_hint`, which
is the FOUR-regime read's answer, so the matrix could report a Bull market while
lifting from a 0.30 baseline the other classifier had set because it saw
Risk-Off - two taxonomies stacked, silently.

So the caller must state `BM`, and the honest source is the account's own risk
budget. `config.py` already spells the arithmetic out beside
`max_gap_risk_at_shock_pct`: a 5% gap budget against a 6% gap shock "implies a
gross-exposure ceiling of about 83% of equity". That is exactly what a baseline
should be - the exposure the deterministic rails alone justify holding, computed
from settings the operator can see and change, and owing nothing to any regime
classifier.
"""

from __future__ import annotations

import pytest

from qat.config import Settings
from qat.domain.macro_analysis.matrix import baseline_from_risk_budget


def test_the_shipped_budget_gives_the_ceiling_config_documents() -> None:
    """⚠️ 83% is not a constant typed in here - it is 0.05 / 0.06, and
    `config.py` states that figure in prose beside the setting it comes from."""
    settings = Settings(_env_file=None)

    baseline = baseline_from_risk_budget(settings.max_gap_risk_at_shock_pct, settings.gap_shock_pct)

    assert baseline == pytest.approx(0.8333, abs=0.0005)


def test_a_tighter_budget_lowers_the_baseline() -> None:
    """The point of deriving it: an operator who halves the gap budget has
    halved what the rails justify holding, and the matrix should lift from
    there rather than from a figure that never moved."""
    assert baseline_from_risk_budget(0.025, 0.06) == pytest.approx(0.4167, abs=0.0005)


def test_a_budget_wider_than_the_shock_still_baselines_at_fully_invested() -> None:
    """⚠️ THE CLAMP IS ON `BM` AND ONLY ON `BM`. A budget of 10% against a 6%
    shock implies holding 167% of equity as the NORMAL state, which is not a
    baseline. The matrix's TARGET remains unclamped by design - a lift may
    exceed 100% and `implies_leverage` surfaces that - but the thing being
    lifted FROM is fully invested at most."""
    assert baseline_from_risk_budget(0.10, 0.06) == 1.0


def test_a_zero_shock_is_refused_rather_than_divided_by() -> None:
    """`Settings` constrains this above zero, so reaching here means a caller
    built the numbers itself. Returning infinity would put an infinite target
    on screen."""
    with pytest.raises(ValueError, match="gap shock"):
        baseline_from_risk_budget(0.05, 0.0)


def test_a_negative_budget_is_refused() -> None:
    with pytest.raises(ValueError, match="gap budget"):
        baseline_from_risk_budget(-0.01, 0.06)

"""Three hazards the matrix carried on the day it was written.

Raised in review on 8 September 2026, before Phase 4 gave the matrix a consumer:

1. **Stale growth could drive present-tense advice.** `GrowthRead.age_days`
   existed and nothing consulted it. With quarterly GDP a RECESSION call could be
   computed from data five months old and rendered as "the economy is
   contracting, cut to 42.5%" while the market had already turned. Confident
   advice about the last war.

2. **`BM` came from a DIFFERENT taxonomy than the matrix's own.** `baseline`
   defaulted to `MacroSignal.exposure_hint`, which is the FOUR-regime read's
   answer. So the matrix could say "this is a Bull market" and lift from a
   baseline of 0.30 that the other classifier set because it saw Risk-Off. Two
   regime systems stacked, silently.

3. **"Advisory only" was prose, not a mechanism.** The operator's instruction -
   *"this sits outside of the authority of autonomy, resultant action must be
   human driven only for now"* - lived in comments. Every other safety boundary
   in this codebase has a test.
"""

from __future__ import annotations

import ast
from datetime import UTC, datetime
from pathlib import Path

import pytest
from support.source_corpus import source_files

from qat.domain.macro_analysis.growth import GrowthRead
from qat.domain.macro_analysis.matrix import MAX_GROWTH_AGE_DAYS, MatrixRefusal, decide
from qat.domain.macro_analysis.signal import MacroSignal

_SB = 0.20


def _signal(rv: float = 8.74, hv: float | None = 15.0) -> MacroSignal:
    return MacroSignal(
        realized_vol_annualized_pct=rv,
        vol_direction="steady",
        vix_shock=False,
        term_structure="normal",
        spreads="normal",
        baseline_vol_annualized_pct=hv,
        pct_above_trend=1.0,
        drawdown_from_recent_high_pct=1.69,
        suggested_regime="neutral",
        elevated_volatility=False,
        below_trend=False,
    )


def _growth(age_days: int, yoy: float = 2.0) -> GrowthRead:
    return GrowthRead(
        series="GDPC1",
        yoy_pct=yoy,
        direction="flattening",
        as_of=datetime(2026, 6, 30, tzinfo=UTC),
        age_days=age_days,
    )


# --- 1. staleness ---------------------------------------------------------


def test_a_fresh_growth_reading_is_used() -> None:
    result = decide(_signal(), _growth(age_days=70), scaling_unit=_SB, baseline=0.85)

    assert not isinstance(result, MatrixRefusal)


def test_growth_older_than_the_limit_is_REFUSED_not_used() -> None:
    """⚠️ THE HAZARD THIS FILE EXISTS FOR. A confident regime computed from data
    two quarters out of date is worse than no regime: it reads as current."""
    result = decide(
        _signal(), _growth(age_days=MAX_GROWTH_AGE_DAYS + 1), scaling_unit=_SB, baseline=0.85
    )

    assert isinstance(result, MatrixRefusal)
    assert any("old" in reason or "stale" in reason for reason in result.missing)


def test_the_refusal_says_how_old_the_reading_actually_was() -> None:
    """A limit without the measured value leaves the operator unable to judge
    whether the series has stalled or is merely between publications."""
    result = decide(_signal(), _growth(age_days=400), scaling_unit=_SB, baseline=0.85)

    assert isinstance(result, MatrixRefusal)
    assert "400" in result.detail


def test_the_limit_allows_an_ordinary_quarterly_publication_cycle() -> None:
    """⚠️ Set too tight, this refuses every day of a normal quarter and the
    matrix never speaks. Australian GDP for a quarter ending 30 June is
    published near the end of August, so a reading is routinely 60-155 days old
    without anything being wrong."""
    assert MAX_GROWTH_AGE_DAYS > 155


# --- 2. the baseline mismatch --------------------------------------------


def test_the_baseline_must_be_supplied_and_is_never_borrowed() -> None:
    """⚠️ `baseline` no longer defaults to `MacroSignal.exposure_hint`. That
    figure is the FOUR-regime read's answer, and letting the seven-regime matrix
    adjust it silently stacked two taxonomies: a Bull regime could lift from a
    Risk-Off baseline of 0.30. The caller now states what BM is."""
    with pytest.raises(TypeError):
        decide(_signal(), _growth(age_days=70), scaling_unit=_SB)  # type: ignore[call-arg]


def test_the_decision_reports_the_baseline_it_was_given() -> None:
    result = decide(_signal(), _growth(age_days=70), scaling_unit=_SB, baseline=0.60)

    assert not isinstance(result, MatrixRefusal)
    assert result.baseline == 0.60


# --- 3. advisory only, as a mechanism ------------------------------------


def _imports_of(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
        elif isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
    return found


def test_no_trading_path_module_imports_the_matrix() -> None:
    """⚠️ THE OPERATOR'S CONSTRAINT, ENFORCED RATHER THAN DESCRIBED.
    "This sits outside of the authority of autonomy, resultant action must be
    human driven only for now."

    Nothing that can size, gate or send an order may reach this module. Prose in
    a docstring does not stop a future edit; this does.
    """
    root = Path(__file__).resolve().parents[3] / "src" / "qat"
    trading_path = [
        root / "domain" / "risk_engine",
        root / "domain" / "oms",
        root / "domain" / "autonomy",
        root / "domain" / "strategies",
        # ⚠️ Added when the friction detector was built: `regime_engine` OWNS
        # `RiskEngine.regime_scalar`, so it is as much the trading path as the
        # sizer is. It was missing from the first version of this guard.
        root / "domain" / "regime_engine",
    ]
    # ⚠️ `source_files`, not `rglob`. Caught by
    # `test_source_scanning_guards_cannot_go_blind` on this file's FIRST run:
    # a bare glob that matched nothing - a moved package, a renamed directory -
    # would report a clean codebase because it scanned none of it. The
    # `minimum` is the corpus check that makes "we looked" a measured claim.
    offenders = []
    for area in trading_path:
        for module in source_files(area, recurse=True, minimum=3):
            if any("macro_analysis.matrix" in name for name in _imports_of(module)):
                offenders.append(str(module.relative_to(root)))

    assert offenders == [], (
        f"the macro matrix reached the trading path via {offenders}. It is advisory "
        f"only by operator instruction - it computes, a person acts."
    )

"""The 7-regime matrix: one regime, one target, exact arithmetic.

Phase 3 of `docs/superpowers/specs/2026-09-08-macro-regime-matrix-design.md`.

⚠️ THE ARITHMETIC IS ASSERTED EXACTLY, not approximately. This is the whole
reason the calculation is deterministic rather than asked of a model: an
exposure target that is nearly right is a different number, and nobody would
know which one they had.

⚠️ NOTHING CLAMPS TO `+/- SB`, AND THE TESTS MUST NOT ASK IT TO. `SB` is the
risk scaling unit, not a cap - operator definition, 8 September: "total
portfolio swings are dynamic and can exceed this value during extreme market
stress to ensure adequate downside protection". A bear cut is unbounded above,
recovery adds a kicker on top, shock is flat and recession halves outright. A
test demanding a cap would re-impose the misconception the naming was changed
to remove.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from qat.domain.macro_analysis.growth import GrowthRead
from qat.domain.macro_analysis.matrix import MatrixRefusal, RegimeDecision, decide
from qat.domain.macro_analysis.signal import MacroSignal

_SB = 0.20


def _signal(
    *,
    rv: float,
    hv: float | None = 15.0,
    vol_direction: str | None = "steady",
    vix_shock: bool | None = False,
    spreads: str | None = "normal",
    regime: str = "neutral",
) -> MacroSignal:
    return MacroSignal(
        realized_vol_annualized_pct=rv,
        vol_direction=vol_direction,  # type: ignore[arg-type]
        vix_shock=vix_shock,
        term_structure="normal",
        spreads=spreads,  # type: ignore[arg-type]
        baseline_vol_annualized_pct=hv,
        pct_above_trend=1.0,
        drawdown_from_recent_high_pct=1.69,
        suggested_regime=regime,  # type: ignore[arg-type]
        elevated_volatility=rv >= 25.0,
        below_trend=False,
    )


def _growth(yoy: float, direction: str | None = "flattening") -> GrowthRead:
    return GrowthRead(
        series="GDPC1",
        yoy_pct=yoy,
        direction=direction,  # type: ignore[arg-type]
        as_of=datetime(2026, 6, 30, tzinfo=UTC),
        age_days=70,
    )


# --- refusal --------------------------------------------------------------


def test_no_growth_series_refuses_every_regime() -> None:
    """⚠️ TODAY'S ACTUAL BEHAVIOUR, and the spec requires it. Every regime keys
    on growth; with no series named there is nothing to key on, and "sideways"
    would be calm this matrix never measured."""
    result = decide(_signal(rv=8.74), growth=None, scaling_unit=_SB, baseline=0.85)

    assert isinstance(result, MatrixRefusal)
    assert any("growth" in reason for reason in result.missing)
    assert "QAT_MACRO_GROWTH_SERIES" in result.detail


def test_no_baseline_volatility_also_refuses() -> None:
    """Every formula divides by HV. Without it there is no arithmetic to do."""
    result = decide(_signal(rv=8.74, hv=None), growth=_growth(2.0), scaling_unit=_SB, baseline=0.85)

    assert isinstance(result, MatrixRefusal)
    assert any("baseline volatility" in reason for reason in result.missing)


def test_a_refusal_names_everything_that_was_missing() -> None:
    result = decide(_signal(rv=8.74, hv=None), growth=None, scaling_unit=_SB, baseline=0.85)

    assert isinstance(result, MatrixRefusal)
    assert len(result.missing) == 2


# --- the seven regimes ----------------------------------------------------


def test_bull_lifts_by_the_full_scaled_gap() -> None:
    """High growth, quiet market. Lift = ((HV - RV) / HV) * SB."""
    result = decide(_signal(rv=8.74), growth=_growth(4.0), scaling_unit=_SB, baseline=0.85)

    assert isinstance(result, RegimeDecision)
    assert result.regime == "bull"
    expected = ((15.0 - 8.74) / 15.0) * _SB
    assert result.change == pytest.approx(expected)
    assert result.target_weight == pytest.approx(0.85 + expected)


def test_bear_cuts_and_is_not_capped_at_the_scaling_unit() -> None:
    """⚠️ THE TEST THE NAMING CHANGE EXISTS FOR. RV at three times HV gives a
    cut of 2 * SB - forty per cent on a moderate mandate - and that is the
    intended dynamic response, not an overflow to clamp."""
    result = decide(_signal(rv=45.0), growth=_growth(-1.0), scaling_unit=_SB, baseline=0.85)

    assert isinstance(result, RegimeDecision)
    assert result.regime == "bear"
    expected = ((45.0 - 15.0) / 15.0) * _SB  # 0.40
    assert result.change == pytest.approx(-expected)
    assert expected > _SB, "the fixture must actually exceed SB or it proves nothing"
    assert result.target_weight == pytest.approx(0.45)


def test_a_bear_target_is_floored_at_zero_rather_than_going_negative() -> None:
    """The document's own floor. A negative weight is not a short, it is a
    number nobody can act on."""
    result = decide(_signal(rv=200.0), growth=_growth(-2.0), scaling_unit=_SB, baseline=0.85)

    assert isinstance(result, RegimeDecision)
    assert result.target_weight == 0.0


def test_shock_is_a_flat_reduction_regardless_of_the_scaling_unit() -> None:
    result = decide(
        _signal(rv=12.0, vix_shock=True), growth=_growth(2.0), scaling_unit=_SB, baseline=0.85
    )

    assert isinstance(result, RegimeDecision)
    assert result.regime == "shock"
    assert result.change == pytest.approx(-0.10)
    assert result.target_weight == pytest.approx(0.75)


def test_a_volatility_spike_alone_triggers_shock_without_the_vix() -> None:
    """The document's trigger is disjunctive: RV >> HV OR VIX > 25."""
    result = decide(
        _signal(rv=30.0, vix_shock=None), growth=_growth(2.0), scaling_unit=_SB, baseline=0.85
    )

    assert isinstance(result, RegimeDecision)
    assert result.regime == "shock"


def test_low_volatility_drift_lifts_by_half() -> None:
    result = decide(_signal(rv=8.74), growth=_growth(1.0), scaling_unit=_SB, baseline=0.85)

    assert isinstance(result, RegimeDecision)
    assert result.regime == "low_vol_drift"
    expected = ((15.0 - 8.74) / 15.0) * _SB * 0.5
    assert result.change == pytest.approx(expected)


def test_recession_halves_the_baseline_and_ignores_the_scaling_unit() -> None:
    """⚠️ Distressed spreads are the ONLY thing separating this from BEAR, which
    is why Phase 1 had to classify BAA10Y before this row could exist."""
    result = decide(
        _signal(rv=20.0, spreads="distressed"),
        growth=_growth(-1.0),
        scaling_unit=_SB,
        baseline=0.85,
    )

    assert isinstance(result, RegimeDecision)
    assert result.regime == "recession"
    assert result.target_weight == pytest.approx(0.425)


def test_recovery_adds_its_kicker_on_top_of_the_scaled_lift() -> None:
    result = decide(
        _signal(rv=8.74, vol_direction="falling"),
        growth=_growth(2.0, direction="accelerating"),
        scaling_unit=_SB,
        baseline=0.85,
    )

    assert isinstance(result, RegimeDecision)
    assert result.regime == "recovery"
    expected = ((15.0 - 8.74) / 15.0) * _SB + 0.05
    assert result.change == pytest.approx(expected)


def test_sideways_holds_the_baseline_exactly() -> None:
    """Flat growth, volatility at the baseline. No change at all - the point is
    avoiding churn, so a near-zero drift would defeat it."""
    result = decide(_signal(rv=15.0), growth=_growth(2.0), scaling_unit=_SB, baseline=0.85)

    assert isinstance(result, RegimeDecision)
    assert result.regime == "sideways"
    assert result.change == 0.0
    assert result.target_weight == 0.85


# --- precedence and reporting --------------------------------------------


def test_recession_outranks_bear_when_both_are_true() -> None:
    """⚠️ A recession IS a bear market. Reporting the milder of two true
    readings would understate exactly when it matters most."""
    result = decide(
        _signal(rv=45.0, spreads="distressed"),
        growth=_growth(-1.0),
        scaling_unit=_SB,
        baseline=0.85,
    )

    assert isinstance(result, RegimeDecision)
    assert result.regime == "recession"


def test_the_mandate_changes_the_size_of_the_move() -> None:
    """⚠️ SB is RESPONSIVENESS. The same market on an aggressive mandate must
    move further than on a conservative one - that is what the setting is."""
    market = dict(growth=_growth(4.0), baseline=0.85)
    timid = decide(_signal(rv=8.74), scaling_unit=0.10, **market)
    bold = decide(_signal(rv=8.74), scaling_unit=0.35, **market)

    assert isinstance(timid, RegimeDecision) and isinstance(bold, RegimeDecision)
    assert timid.regime == bold.regime
    assert bold.change > timid.change * 3


def test_a_target_above_full_exposure_is_surfaced_not_clamped() -> None:
    """⚠️ A lift can carry the target past 100%. For a mandate permitting
    leverage that is the intended answer, and the operator should SEE it rather
    than have it quietly trimmed."""
    result = decide(_signal(rv=1.0), growth=_growth(5.0), scaling_unit=0.35, baseline=1.0)

    assert isinstance(result, RegimeDecision)
    assert result.target_weight > 1.0
    assert result.implies_leverage is True


def test_the_decision_carries_why() -> None:
    """The narrative in Phase 4 must cite figures rather than invent them."""
    result = decide(_signal(rv=8.74), growth=_growth(4.0), scaling_unit=_SB, baseline=0.85)

    assert isinstance(result, RegimeDecision)
    joined = " ".join(result.reasons)
    assert "8.7" in joined and "15.0" in joined and "+4.0" in joined

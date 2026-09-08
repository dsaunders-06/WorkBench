"""Phase 4: the matrix's reading, written up - with the model kept off the maths.

`docs/superpowers/specs/2026-09-08-macro-regime-matrix-design.md`.

The source document reads as ONE prompt asking a model to classify the regime
AND compute `Lift = ((HV - RV) / HV) * SB`. ⚠️ That division of labour is what
this phase refuses. The regime, the change and the target are decided by
`macro_analysis.matrix.decide` - deterministic, tested, same inputs same answer -
and the model is handed them as facts. An LLM performing arithmetic that sets an
exposure target is the failure mode `ai_advisory/guards.py` exists for.
"""

from __future__ import annotations

from datetime import UTC, datetime

from qat.domain.ai_advisory.prompts import build_macro_matrix_prompt
from qat.domain.macro_analysis.growth import GrowthRead
from qat.domain.macro_analysis.matrix import RegimeHysteresis, decide
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


def _bucket(yoy: float) -> str:
    """Mirrors `classify_growth`'s own bucketing, so a fixture's yoy value still
    implies the regime the test is reasoning about."""
    if yoy < 0.0:
        return "negative"
    if yoy < 1.5:
        return "low"
    if yoy < 3.0:
        return "normal"
    return "high"


def _growth(yoy: float = 4.0, age_days: int = 70) -> GrowthRead:
    return GrowthRead(
        series="GDPC1",
        bucket=_bucket(yoy),  # type: ignore[arg-type]
        summary=f"{yoy:+.1f}% y/y",
        yoy_pct=yoy,
        direction="flattening",
        as_of=datetime(2026, 6, 30, tzinfo=UTC),
        age_days=age_days,
    )


def _decision(**kwargs):
    return decide(
        _signal(**kwargs.pop("signal", {})),
        _growth(**kwargs.pop("growth", {})),
        scaling_unit=_SB,
        baseline=0.85,
    )


def test_the_prompt_forbids_recalculation_in_terms() -> None:
    """⚠️ THE TEST THIS FILE EXISTS FOR. The whole point of Phase 3 was that the
    arithmetic is deterministic; a prompt that let the model redo it would give
    that away silently."""
    prompt = build_macro_matrix_prompt(_decision())

    assert "NOT YOURS TO REDO" in prompt
    assert "EXACTLY as given" in prompt


def test_the_prompt_carries_the_computed_figures() -> None:
    """The model must copy, so it has to be given something to copy."""
    decision = _decision()
    prompt = build_macro_matrix_prompt(decision)

    assert "Bull Market" in prompt
    assert f"{decision.target_weight:.1%}" in prompt
    assert f"{decision.change:+.2%}" in prompt


def test_the_prompt_asks_for_the_if_then_justification_structure() -> None:
    prompt = build_macro_matrix_prompt(_decision())

    assert "the IF:" in prompt and "the THEN:" in prompt and "the JUSTIFICATION:" in prompt


def test_a_refusal_is_rendered_as_a_refusal_and_not_a_regime() -> None:
    """⚠️ "We cannot tell" is not "sideways". A model handed a refusal must
    report it, not reach for the nearest plausible market state."""
    refusal = decide(_signal(), None, scaling_unit=_SB, baseline=0.85)

    prompt = build_macro_matrix_prompt(refusal)

    assert "COULD NOT identify a regime" in prompt
    assert "Do NOT guess" in prompt
    assert "calm or sideways" in prompt
    assert "QAT_MACRO_GROWTH_SERIES" in prompt


def test_a_refusal_prompt_asks_for_no_exposure_change() -> None:
    refusal = decide(_signal(), None, scaling_unit=_SB, baseline=0.85)

    prompt = build_macro_matrix_prompt(refusal)

    assert "do NOT" in prompt and "exposure change" in prompt


def test_leverage_is_called_out_when_the_target_exceeds_full_exposure() -> None:
    """Surfaced rather than trimmed - so the prose has to mention it."""
    decision = decide(_signal(rv=1.0), _growth(yoy=5.0), scaling_unit=0.35, baseline=1.0)

    prompt = build_macro_matrix_prompt(decision)

    assert "LEVERAGE" in prompt


def test_a_held_regime_is_declared_provisional() -> None:
    """⚠️ Hysteresis smooths the NAME. A reading being held back is something
    the reader needs told, or the screen implies more certainty than exists."""
    gate = RegimeHysteresis(min_persistence=3)
    gate.settle(decide(_signal(rv=8.74), _growth(4.0), scaling_unit=_SB, baseline=0.85))
    held = gate.settle(decide(_signal(rv=45.0), _growth(-1.0), scaling_unit=_SB, baseline=0.85))

    prompt = build_macro_matrix_prompt(held)

    assert "HELD" in prompt and "provisional" in prompt


def test_holdings_are_weighed_only_when_something_is_held() -> None:
    """⚠️ A standing instruction to weigh holdings, handed a flat account,
    invites discussion of a position that does not exist - the shape of every
    absent-rendered-as-present defect in this codebase."""
    flat = build_macro_matrix_prompt(_decision(), positions={})
    invested = build_macro_matrix_prompt(_decision(), positions={"BHP.AX": 100.0})

    assert "ALREADY HOLDS" not in flat
    assert "ALREADY HOLDS" in invested


def test_the_prompt_refuses_boilerplate_disclaimers() -> None:
    """⚠️ `workbench.py`: "a disclaimer printed on every result stops being
    read". The screen carries the standing one; caveats here are specific."""
    prompt = build_macro_matrix_prompt(_decision())

    assert "Do NOT add a generic disclaimer" in prompt


def test_the_prompt_never_instructs_the_system_to_trade() -> None:
    """⚠️ Advisory only, by operator instruction. The prose describes a target;
    it must not read as an order."""
    prompt = build_macro_matrix_prompt(_decision())
    lowered = prompt.lower()

    assert "place an order" not in lowered
    assert "submit" not in lowered


def test_a_friction_alert_is_front_loaded_before_any_justification() -> None:
    """⚠️ THE ORDERING IS THE POINT. A reader meeting a tidy narrative first and
    a caveat last has already formed a view. The alert goes above everything."""
    from qat.domain.macro_analysis.friction import compare
    from qat.domain.regime import Regime

    decision = _decision()
    friction = compare(Regime.BEAR, 0.5, decision)

    prompt = build_macro_matrix_prompt(decision, friction=friction)

    assert prompt.index("FRICTION ALERT") < prompt.index("Write the macro regime read")
    assert "Do NOT write a single tidy narrative" in prompt


def test_agreement_adds_no_alert_at_all() -> None:
    """⚠️ An alert printed when the engines agree is the alarm-fatigue shape
    this project has removed twice. Silence when there is nothing to say."""
    from qat.domain.macro_analysis.friction import compare
    from qat.domain.regime import Regime

    decision = _decision()
    friction = compare(Regime.BULL, 1.0, decision)

    prompt = build_macro_matrix_prompt(decision, friction=friction)

    assert "FRICTION" not in prompt


def test_no_friction_object_behaves_as_before() -> None:
    """The comparison is optional - the HMM may not have fitted yet."""
    prompt = build_macro_matrix_prompt(_decision(), friction=None)

    assert "FRICTION" not in prompt
    assert "Write the macro regime read" in prompt


def test_the_schemas_regime_tokens_are_the_programs_own() -> None:
    """⚠️ A THIRD TAXONOMY IS THE BUG THIS PINS. The schema first listed
    "shock" and "low_vol_drift" - names the matrix itself had already abandoned
    for `domain.regime.Regime`, because `friction.py` compares the two engines
    by equality and a renamed pair reads as disagreement on a quiet market.

    `schema.py` cannot import `Regime` (it depends on nothing in the domain by
    design), so the tokens are written out there and checked here.
    """
    from typing import get_args

    from qat.domain.ai_advisory.schema import MacroMatrixNarrative
    from qat.domain.regime import ALL_REGIMES

    declared = set(get_args(MacroMatrixNarrative.model_fields["regime"].annotation))

    assert declared == {regime.value for regime in ALL_REGIMES}

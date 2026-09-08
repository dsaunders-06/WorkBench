"""The matrix's narrative call, and the check that the model copied rather
than recomputed.

Phase 4 said the echoed fields exist "so a model that quietly disagreed with the
arithmetic is CAUGHT rather than believed - the caller compares them against
what it sent". Until now there was no caller, so nothing compared. This is that
comparison.

⚠️ A MISMATCH IS CORRECTED AND SAID OUT LOUD, not raised. Blanking the panel
because a model rounded differently would lose the deterministic reading too -
and that reading is the part with authority. So the figures on screen are always
`decide`'s, and a disagreement becomes a caveat the operator can see.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from qat.config import Settings
from qat.domain.ai_advisory.router import LLMRouter
from qat.domain.ai_advisory.schema import MacroMatrixNarrative
from qat.domain.ai_advisory.service import AIAdvisoryService
from qat.domain.bus import EventBus
from qat.domain.macro_analysis.growth import GrowthRead
from qat.domain.macro_analysis.matrix import decide
from qat.domain.macro_analysis.signal import MacroSignal
from qat.domain.risk_engine.engine import RiskEngine
from qat.domain.risk_engine.kill_switch import KillSwitch


class _RecordingEngine:
    def __init__(self, response: MacroMatrixNarrative, name: str = "recording") -> None:
        self.response = response
        self.name = name
        self.prompts: list[str] = []

    async def complete(self, system_prompt, user_prompt, schema, max_retries=1):
        self.prompts.append(user_prompt)
        return self.response


def _signal() -> MacroSignal:
    return MacroSignal(
        realized_vol_annualized_pct=8.74,
        vol_direction="steady",
        vix_shock=False,
        term_structure="normal",
        spreads="normal",
        baseline_vol_annualized_pct=15.0,
        pct_above_trend=1.0,
        drawdown_from_recent_high_pct=1.0,
        suggested_regime="neutral",
        elevated_volatility=False,
        below_trend=False,
    )


def _growth() -> GrowthRead:
    return GrowthRead(
        series="CFNAIMA3",
        bucket="high",
        summary="CFNAIMA3 +0.31 (above trend)",
        yoy_pct=None,
        direction="accelerating",
        as_of=datetime(2026, 8, 31, tzinfo=UTC),
        age_days=8,
    )


def _decision():
    return decide(_signal(), _growth(), scaling_unit=0.20, baseline=0.8333)


def _narrative(**overrides) -> MacroMatrixNarrative:
    decision = _decision()
    payload = {
        "regime": decision.regime.value,
        "condition": "Realised volatility is well below its baseline.",
        "action": "Lift exposure toward the stated target.",
        "justification": "A calm, growing tape rewards being invested.",
        "change_pct": decision.change * 100.0,
        "target_pct": decision.target_weight * 100.0,
        "caveats": [],
    }
    payload.update(overrides)
    return MacroMatrixNarrative.model_validate(payload)


def _service(engine, settings: Settings | None = None) -> AIAdvisoryService:
    settings = settings or Settings(_env_file=None)
    bus = EventBus()
    risk_engine = RiskEngine(bus, KillSwitch(), settings=settings)
    router = LLMRouter(engine, engine, settings=settings)
    return AIAdvisoryService(router, risk_engine, settings=settings)


@pytest.mark.asyncio
async def test_the_narrative_comes_back_and_the_prompt_carried_the_figures() -> None:
    engine = _RecordingEngine(_narrative())
    decision = _decision()

    result = await _service(engine).get_macro_matrix_narrative(decision)

    assert isinstance(result, MacroMatrixNarrative)
    prompt = engine.prompts[0]
    assert 'Return regime="bull" exactly.' in prompt
    assert "PERCENTAGES and not fractions" in prompt


@pytest.mark.asyncio
async def test_a_model_that_agrees_is_left_alone() -> None:
    """⚠️ The correction must not fire on agreement. A caveat that appears every
    time is the disclaimer nobody reads."""
    engine = _RecordingEngine(_narrative())

    result = await _service(engine).get_macro_matrix_narrative(_decision())

    assert result.caveats == []


@pytest.mark.asyncio
async def test_a_model_that_moves_the_target_is_corrected_and_says_so() -> None:
    """⚠️ THE TEST THIS FILE EXISTS FOR. The screen shows a percentage next to
    an exposure instruction; a model that decided 95% was tidier than 86.7%
    would have put a number nothing computed in front of the operator."""
    decision = _decision()
    engine = _RecordingEngine(_narrative(target_pct=95.0))

    result = await _service(engine).get_macro_matrix_narrative(decision)

    assert result.target_pct == pytest.approx(decision.target_weight * 100.0)
    assert any("95.0" in caveat and "did not match" in caveat for caveat in result.caveats)


@pytest.mark.asyncio
async def test_a_model_that_moves_the_change_is_corrected() -> None:
    decision = _decision()
    engine = _RecordingEngine(_narrative(change_pct=-4.0))

    result = await _service(engine).get_macro_matrix_narrative(decision)

    assert result.change_pct == pytest.approx(decision.change * 100.0)
    assert result.caveats


@pytest.mark.asyncio
async def test_rounding_to_one_decimal_is_not_treated_as_disagreement() -> None:
    """A model told 12.50 that returns 12.5 has copied it."""
    decision = _decision()
    engine = _RecordingEngine(_narrative(target_pct=round(decision.target_weight * 100.0, 1)))

    result = await _service(engine).get_macro_matrix_narrative(decision)

    assert result.caveats == []


@pytest.mark.asyncio
async def test_a_model_that_renames_the_regime_is_corrected() -> None:
    """The regime drives what the screen labels the whole panel."""
    engine = _RecordingEngine(_narrative(regime="recession"))

    result = await _service(engine).get_macro_matrix_narrative(_decision())

    assert result.regime == "bull"
    assert any("recession" in caveat for caveat in result.caveats)


@pytest.mark.asyncio
async def test_a_refusal_never_carries_a_number_the_model_invented() -> None:
    """⚠️ On a refusal there IS no target, so any figure came from the model.
    Rendering one beside "we could not tell" is the fabricated-all-clear shape."""
    refusal = decide(_signal(), None, scaling_unit=0.20, baseline=0.8333)
    engine = _RecordingEngine(_narrative(change_pct=-10.0, target_pct=40.0))

    result = await _service(engine).get_macro_matrix_narrative(refusal)

    assert result.change_pct == 0.0
    assert result.target_pct == 0.0
    assert result.caveats


@pytest.mark.asyncio
async def test_a_held_book_keeps_the_call_on_the_local_engine() -> None:
    """⚠️ The router's existing rule, not a new one: a context carrying
    positions never reaches the cloud slot. The matrix prompt mentions only the
    COUNT, but the sensitivity check keys on the context - so the positions go
    into the context rather than being smuggled past it as a bare number."""
    cloud = _RecordingEngine(_narrative(), name="cloud")
    local = _RecordingEngine(_narrative(), name="local")
    settings = Settings(_env_file=None)
    bus = EventBus()
    service = AIAdvisoryService(
        LLMRouter(cloud, local, settings=settings),
        RiskEngine(bus, KillSwitch(), settings=settings),
        settings=settings,
    )

    await service.get_macro_matrix_narrative(_decision(), positions={"BHP.AX": 1200.0})

    assert local.prompts, "a held book went to the cloud slot"
    assert not cloud.prompts

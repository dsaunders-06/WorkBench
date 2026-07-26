"""The macro AI path (spec M13).

The property that matters most here is the division of labour: the numbers
reach the model as established facts, and nothing the model returns is
applied to anything. Both are asserted rather than assumed.
"""

from __future__ import annotations

import pandas as pd
import pytest

from qat.config import Settings
from qat.domain.ai_advisory.llm_engine import DemoLLMEngine
from qat.domain.ai_advisory.router import LLMRouter
from qat.domain.ai_advisory.schema import AdvisoryRecommendation, MacroAssessment
from qat.domain.ai_advisory.service import AIAdvisoryService
from qat.domain.bus import EventBus
from qat.domain.macro_analysis import compute_macro_signal
from qat.domain.risk_engine.engine import RiskEngine
from qat.domain.risk_engine.kill_switch import KillSwitch


class _RecordingEngine:
    """Captures the prompt so the tests can assert what the model was told."""

    def __init__(self, response: MacroAssessment, name: str = "recording") -> None:
        self.response = response
        self.name = name
        self.prompts: list[str] = []

    async def complete(self, system_prompt, user_prompt, schema, max_retries=1):
        self.prompts.append(user_prompt)
        return self.response


def _signal(macro_series: dict[str, float] | None = None):
    closes = [100.0 * (1.002**i) for i in range(120)]
    signal = compute_macro_signal(pd.DataFrame({"close": closes}), macro_series=macro_series)
    assert signal is not None
    return signal


def _assessment(**overrides) -> MacroAssessment:
    payload = {
        "regime": "caution",
        "reasoning": "Vol is picking up into a crowded tape.",
        "confidence": 0.7,
        "key_insights": ["Breadth narrowing"],
        "risk_flags": ["concentration"],
        "suggested_exposure_scalar": 0.6,
    }
    payload.update(overrides)
    return MacroAssessment.model_validate(payload)


def _service(engine, settings: Settings | None = None) -> AIAdvisoryService:
    settings = settings or Settings(_env_file=None)
    bus = EventBus()
    risk_engine = RiskEngine(bus, KillSwitch(), settings=settings)
    router = LLMRouter(engine, engine, settings=settings)
    return AIAdvisoryService(router, risk_engine, settings=settings)


@pytest.mark.asyncio
async def test_returns_a_macro_assessment():
    engine = _RecordingEngine(_assessment())
    result = await _service(engine).get_macro_assessment(_signal())
    assert isinstance(result, MacroAssessment)
    assert result.regime == "caution"


@pytest.mark.asyncio
async def test_the_deterministic_numbers_are_in_the_prompt():
    engine = _RecordingEngine(_assessment())
    signal = _signal()
    await _service(engine).get_macro_assessment(signal)

    prompt = engine.prompts[0]
    assert "Deterministic macro read" in prompt
    assert signal.suggested_regime in prompt
    assert "do not recompute" in prompt


@pytest.mark.asyncio
async def test_macro_series_reaches_the_prompt():
    engine = _RecordingEngine(_assessment())
    await _service(engine).get_macro_assessment(_signal(macro_series={"VIXCLS": 18.4}))
    assert "VIXCLS" in engine.prompts[0]


@pytest.mark.asyncio
async def test_the_prompt_states_that_the_exposure_figure_is_only_a_proposal():
    """The model must not be left thinking it is issuing an instruction."""
    engine = _RecordingEngine(_assessment())
    await _service(engine).get_macro_assessment(_signal())
    assert "PROPOSAL" in engine.prompts[0]
    assert "not applied automatically" in engine.prompts[0]


@pytest.mark.asyncio
async def test_no_positions_are_sent_so_the_request_can_use_the_general_slot():
    """Macro is a market-wide question. If positions leaked into this context
    the router's sensitivity override would force it local, and the operator's
    general-slot provider choice would be silently ignored."""
    general = _RecordingEngine(_assessment(), name="general")
    sensitive = _RecordingEngine(_assessment(), name="sensitive")
    settings = Settings(_env_file=None)
    bus = EventBus()
    risk_engine = RiskEngine(bus, KillSwitch(), settings=settings)
    router = LLMRouter(general, sensitive, settings=settings)
    service = AIAdvisoryService(router, risk_engine, settings=settings)

    await service.get_macro_assessment(_signal())

    assert general.prompts, "macro analysis should route to the general slot"
    assert not sensitive.prompts
    assert "Current positions: {}" in general.prompts[0]


@pytest.mark.asyncio
async def test_a_model_reading_that_differs_from_the_deterministic_one_is_preserved():
    """Disagreement is informative and must survive the round trip rather than
    being reconciled to the computed value."""
    signal = _signal()
    assert signal.suggested_regime == "risk_on"
    engine = _RecordingEngine(_assessment(regime="risk_off"))

    result = await _service(engine).get_macro_assessment(signal)

    assert result.regime == "risk_off"
    assert signal.suggested_regime == "risk_on"


@pytest.mark.asyncio
async def test_the_risk_engine_exposure_scalar_is_untouched_by_a_macro_assessment():
    """Nothing applies the proposal - the whole point of calling it a proposal."""
    settings = Settings(_env_file=None)
    bus = EventBus()
    risk_engine = RiskEngine(bus, KillSwitch(), settings=settings)
    router = LLMRouter(
        _RecordingEngine(_assessment()), _RecordingEngine(_assessment()), settings=settings
    )
    service = AIAdvisoryService(router, risk_engine, settings=settings)
    before = risk_engine.regime_scalar

    await service.get_macro_assessment(_signal())

    assert risk_engine.regime_scalar == before


@pytest.mark.asyncio
async def test_demo_engine_answers_a_macro_request_inertly():
    """Demo is the shipped default, so this path must work out of the box - and
    must propose nothing when it does."""
    result = await _service(DemoLLMEngine()).get_macro_assessment(_signal())
    assert result.regime == "neutral"
    assert result.confidence == 0.0
    assert result.suggested_exposure_scalar is None
    assert "demo_mode_no_real_llm" in result.risk_flags


@pytest.mark.asyncio
async def test_demo_engine_still_answers_an_advisory_request():
    result = await DemoLLMEngine().complete("sys", "user", AdvisoryRecommendation)
    assert result.recommendation == "hold"
    assert result.confidence == 0.0


@pytest.mark.asyncio
async def test_demo_engine_raises_on_an_unregistered_schema():
    """Loud beats a wrong-shaped canned answer for a schema nobody registered."""
    from pydantic import BaseModel

    class Unregistered(BaseModel):
        value: int

    with pytest.raises(ValueError, match="no canned payload"):
        await DemoLLMEngine().complete("sys", "user", Unregistered)

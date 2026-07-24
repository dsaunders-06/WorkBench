"""AnthropicEngine tests use real anthropic.types data classes (no network) -
tests against the actual library's shapes, not a guess at them. LocalEngine
tests use a fake requests.Session - Ollama's REST shape is simple enough
that faking the HTTP layer directly is clearer than modelling it further."""

from __future__ import annotations

from typing import Any

import pytest
from anthropic.types import Message, TextBlock, ToolUseBlock, Usage

from qat.domain.ai_advisory.llm_engine import AnthropicEngine, LLMResponseError, LocalEngine
from qat.domain.ai_advisory.schema import AdvisoryRecommendation


def _usage() -> Usage:
    return Usage(input_tokens=10, output_tokens=20)


def _tool_use_message(input_data: dict[str, Any]) -> Message:
    block = ToolUseBlock(
        id="toolu_1", input=input_data, name="submit_recommendation", type="tool_use"
    )
    return Message(
        id="msg_1",
        content=[block],
        model="claude-sonnet-5",
        role="assistant",
        stop_reason="tool_use",
        stop_sequence=None,
        type="message",
        usage=_usage(),
    )


def _text_only_message(text: str) -> Message:
    block = TextBlock(text=text, type="text")
    return Message(
        id="msg_1",
        content=[block],
        model="claude-sonnet-5",
        role="assistant",
        stop_reason="end_turn",
        stop_sequence=None,
        type="message",
        usage=_usage(),
    )


class FakeMessages:
    def __init__(self, responses: list[Message]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Message:
        self.calls.append(kwargs)
        return self._responses.pop(0)


class FakeAnthropicClient:
    def __init__(self, responses: list[Message]) -> None:
        self.messages = FakeMessages(responses)


@pytest.mark.asyncio
async def test_anthropic_engine_parses_valid_tool_use_response():
    good_input = {
        "recommendation": "buy",
        "rationale": "strong signal",
        "confidence": 0.8,
        "risk_flags": [],
    }
    client = FakeAnthropicClient([_tool_use_message(good_input)])
    engine = AnthropicEngine(client=client, model="claude-sonnet-5")

    result = await engine.complete("system", "user prompt", AdvisoryRecommendation)

    assert result.recommendation == "buy"
    assert result.confidence == 0.8
    assert len(client.messages.calls) == 1
    assert client.messages.calls[0]["tool_choice"] == {
        "type": "tool",
        "name": "submit_recommendation",
    }


@pytest.mark.asyncio
async def test_anthropic_engine_retries_on_invalid_schema_then_succeeds():
    bad_input = {"recommendation": "buy", "rationale": "x", "confidence": 5.0}
    good_input = {"recommendation": "buy", "rationale": "x", "confidence": 0.5, "risk_flags": []}
    client = FakeAnthropicClient([_tool_use_message(bad_input), _tool_use_message(good_input)])
    engine = AnthropicEngine(client=client, model="claude-sonnet-5")

    result = await engine.complete("system", "user prompt", AdvisoryRecommendation, max_retries=1)

    assert result.confidence == 0.5
    assert len(client.messages.calls) == 2


@pytest.mark.asyncio
async def test_anthropic_engine_raises_after_exhausting_retries():
    bad_input = {"recommendation": "buy", "rationale": "x", "confidence": 5.0}
    client = FakeAnthropicClient([_tool_use_message(bad_input), _tool_use_message(bad_input)])
    engine = AnthropicEngine(client=client, model="claude-sonnet-5")

    with pytest.raises(LLMResponseError):
        await engine.complete("system", "user prompt", AdvisoryRecommendation, max_retries=1)


@pytest.mark.asyncio
async def test_anthropic_engine_handles_missing_tool_use_block():
    fallback_input = {
        "recommendation": "hold",
        "rationale": "x",
        "confidence": 0.5,
        "risk_flags": [],
    }
    client = FakeAnthropicClient(
        [_text_only_message("I don't want to use a tool"), _tool_use_message(fallback_input)]
    )
    engine = AnthropicEngine(client=client, model="claude-sonnet-5")

    result = await engine.complete("system", "user prompt", AdvisoryRecommendation, max_retries=1)

    assert result.recommendation == "hold"


class FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._payload


class FakeSession:
    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def post(self, url: str, json: Any = None, timeout: Any = None) -> FakeResponse:
        self.calls.append({"url": url, "json": json})
        return FakeResponse(self._responses.pop(0))


def _chat_completion_payload(content: str) -> dict[str, Any]:
    return {"choices": [{"message": {"content": content}}]}


@pytest.mark.asyncio
async def test_local_engine_parses_valid_json_response():
    good_json = (
        '{"recommendation": "sell", "rationale": "overbought", "confidence": 0.6, '
        '"risk_flags": ["momentum_fading"]}'
    )
    session = FakeSession([_chat_completion_payload(good_json)])
    engine = LocalEngine(session=session, base_url="http://localhost:11434/v1")

    result = await engine.complete("system", "user prompt", AdvisoryRecommendation)

    assert result.recommendation == "sell"
    assert result.risk_flags == ["momentum_fading"]
    assert session.calls[0]["url"] == "http://localhost:11434/v1/chat/completions"


@pytest.mark.asyncio
async def test_local_engine_retries_on_malformed_json_then_succeeds():
    bad_json = "not valid json{{{"
    good_json = '{"recommendation": "hold", "rationale": "x", "confidence": 0.5, "risk_flags": []}'
    session = FakeSession([_chat_completion_payload(bad_json), _chat_completion_payload(good_json)])
    engine = LocalEngine(session=session)

    result = await engine.complete("system", "user prompt", AdvisoryRecommendation, max_retries=1)

    assert result.recommendation == "hold"
    assert len(session.calls) == 2


@pytest.mark.asyncio
async def test_local_engine_raises_after_exhausting_retries():
    bad_json = "not valid json{{{"
    session = FakeSession([_chat_completion_payload(bad_json), _chat_completion_payload(bad_json)])
    engine = LocalEngine(session=session)

    with pytest.raises(LLMResponseError):
        await engine.complete("system", "user prompt", AdvisoryRecommendation, max_retries=1)

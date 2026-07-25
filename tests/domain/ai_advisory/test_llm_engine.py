"""AnthropicEngine tests use real anthropic.types data classes (no network) -
tests against the actual library's shapes, not a guess at them. LocalEngine
tests use a fake requests.Session - Ollama's REST shape is simple enough
that faking the HTTP layer directly is clearer than modelling it further."""

from __future__ import annotations

from typing import Any

import pytest
import requests
from anthropic.types import Message, TextBlock, ToolUseBlock, Usage

from qat.domain.ai_advisory.llm_engine import (
    AnthropicEngine,
    LLMResponseError,
    LocalEngine,
    normalize_openai_base_url,
)
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


# --- regressions for the LM Studio failures found in the field ------------


@pytest.mark.parametrize(
    ("configured", "expected"),
    [
        ("http://localhost:8000", "http://localhost:8000/v1"),
        ("http://localhost:8000/", "http://localhost:8000/v1"),
        ("http://localhost:1234/v1", "http://localhost:1234/v1"),
        ("http://localhost:11434/v1/", "http://localhost:11434/v1"),
    ],
)
def test_base_url_is_normalized_to_include_v1(configured, expected):
    assert normalize_openai_base_url(configured) == expected
    assert LocalEngine(session=FakeSession([]), base_url=configured).base_url == expected


@pytest.mark.asyncio
async def test_error_body_returned_with_http_200_raises_a_diagnosable_error():
    """LM Studio answers a POST to the wrong path with HTTP *200* carrying an
    {"error": ...} body. That used to sail past raise_for_status() and blow up
    as a bare KeyError('choices') which the UI swallowed silently."""
    session = FakeSession([{"error": "Unexpected endpoint or method. (POST /chat/completions)"}])
    engine = LocalEngine(session=session)

    with pytest.raises(LLMResponseError) as excinfo:
        await engine.complete("system", "user prompt", AdvisoryRecommendation)

    assert "Unexpected endpoint" in str(excinfo.value)


@pytest.mark.asyncio
async def test_json_wrapped_in_markdown_code_fences_is_parsed():
    fenced = '```json\n{"recommendation": "buy", "rationale": "x", "confidence": 0.4}\n```'
    session = FakeSession([_chat_completion_payload(fenced)])
    engine = LocalEngine(session=session)

    result = await engine.complete("system", "user prompt", AdvisoryRecommendation)

    assert result.recommendation == "buy"


class _StatusAwareSession:
    """Fails the first N posts with an HTTP 400 (what LM Studio returns for an
    unsupported response_format), then succeeds - so the engine's step-down
    negotiation is exercised for real."""

    def __init__(self, failures: int, payload: dict[str, Any]) -> None:
        self._failures = failures
        self._payload = payload
        self.attempts: list[dict[str, Any]] = []

    def post(self, url: str, json: Any = None, timeout: Any = None) -> FakeResponse:
        self.attempts.append(json)
        if len(self.attempts) <= self._failures:
            response = requests.Response()
            response.status_code = 400
            raise requests.HTTPError("400 Bad Request", response=response)
        return FakeResponse(self._payload)


@pytest.mark.asyncio
async def test_steps_down_from_json_schema_when_the_server_rejects_it():
    good = '{"recommendation": "hold", "rationale": "x", "confidence": 0.5, "risk_flags": []}'
    session = _StatusAwareSession(failures=1, payload=_chat_completion_payload(good))
    engine = LocalEngine(session=session)

    result = await engine.complete("system", "user prompt", AdvisoryRecommendation)

    assert result.recommendation == "hold"
    assert session.attempts[0]["response_format"]["type"] == "json_schema"
    assert session.attempts[1]["response_format"]["type"] == "json_object"


@pytest.mark.asyncio
async def test_negotiated_mode_is_remembered_across_calls():
    good = '{"recommendation": "hold", "rationale": "x", "confidence": 0.5, "risk_flags": []}'
    session = _StatusAwareSession(failures=1, payload=_chat_completion_payload(good))
    engine = LocalEngine(session=session)

    await engine.complete("system", "first", AdvisoryRecommendation)
    await engine.complete("system", "second", AdvisoryRecommendation)

    # Only the very first call pays for the rejected json_schema attempt.
    assert [a["response_format"]["type"] for a in session.attempts] == [
        "json_schema",
        "json_object",
        "json_object",
    ]

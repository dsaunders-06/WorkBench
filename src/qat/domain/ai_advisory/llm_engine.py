"""LLMEngine implementations (spec §J/§16): AnthropicEngine (official SDK,
forced tool-use for schema-conforming JSON) and LocalEngine (Ollama's
OpenAI-compatible REST endpoint, response_format=json_object).

Both wrap a synchronous client call in asyncio.to_thread (matching
FredMacroSource's existing pattern, M2) and retry once on a malformed/
schema-invalid response before giving up (spec: "malformed JSON is
rejected and retried"). The client is injectable behind a narrow Protocol
so tests use a fake instead of needing a real API key or local Ollama
server - the same pattern M7 used for ib_async.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Protocol, TypeVar, cast

import requests
from pydantic import BaseModel, ValidationError

from qat.config import Settings
from qat.security import get_secret

_TOOL_NAME = "submit_recommendation"

SchemaT = TypeVar("SchemaT", bound=BaseModel)


class LLMEngine(Protocol):
    async def complete(
        self, system_prompt: str, user_prompt: str, schema: type[SchemaT], max_retries: int = 1
    ) -> SchemaT: ...


class LLMResponseError(Exception):
    """Raised when an engine can't get a schema-valid response within its retry budget."""


class _AnthropicMessagesProtocol(Protocol):
    def create(self, **kwargs: Any) -> Any: ...


class AnthropicClientProtocol(Protocol):
    @property
    def messages(self) -> _AnthropicMessagesProtocol: ...


class AnthropicEngine:
    def __init__(
        self,
        client: AnthropicClientProtocol | None = None,
        model: str | None = None,
        settings: Settings | None = None,
    ) -> None:
        settings = settings or Settings()
        self.model = model or settings.anthropic_model
        self._client = client or self._build_default_client()

    @staticmethod
    def _build_default_client() -> AnthropicClientProtocol:
        import anthropic

        api_key = get_secret("ANTHROPIC_API_KEY")
        # anthropic.Anthropic's real .messages.create signature is fully typed
        # with specific named parameters, which mypy won't structurally match
        # against this Protocol's intentionally loose **kwargs method - the
        # runtime call (specific keywords we control below) is correct either way.
        return cast(AnthropicClientProtocol, anthropic.Anthropic(api_key=api_key))

    async def complete(
        self, system_prompt: str, user_prompt: str, schema: type[SchemaT], max_retries: int = 1
    ) -> SchemaT:
        tool = {
            "name": _TOOL_NAME,
            "description": f"Submit a structured {schema.__name__}",
            "input_schema": schema.model_json_schema(),
        }
        messages: list[dict[str, str]] = [{"role": "user", "content": user_prompt}]
        last_error: Exception | None = None

        for _ in range(max_retries + 1):
            response = await asyncio.to_thread(
                self._client.messages.create,
                model=self.model,
                max_tokens=1024,
                system=system_prompt,
                messages=messages,
                tools=[tool],
                tool_choice={"type": "tool", "name": _TOOL_NAME},
            )
            tool_use = next(
                (block for block in response.content if getattr(block, "type", None) == "tool_use"),
                None,
            )
            if tool_use is None:
                last_error = LLMResponseError("model did not return a tool_use block")
                continue
            try:
                return schema.model_validate(tool_use.input)
            except ValidationError as exc:
                last_error = exc
                messages.append(
                    {
                        "role": "user",
                        "content": f"Your previous response didn't match the required schema "
                        f"({exc}). Please try again.",
                    }
                )
                continue

        raise LLMResponseError(
            f"AnthropicEngine failed to get valid structured output after "
            f"{max_retries + 1} attempt(s): {last_error}"
        )


class LocalEngine:
    def __init__(
        self,
        session: requests.Session | None = None,
        base_url: str | None = None,
        model: str | None = None,
        settings: Settings | None = None,
    ) -> None:
        settings = settings or Settings()
        self.base_url = base_url or settings.local_llm_base_url
        self.model = model or settings.local_llm_model
        self._session = session or requests.Session()

    async def complete(
        self, system_prompt: str, user_prompt: str, schema: type[SchemaT], max_retries: int = 1
    ) -> SchemaT:
        last_error: Exception | None = None
        current_user_prompt = user_prompt

        for _ in range(max_retries + 1):
            payload = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": current_user_prompt},
                ],
                "response_format": {"type": "json_object"},
                "stream": False,
            }
            response_data = await asyncio.to_thread(self._post, payload)
            content = response_data["choices"][0]["message"]["content"]
            try:
                parsed = json.loads(content)
                return schema.model_validate(parsed)
            except (json.JSONDecodeError, ValidationError) as exc:
                last_error = exc
                current_user_prompt = (
                    f"{user_prompt}\n\nYour previous response was invalid JSON or didn't match "
                    f"the schema ({exc}). Respond again with valid JSON matching the schema."
                )
                continue

        raise LLMResponseError(
            f"LocalEngine failed to get valid structured output after "
            f"{max_retries + 1} attempt(s): {last_error}"
        )

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        response = self._session.post(f"{self.base_url}/chat/completions", json=payload, timeout=60)
        response.raise_for_status()
        result: dict[str, Any] = response.json()
        return result


class DemoLLMEngine:
    """A canned, offline fallback (spec §M9) used only when the runtime isn't
    given a real engine - no Anthropic key configured, no local Ollama
    server running - so the demo app runs out of the box without either.
    Always returns "hold" with confidence 0.0 and a risk_flag naming itself:
    the safest possible default, since it can never accidentally propose a
    real trade. AnthropicEngine/LocalEngine are the right choice for any
    real paper or live session.

    Assumes the schema is AdvisoryRecommendation-shaped (the only schema
    this codebase uses) - it is not a general-purpose LLM stand-in.
    """

    async def complete(
        self, system_prompt: str, user_prompt: str, schema: type[SchemaT], max_retries: int = 1
    ) -> SchemaT:
        await asyncio.sleep(0)  # a real (trivial) await, not a blocking call
        return schema.model_validate(
            {
                "recommendation": "hold",
                "rationale": (
                    "[Demo mode - no real LLM configured] This is a canned response. "
                    "Configure an Anthropic API key or a local Ollama server for real analysis."
                ),
                "confidence": 0.0,
                "risk_flags": ["demo_mode_no_real_llm"],
            }
        )

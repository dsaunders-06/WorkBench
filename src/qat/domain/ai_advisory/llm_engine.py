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
# Strongest structured-output guarantee first; see LocalEngine._post_negotiated.
_RESPONSE_FORMAT_MODES = ("json_schema", "json_object", "text")

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


def normalize_openai_base_url(base_url: str) -> str:
    """Strips trailing slashes and appends the "/v1" path segment when absent.

    Every OpenAI-compatible server this app targets (LM Studio, Ollama, vLLM)
    serves under /v1, but it is easy to configure just "http://localhost:8000"
    - and LM Studio answers a POST to the resulting /chat/completions with
    HTTP *200* carrying an {"error": ...} body rather than a 404, so the
    mistake would otherwise sail past raise_for_status() and only surface as
    a confusing KeyError deeper in the parser.
    """
    cleaned = base_url.rstrip("/")
    if not cleaned:
        return cleaned
    return cleaned if cleaned.rsplit("/", 1)[-1] == "v1" else f"{cleaned}/v1"


class LocalEngine:
    def __init__(
        self,
        session: requests.Session | None = None,
        base_url: str | None = None,
        model: str | None = None,
        settings: Settings | None = None,
    ) -> None:
        settings = settings or Settings()
        self.base_url = normalize_openai_base_url(base_url or settings.local_llm_base_url)
        self.model = model or settings.local_llm_model
        self._session = session or requests.Session()
        self._response_format_mode: str | None = None

    async def complete(
        self, system_prompt: str, user_prompt: str, schema: type[SchemaT], max_retries: int = 1
    ) -> SchemaT:
        last_error: Exception | None = None
        current_user_prompt = user_prompt

        for _ in range(max_retries + 1):
            response_data = await asyncio.to_thread(
                self._post_negotiated, system_prompt, current_user_prompt, schema
            )
            content = _extract_choice_content(response_data, self.base_url)
            try:
                parsed = json.loads(_strip_code_fences(content))
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

    def _post_negotiated(
        self, system_prompt: str, user_prompt: str, schema: type[SchemaT]
    ) -> dict[str, Any]:
        """Posts a completion, negotiating the structured-output mode.

        Servers disagree on this: current LM Studio accepts only
        "json_schema" or "text" and rejects "json_object" with HTTP 400,
        while Ollama supports "json_object". Rather than force one, try the
        strongest option first and step down on a 400, remembering whatever
        worked so the negotiation costs at most one wasted call per process.
        """
        last_http_error: requests.HTTPError | None = None
        for mode in self._modes_to_try():
            payload: dict[str, Any] = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "stream": False,
            }
            response_format = _response_format_for(mode, schema)
            if response_format is not None:
                payload["response_format"] = response_format

            try:
                response_data = self._post(payload)
            except requests.HTTPError as exc:
                status = exc.response.status_code if exc.response is not None else None
                if status == 400:  # likely an unsupported response_format - step down
                    last_http_error = exc
                    continue
                raise
            self._response_format_mode = mode
            return response_data

        raise LLMResponseError(
            f"Local LLM at {self.base_url} rejected every structured-output mode "
            f"({', '.join(_RESPONSE_FORMAT_MODES)}). Last error: {last_http_error}"
        )

    def _modes_to_try(self) -> tuple[str, ...]:
        if self._response_format_mode is None:
            return _RESPONSE_FORMAT_MODES
        remaining = tuple(m for m in _RESPONSE_FORMAT_MODES if m != self._response_format_mode)
        return (self._response_format_mode, *remaining)

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        response = self._session.post(f"{self.base_url}/chat/completions", json=payload, timeout=60)
        response.raise_for_status()
        result: dict[str, Any] = response.json()
        return result


def _response_format_for(mode: str, schema: type[BaseModel]) -> dict[str, Any] | None:
    if mode == "json_schema":
        return {
            "type": "json_schema",
            "json_schema": {"name": schema.__name__, "schema": schema.model_json_schema()},
        }
    if mode == "json_object":
        return {"type": "json_object"}
    return None  # "text" - rely on the prompt plus this engine's own parse/retry


def _strip_code_fences(content: str) -> str:
    """Unwraps ```json ... ``` fencing.

    Without constrained decoding a chat model very often returns its JSON
    inside a markdown code fence, which json.loads then rejects - so strip it
    rather than burning a retry on a response that was substantively correct.
    """
    text = content.strip()
    if not text.startswith("```"):
        return text
    without_open = text[3:]
    if without_open[:4].lower().startswith("json"):
        without_open = without_open[4:]
    closing = without_open.rfind("```")
    return (without_open[:closing] if closing != -1 else without_open).strip()


def _extract_choice_content(response_data: dict[str, Any], base_url: str) -> str:
    """Pulls choices[0].message.content out of an OpenAI-shaped response,
    raising a diagnosable error rather than a bare KeyError/IndexError when
    the server answered with something else (a wrong endpoint, an auth
    failure, or a provider-specific error body returned with HTTP 200)."""
    try:
        content = response_data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        detail = response_data.get("error") if isinstance(response_data, dict) else None
        raise LLMResponseError(
            f"Local LLM at {base_url} did not return an OpenAI-shaped completion "
            f"({exc!r}). Server said: {detail or response_data!r:.300}. Check that the "
            f"base URL, model name, and server are correct."
        ) from exc
    if not isinstance(content, str):
        raise LLMResponseError(
            f"Local LLM at {base_url} returned a non-text completion content: {content!r:.200}"
        )
    return content


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

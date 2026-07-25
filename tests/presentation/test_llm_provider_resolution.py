"""resolve_llm_engines (spec M10): each LLMRouter slot's real backing engine
is an explicit, independently selectable Settings choice - these tests check
every choice resolves to the right engine class, and that a misconfigured
real provider (no key / unreachable local server) degrades to DemoLLMEngine
rather than raising, so the app never crashes on startup over AI config."""

from __future__ import annotations

from qat.config import Settings
from qat.domain.ai_advisory.llm_engine import AnthropicEngine, DemoLLMEngine, LocalEngine
from qat.presentation.runtime import resolve_llm_engines


def test_demo_provider_resolves_to_demo_engine():
    settings = Settings(
        _env_file=None, general_request_provider="demo", sensitive_request_provider="demo"
    )

    general, sensitive = resolve_llm_engines(settings)

    assert isinstance(general, DemoLLMEngine)
    assert isinstance(sensitive, DemoLLMEngine)


def test_anthropic_provider_with_configured_key_resolves_to_anthropic_engine(monkeypatch):
    monkeypatch.setattr(
        "qat.presentation.runtime.get_secret",
        lambda name: "sk-test" if name == "ANTHROPIC_API_KEY" else None,
    )
    settings = Settings(_env_file=None, general_request_provider="anthropic")

    general, _sensitive = resolve_llm_engines(settings)

    assert isinstance(general, AnthropicEngine)


def test_anthropic_provider_without_key_falls_back_to_demo(monkeypatch):
    monkeypatch.setattr("qat.presentation.runtime.get_secret", lambda name: None)
    settings = Settings(_env_file=None, general_request_provider="anthropic")

    general, _sensitive = resolve_llm_engines(settings)

    assert isinstance(general, DemoLLMEngine)


def test_local_provider_when_reachable_resolves_to_local_engine(monkeypatch):
    monkeypatch.setattr("qat.presentation.runtime._local_llm_reachable", lambda base_url: True)
    settings = Settings(_env_file=None, sensitive_request_provider="local")

    _general, sensitive = resolve_llm_engines(settings)

    assert isinstance(sensitive, LocalEngine)


def test_local_provider_when_unreachable_falls_back_to_demo(monkeypatch):
    monkeypatch.setattr("qat.presentation.runtime._local_llm_reachable", lambda base_url: False)
    settings = Settings(_env_file=None, sensitive_request_provider="local")

    _general, sensitive = resolve_llm_engines(settings)

    assert isinstance(sensitive, DemoLLMEngine)


def test_slots_are_independently_selectable(monkeypatch):
    """The whole point of two slots (spec M10): the sensitive slot can stay
    local-only even when the general slot uses Anthropic's cloud API."""
    monkeypatch.setattr(
        "qat.presentation.runtime.get_secret",
        lambda name: "sk-test" if name == "ANTHROPIC_API_KEY" else None,
    )
    monkeypatch.setattr("qat.presentation.runtime._local_llm_reachable", lambda base_url: True)
    settings = Settings(
        _env_file=None, general_request_provider="anthropic", sensitive_request_provider="local"
    )

    general, sensitive = resolve_llm_engines(settings)

    assert isinstance(general, AnthropicEngine)
    assert isinstance(sensitive, LocalEngine)

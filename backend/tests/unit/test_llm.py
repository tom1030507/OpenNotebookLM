"""Tests for provider selection and failure reporting in the LLM service."""
import sys
import types

import pytest

from app.services import llm as llm_module
from app.services.llm import FALLBACK_MODEL, LLMService

RAG_PROMPT = (
    "Context:\n[Source 1: invoice.pdf]\nTotal amount due NT$690.00. "
    "Issued August 4, 2026. Payable on receipt.\n\nQuestion: What is the total?"
)


class _FakeMessages:
    """Records the request so tests can assert on what was sent."""

    def __init__(self, response, recorder):
        self._response = response
        self._recorder = recorder

    def create(self, **kwargs):
        self._recorder.append(kwargs)
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


class _FakeModels:
    def retrieve(self, model):
        return {"id": model}

    def list(self):
        return []


def _fake_anthropic_response(text="Answer", stop_reason="end_turn"):
    block = types.SimpleNamespace(type="text", text=text)
    usage = types.SimpleNamespace(input_tokens=11, output_tokens=7)
    return types.SimpleNamespace(
        content=[block],
        model="claude-opus-5",
        stop_reason=stop_reason,
        usage=usage,
    )


@pytest.fixture
def fake_anthropic(monkeypatch):
    """Install a stand-in `anthropic` module and return the request recorder."""
    requests = []
    state = {"response": _fake_anthropic_response()}

    class FakeAnthropic:
        def __init__(self, api_key=None):
            self.api_key = api_key
            self.messages = _FakeMessages(state["response"], requests)
            self.models = _FakeModels()

    module = types.ModuleType("anthropic")
    module.Anthropic = FakeAnthropic
    monkeypatch.setitem(sys.modules, "anthropic", module)
    return types.SimpleNamespace(requests=requests, state=state)


@pytest.fixture
def fake_openai(monkeypatch):
    """Install a stand-in `openai` module and return the constructor calls."""
    constructions = []

    class FakeOpenAI:
        def __init__(self, api_key=None, base_url=None):
            constructions.append({"api_key": api_key, "base_url": base_url})
            self.models = _FakeModels()

    module = types.ModuleType("openai")
    module.OpenAI = FakeOpenAI
    monkeypatch.setitem(sys.modules, "openai", module)
    return constructions


@pytest.fixture
def settings(monkeypatch):
    """Reset the provider-selection settings to a known, unconfigured state."""
    for field, value in (
        ("llm_mode", "auto"),
        ("claude_api_key", None),
        ("openai_api_key", None),
        ("claude_model", "claude-opus-5"),
        ("openai_model", "gpt-5.6"),
        ("ollama_model", "llama3.2"),
        ("ollama_base_url", "http://localhost:11434/v1"),
        ("claude_effort", "low"),
        ("claude_min_max_tokens", 2048),
    ):
        monkeypatch.setattr(llm_module.settings, field, value)
    return llm_module.settings


def test_no_provider_configured_answers_extractively(settings, monkeypatch):
    monkeypatch.setattr(settings, "llm_mode", "none")
    service = LLMService()

    assert service.provider is None
    assert service.is_available() is False

    result = service.generate(RAG_PROMPT)
    assert result["model"] == FALLBACK_MODEL
    assert result["usage"]["total_tokens"] == 0


def test_auto_prefers_claude_when_its_key_is_set(settings, monkeypatch, fake_anthropic):
    monkeypatch.setattr(settings, "claude_api_key", "sk-ant-test")
    monkeypatch.setattr(settings, "openai_api_key", "sk-openai-test")

    service = LLMService()

    assert service.provider.name == "claude"
    assert service.provider.model == "claude-opus-5"


def test_auto_falls_back_to_openai_then_local(settings, monkeypatch, fake_openai):
    monkeypatch.setattr(settings, "openai_api_key", "sk-openai-test")
    assert LLMService().provider.name == "openai"
    assert fake_openai[-1]["base_url"] is None

    monkeypatch.setattr(settings, "openai_api_key", None)
    local = LLMService()
    assert local.provider.name == "local"
    assert local.provider.model == "llama3.2"
    assert fake_openai[-1]["base_url"] == "http://localhost:11434/v1"


def test_claude_request_omits_temperature_and_lifts_max_tokens(
    settings, monkeypatch, fake_anthropic
):
    monkeypatch.setattr(settings, "claude_api_key", "sk-ant-test")
    service = LLMService()

    result = service.generate(RAG_PROMPT, temperature=0.7, max_tokens=512)

    sent = fake_anthropic.requests[-1]
    # Current Claude models reject sampling parameters outright.
    assert "temperature" not in sent
    # Thinking shares the output budget, so the caller's 512 is lifted.
    assert sent["max_tokens"] == 2048
    assert sent["output_config"] == {"effort": "low"}
    assert result["model"] == "claude-opus-5"
    assert result["usage"]["total_tokens"] == 18


def test_generation_failure_is_reported_not_swallowed(
    settings, monkeypatch, fake_anthropic
):
    monkeypatch.setattr(settings, "claude_api_key", "sk-ant-test")
    fake_anthropic.state["response"] = RuntimeError("connection refused")
    service = LLMService()
    service.provider._client.messages = _FakeMessages(
        RuntimeError("connection refused"), fake_anthropic.requests
    )

    result = service.generate(RAG_PROMPT)

    # The answer still arrives, but it is labelled as extracted, not generated,
    # and the service now knows the provider is down.
    assert result["model"] == FALLBACK_MODEL
    assert service.is_available() is False
    assert "connection refused" in service.get_info()["error"]


def test_refusal_does_not_masquerade_as_an_answer(
    settings, monkeypatch, fake_anthropic
):
    monkeypatch.setattr(settings, "claude_api_key", "sk-ant-test")
    service = LLMService()
    service.provider._client.messages = _FakeMessages(
        _fake_anthropic_response(text="", stop_reason="refusal"),
        fake_anthropic.requests,
    )

    result = service.generate(RAG_PROMPT)

    assert result["model"] == FALLBACK_MODEL

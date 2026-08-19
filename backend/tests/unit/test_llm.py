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


def _fake_openai_response(text="Answer", model="llama-3.3-70b-versatile"):
    message = types.SimpleNamespace(content=text)
    choice = types.SimpleNamespace(message=message, finish_reason="stop")
    usage = types.SimpleNamespace(
        prompt_tokens=11, completion_tokens=7, total_tokens=18
    )
    return types.SimpleNamespace(choices=[choice], model=model, usage=usage)


@pytest.fixture
def fake_openai(monkeypatch):
    """Install a stand-in `openai` module.

    Returns the constructor calls and the chat requests, so a test can assert on
    both where the client was pointed and what was sent to it.
    """
    constructions = []
    requests = []

    class _FakeCompletions:
        def create(self, **kwargs):
            requests.append(kwargs)
            return _fake_openai_response()

    class FakeOpenAI:
        def __init__(self, api_key=None, base_url=None):
            constructions.append({"api_key": api_key, "base_url": base_url})
            self.models = _FakeModels()
            self.chat = types.SimpleNamespace(completions=_FakeCompletions())

    module = types.ModuleType("openai")
    module.OpenAI = FakeOpenAI
    monkeypatch.setitem(sys.modules, "openai", module)
    return types.SimpleNamespace(constructions=constructions, requests=requests)


@pytest.fixture
def settings(monkeypatch):
    """Reset the provider-selection settings to a known, unconfigured state."""
    for field, value in (
        ("llm_mode", "auto"),
        ("claude_api_key", None),
        ("openai_api_key", None),
        ("claude_model", "claude-opus-5"),
        ("openai_model", "gpt-5.6"),
        ("openai_base_url", None),
        ("openai_reasoning_format", None),
        ("openai_min_max_tokens", 0),
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
    assert fake_openai.constructions[-1]["base_url"] is None

    monkeypatch.setattr(settings, "openai_api_key", None)
    local = LLMService()
    assert local.provider.name == "local"
    assert local.provider.model == "llama3.2"
    assert fake_openai.constructions[-1]["base_url"] == "http://localhost:11434/v1"


def test_openai_base_url_redirects_to_a_compatible_provider(
    settings, monkeypatch, fake_openai
):
    """A base URL points the OpenAI path at Groq, OpenRouter, DeepSeek, ..."""
    monkeypatch.setattr(settings, "openai_api_key", "gsk-test")
    monkeypatch.setattr(settings, "openai_base_url", "https://api.groq.com/openai/v1")
    monkeypatch.setattr(settings, "openai_model", "llama-3.3-70b-versatile")

    service = LLMService()

    assert service.provider.name == "openai"
    assert service.provider.model == "llama-3.3-70b-versatile"
    assert fake_openai.constructions[-1] == {
        "api_key": "gsk-test",
        "base_url": "https://api.groq.com/openai/v1",
    }


def test_empty_base_url_still_reaches_openai(settings, monkeypatch, fake_openai):
    """docker-compose passes `OPENAI_BASE_URL=` when the variable is unset.

    Pydantic reads that as "" rather than None, and forwarding "" as the base URL
    would send every request nowhere. Guards `OpenAICompatibleProvider.__init__`,
    which must keep testing the value for truthiness, not for `is not None`.
    """
    monkeypatch.setattr(settings, "openai_api_key", "sk-openai-test")
    monkeypatch.setattr(settings, "openai_base_url", "")

    assert LLMService().provider.name == "openai"
    assert fake_openai.constructions[-1]["base_url"] is None


def test_output_budget_is_lifted_to_the_floor(settings, monkeypatch, fake_openai):
    """A reasoning model spends this budget on thinking before it answers.

    Measured against Groq's qwen3.6-27b at the 512 services/rag.py sends: turns
    that reasoned for the whole 512 returned a truncated answer, or none at all.
    The thinking comes first, so the ceiling cuts the answer, not the thinking —
    the same reason ClaudeProvider lifts to `claude_min_max_tokens`.
    """
    monkeypatch.setattr(settings, "openai_api_key", "gsk-test")
    monkeypatch.setattr(settings, "openai_min_max_tokens", 2048)

    LLMService().generate("Question: what is the total?", max_tokens=512)

    assert fake_openai.requests[-1]["max_tokens"] == 2048


def test_output_budget_above_the_floor_is_left_alone(
    settings, monkeypatch, fake_openai
):
    """The floor raises a small budget; it never caps a generous one."""
    monkeypatch.setattr(settings, "openai_api_key", "gsk-test")
    monkeypatch.setattr(settings, "openai_min_max_tokens", 2048)

    LLMService().generate("Question: what is the total?", max_tokens=4096)

    assert fake_openai.requests[-1]["max_tokens"] == 4096


def test_reasoning_format_is_sent_when_configured(settings, monkeypatch, fake_openai):
    """Groq's reasoning models otherwise return <think> blocks inside the answer.

    Verified live against `qwen/qwen3.6-27b`: the default format embeds the whole
    chain of thought in `message.content`, which the UI then shows as the answer.
    """
    monkeypatch.setattr(settings, "openai_api_key", "gsk-test")
    monkeypatch.setattr(settings, "openai_base_url", "https://api.groq.com/openai/v1")
    monkeypatch.setattr(settings, "openai_reasoning_format", "hidden")

    LLMService().generate("Question: what is the total?")

    assert fake_openai.requests[-1]["extra_body"] == {"reasoning_format": "hidden"}


def test_reasoning_format_is_absent_unless_configured(
    settings, monkeypatch, fake_openai
):
    """`reasoning_format` is a Groq extension — OpenAI itself rejects unknown keys."""
    monkeypatch.setattr(settings, "openai_api_key", "sk-openai-test")

    LLMService().generate("Question: what is the total?")

    assert "extra_body" not in fake_openai.requests[-1]


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

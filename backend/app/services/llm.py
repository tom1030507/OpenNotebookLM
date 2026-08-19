"""LLM (Large Language Model) service.

Three providers are supported, all optional: Claude (Anthropic), OpenAI, and any
OpenAI-compatible server running locally (Ollama, llama.cpp, vLLM). When none is
configured the service still answers, but extractively — see
:meth:`LLMService._fallback_response` — and reports ``model`` as ``"fallback"``
so callers can tell a real answer from a passage of the source text.
"""
from typing import Any, Dict, Optional

import structlog

from app.config import get_settings

logger = structlog.get_logger()
settings = get_settings()

# The model name reported when no provider answered. Callers (and the API's
# `model_used` field) rely on this to distinguish generated from extracted text.
FALLBACK_MODEL = "fallback"


class ClaudeProvider:
    """Anthropic's Messages API."""

    name = "claude"

    def __init__(self):
        import anthropic  # imported lazily so the dep is optional at runtime

        self._anthropic = anthropic
        self._client = anthropic.Anthropic(api_key=settings.claude_api_key)
        self.model = settings.claude_model

    def check(self) -> None:
        """Raise if the key or the configured model is not usable."""
        self._client.models.retrieve(self.model)

    def generate(
        self,
        prompt: str,
        temperature: float,
        max_tokens: int,
        system_prompt: Optional[str],
    ) -> Dict[str, Any]:
        """Generate an answer with Claude.

        `temperature` is accepted for interface parity and deliberately not
        forwarded: current Claude models reject sampling parameters. Depth is
        controlled by `claude_effort` instead.
        """
        request: Dict[str, Any] = {
            "model": self.model,
            # Thinking is on by default and shares this budget with the answer,
            # so too small a value truncates the reply rather than the thinking.
            "max_tokens": max(max_tokens, settings.claude_min_max_tokens),
            "output_config": {"effort": settings.claude_effort},
            "messages": [{"role": "user", "content": prompt}],
        }
        if system_prompt:
            request["system"] = system_prompt

        response = self._client.messages.create(**request)

        if response.stop_reason == "refusal":
            raise RuntimeError("Claude declined to answer this request")

        text = "".join(
            block.text for block in response.content if block.type == "text"
        )
        return {
            "text": text,
            "model": response.model,
            "usage": {
                "prompt_tokens": response.usage.input_tokens,
                "completion_tokens": response.usage.output_tokens,
                "total_tokens": response.usage.input_tokens
                + response.usage.output_tokens,
            },
        }


class OpenAICompatibleProvider:
    """OpenAI, or any server speaking the same chat-completions API."""

    def __init__(
        self,
        name: str,
        model: str,
        api_key: str,
        base_url: Optional[str],
        reasoning_format: Optional[str] = None,
        min_max_tokens: int = 0,
    ):
        from openai import OpenAI  # imported lazily, as above

        self.name = name
        self.model = model
        self.reasoning_format = reasoning_format
        self.min_max_tokens = min_max_tokens
        self._client = (
            OpenAI(api_key=api_key, base_url=base_url)
            if base_url
            else OpenAI(api_key=api_key)
        )

    def check(self) -> None:
        """Raise if the server is unreachable or the key is rejected."""
        self._client.models.list()

    def generate(
        self,
        prompt: str,
        temperature: float,
        max_tokens: int,
        system_prompt: Optional[str],
    ) -> Dict[str, Any]:
        """Generate an answer through the chat-completions API."""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        request: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            # A reasoning model writes its thinking into this budget first, so
            # the floor is what keeps the ceiling from cutting off the answer.
            "max_tokens": max(max_tokens, self.min_max_tokens),
        }
        if self.reasoning_format:
            # Not part of the OpenAI API. It travels in extra_body, and only
            # when configured, because OpenAI rejects parameters it does not
            # recognise — which would take down the default path.
            request["extra_body"] = {"reasoning_format": self.reasoning_format}

        response = self._client.chat.completions.create(**request)
        usage = response.usage
        return {
            "text": response.choices[0].message.content,
            "model": response.model,
            "usage": {
                "prompt_tokens": usage.prompt_tokens if usage else 0,
                "completion_tokens": usage.completion_tokens if usage else 0,
                "total_tokens": usage.total_tokens if usage else 0,
            },
        }


def _build_provider():
    """Build the provider named by settings, or the first one configured.

    Returns None when nothing is configured — that is a normal state, not an
    error: the service falls back to extractive answers.
    """
    mode = (settings.llm_mode or "auto").lower()

    if mode == "none":
        return None

    if mode in ("claude", "cloud", "auto") and settings.claude_api_key:
        return ClaudeProvider()

    if mode in ("openai", "cloud", "auto") and settings.openai_api_key:
        return OpenAICompatibleProvider(
            name="openai",
            model=settings.openai_model,
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            reasoning_format=settings.openai_reasoning_format,
            min_max_tokens=settings.openai_min_max_tokens,
        )

    if mode in ("local", "auto"):
        return OpenAICompatibleProvider(
            name="local",
            model=settings.ollama_model,
            api_key="not-needed",  # local servers ignore it
            base_url=settings.ollama_base_url,
        )

    return None


class LLMService:
    """Service for LLM text generation."""

    def __init__(self):
        """Select a provider. Construction never performs network I/O."""
        self.mode = settings.llm_mode
        self._availability: Optional[Dict[str, Any]] = None

        try:
            self.provider = _build_provider()
        except Exception as e:
            logger.error(
                "Failed to initialize LLM provider",
                mode=self.mode,
                error_type=type(e).__name__,
                error=str(e),
            )
            self.provider = None

        if self.provider:
            logger.info(
                "LLM provider selected",
                provider=self.provider.name,
                model=self.provider.model,
            )
        else:
            logger.warning(
                "No LLM provider configured; answers will be extractive",
                mode=self.mode,
            )

    def availability(self, refresh: bool = False) -> Dict[str, Any]:
        """Check whether the selected provider can actually be reached.

        The result is cached because this performs a network round trip, and is
        the honest answer to "is question answering working?" — constructing a
        client proves nothing, which is how an unreachable local server used to
        look healthy right up until the first question.

        Args:
            refresh: Re-run the check instead of returning the cached result.

        Returns:
            Provider name, model, whether it is reachable, and any error.
        """
        if self._availability is not None and not refresh:
            return self._availability

        if not self.provider:
            self._availability = {
                "provider": None,
                "model": None,
                "available": False,
                "error": "No LLM provider configured",
            }
            return self._availability

        result = {
            "provider": self.provider.name,
            "model": self.provider.model,
            "available": True,
            "error": None,
        }
        try:
            self.provider.check()
        except Exception as e:
            result["available"] = False
            result["error"] = f"{type(e).__name__}: {e}"
            logger.warning(
                "LLM provider is not reachable",
                provider=self.provider.name,
                model=self.provider.model,
                error_type=type(e).__name__,
                error=str(e),
            )

        self._availability = result
        return result

    def generate(
        self,
        prompt: str,
        temperature: float = 0.7,
        max_tokens: int = 512,
        system_prompt: Optional[str] = None
    ) -> Dict[str, Any]:
        """Generate text using LLM.

        Args:
            prompt: User prompt
            temperature: Sampling temperature (ignored by Claude)
            max_tokens: Maximum tokens to generate
            system_prompt: Optional system prompt

        Returns:
            Generated text and metadata. `model` is "fallback" when no provider
            produced the text.
        """
        if not self.provider:
            return self._fallback_response(prompt)

        try:
            result = self.provider.generate(
                prompt=prompt,
                temperature=temperature,
                max_tokens=max_tokens,
                system_prompt=system_prompt,
            )
            logger.info(
                "LLM generation completed",
                provider=self.provider.name,
                model=result["model"],
                tokens=result["usage"]["total_tokens"],
            )
            return result
        except Exception as e:
            # Surface the real cause: the fallback below reads like an answer,
            # so a silent except here is how a broken provider stays invisible.
            logger.error(
                "LLM generation failed; returning extractive fallback",
                provider=self.provider.name,
                model=self.provider.model,
                error_type=type(e).__name__,
                error=str(e),
            )
            self._availability = {
                "provider": self.provider.name,
                "model": self.provider.model,
                "available": False,
                "error": f"{type(e).__name__}: {e}",
            }
            return self._fallback_response(prompt)

    def _fallback_response(self, prompt: str) -> Dict[str, Any]:
        """Generate a fallback response when LLM is not available.

        Args:
            prompt: User prompt

        Returns:
            Fallback response
        """
        # Extract context and question from RAG prompt
        if "Context:" in prompt and "Question:" in prompt:
            # This is a RAG query
            context_start = prompt.find("Context:") + len("Context:")
            question_start = prompt.find("Question:")
            context = prompt[context_start:question_start].strip()

            # Simple extractive approach: return first few sentences from context
            sentences = context.split(". ")[:3]
            response_text = ". ".join(sentences) + "."

            if "[Source" in response_text:
                response_text = (
                    "Based on the provided documents:\n\n" +
                    response_text +
                    "\n\n(Note: This is a simplified response. Configure an LLM for better answers.)"
                )
        else:
            # Generic response
            response_text = (
                "I understand you're asking about this topic. "
                "However, I need an LLM service configured to provide detailed answers. "
                "Please configure an API key for Claude or OpenAI, or run a local model server."
            )

        return {
            "text": response_text,
            "model": FALLBACK_MODEL,
            "usage": {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0
            }
        }

    def is_available(self) -> bool:
        """Check if LLM service is available.

        Returns:
            True if a provider is configured *and* reachable
        """
        return self.availability()["available"]

    def get_info(self) -> Dict[str, Any]:
        """Get LLM service information.

        Returns:
            Service information
        """
        status = self.availability()
        return {
            "available": status["available"],
            "mode": self.mode,
            "model": status["model"],
            "backend": status["provider"],
            "error": status["error"],
        }

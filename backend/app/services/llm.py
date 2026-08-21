"""LLM (Large Language Model) service.

Three providers are supported, all optional: Claude (Anthropic), OpenAI, and any
OpenAI-compatible server running locally (Ollama, llama.cpp, vLLM). When none is
configured the service still answers, but extractively — see
:meth:`LLMService._fallback_response` — and reports ``model`` as ``"fallback"``
so callers can tell a real answer from a passage of the source text.
"""
import re
from typing import Any, Dict, List, Optional

import structlog

from app.config import get_settings

logger = structlog.get_logger()
settings = get_settings()

# The model name reported when no provider answered. Callers (and the API's
# `model_used` field) rely on this to distinguish generated from extracted text.
FALLBACK_MODEL = "fallback"

# Used only when a caller asks for the model's limit, nothing is configured, and
# the provider will not say what its limit is. Large enough to clear the hidden
# reasoning a thinking model spends before it writes anything, which is the
# failure this whole mechanism exists to avoid.
DEFAULT_MAX_OUTPUT_TOKENS = 4096

# Rough tokens-per-character for the clamp below. Only ever used to leave room
# under a request ceiling, so erring high is the safe direction: a slightly
# over-estimated prompt asks for slightly fewer output tokens.
CHARS_PER_TOKEN = 4

# A provider that refuses an oversized request names the ceiling it applied, but
# a provider whose request quota is spent refuses in the same words, with the
# same code, and names a limit that counts requests. So a refusal is only read
# as a token ceiling when nothing in it points at a request-counting metric.
#   learn:  "... on tokens per minute (TPM): Limit 8000, Requested 10139"
#   ignore: "... on requests per day (RPD): Limit 1000, Used 1000, Requested 1"
_TOKEN_LIMIT_PATTERN = re.compile(r"\bLimit[\s:]+(\d{3,})", re.IGNORECASE)
_TOKEN_REFUSAL_MARKERS = ("token", "too large", "rate_limit", "rate limit")
# The size of the number cannot separate the two: a higher tier's requests-per-
# minute allowance runs into the hundreds, the same range as a small TPM.
_REQUEST_COUNT_MARKERS = ("requests per", "request per", "(rpm)", "(rpd)")


def estimate_prompt_tokens(messages: List[Dict[str, Any]]) -> int:
    """Estimate what a request's messages will cost, before sending it.

    There is no local tokenizer here and adding one to clamp a budget would be
    out of proportion. Character count is close enough: measured against Groq's
    qwen3.6-27b, a two-source script prompt of 3100 characters counted 667
    tokens, which this over-estimates by about a sixth — the direction that
    leaves room rather than taking it.

    Args:
        messages: The chat messages about to be sent.

    Returns:
        An estimated prompt token count.
    """
    characters = sum(len(str(message.get("content") or "")) for message in messages)

    return characters // CHARS_PER_TOKEN + 1


def token_ceiling_from_error(error: Exception) -> Optional[int]:
    """Read the per-request token ceiling out of a provider's refusal.

    A provider that counts the prompt and `max_tokens` together against a rate
    limit refuses the whole request before the model sees it, and says what the
    limit was. Learning it from the refusal means asking for the model's own
    limit can be the default: the ceiling does not have to be known in advance,
    or configured per tier.

    Only a refusal that is genuinely about size counts. A provider also refuses
    once the tier's allowance of *requests* is spent, and says so in the same
    words: Groq's daily quota reports "Limit 1000" meaning a thousand requests,
    not a thousand tokens. Read as a ceiling that number sits below any real
    prompt, so every later request would be clamped to a single token — and it
    would outlast the window it came from, because the provider is held for the
    life of the process and only a restart would clear it.

    Args:
        error: The exception the provider raised.

    Returns:
        The ceiling in tokens, or None if this was not a size or rate refusal,
        or was one whose limit counts requests rather than tokens.
    """
    message = str(error)
    lowered = message.lower()
    if not any(marker in lowered for marker in _TOKEN_REFUSAL_MARKERS):
        return None

    if any(marker in lowered for marker in _REQUEST_COUNT_MARKERS):
        return None

    match = _TOKEN_LIMIT_PATTERN.search(message)
    if not match:
        return None

    ceiling = int(match.group(1))

    return ceiling if ceiling > 0 else None


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
        max_tokens: Optional[int],
        system_prompt: Optional[str],
    ) -> Dict[str, Any]:
        """Generate an answer with Claude.

        `temperature` is accepted for interface parity and deliberately not
        forwarded: current Claude models reject sampling parameters. Depth is
        controlled by `claude_effort` instead.

        `max_tokens` of None means the model's limit, which here is
        `claude_max_output_tokens` rather than anything discovered: the Messages
        API requires the field, and the headline 128k needs streaming to stay
        inside the SDK's HTTP timeout.
        """
        budget = (
            max_tokens if max_tokens is not None
            else settings.claude_max_output_tokens
        )

        request: Dict[str, Any] = {
            "model": self.model,
            # Thinking is on by default and shares this budget with the answer,
            # so too small a value truncates the reply rather than the thinking.
            "max_tokens": max(budget, settings.claude_min_max_tokens),
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
        max_output_tokens: Optional[int] = None,
        max_request_tokens: Optional[int] = None,
    ):
        from openai import OpenAI  # imported lazily, as above

        self.name = name
        self.model = model
        self.reasoning_format = reasoning_format
        self.min_max_tokens = min_max_tokens
        self._configured_max_output = max_output_tokens
        # The model's own limit, asked of the provider the first time a caller
        # wants it. False means "asked, and it would not say".
        self._model_max_output: Any = None
        # Learned from a refusal, or configured. Applies to prompt + max_tokens
        # together, which is what the provider counts.
        self._max_request_tokens = max_request_tokens
        self._client = (
            OpenAI(api_key=api_key, base_url=base_url)
            if base_url
            else OpenAI(api_key=api_key)
        )

    def check(self) -> None:
        """Raise if the server is unreachable or the key is rejected."""
        self._client.models.list()

    def max_output_tokens(self) -> int:
        """How much output to ask for when the caller wants the model's limit.

        Read from the provider rather than tabulated here: OpenAI-compatible
        `/v1/models` reports `max_completion_tokens`, so a new model needs no
        code change. Asked once and remembered, including the failure — a
        provider that does not report it must not be re-asked on every call.

        Returns:
            The configured limit, the model's reported limit, or
            `DEFAULT_MAX_OUTPUT_TOKENS` when neither is available.
        """
        if self._configured_max_output:
            return self._configured_max_output

        if self._model_max_output is None:
            self._model_max_output = self._discover_max_output_tokens() or False

        if self._model_max_output:
            return self._model_max_output

        return DEFAULT_MAX_OUTPUT_TOKENS

    def _discover_max_output_tokens(self) -> Optional[int]:
        """Ask the provider what this model's output limit is.

        Returns:
            The limit, or None if the provider does not report one or could not
            be reached. Not an error: the caller has a default.
        """
        try:
            described = self._client.models.retrieve(self.model).model_dump()
        except Exception as e:
            logger.info(
                "Provider did not describe the model; using the default output budget",
                provider=self.name,
                model=self.model,
                error_type=type(e).__name__,
            )
            return None

        # `max_completion_tokens` is Groq's name for it; `max_output_length`
        # appears alongside it. Neither is in the OpenAI schema, so they arrive
        # as extra fields and are read from the dump rather than as attributes.
        for field in ("max_completion_tokens", "max_output_length"):
            value = described.get(field)
            if isinstance(value, int) and value > 0:
                logger.info(
                    "Read the model's output limit from the provider",
                    provider=self.name,
                    model=self.model,
                    max_output_tokens=value,
                )
                return value

        return None

    def _budget(
        self,
        max_tokens: Optional[int],
        messages: List[Dict[str, Any]],
    ) -> int:
        """Decide the `max_tokens` to send.

        Args:
            max_tokens: What the caller asked for, or None for the model's limit.
            messages: The messages about to be sent, for the clamp below.

        Returns:
            A positive token budget.

        The floor is applied before the ceiling, and the ceiling wins. Both
        failures end in the same place — an unparseable reply falls back — but a
        truncated answer at least arrives, where a request refused for being too
        large returns nothing at all.
        """
        budget = max_tokens if max_tokens is not None else self.max_output_tokens()
        budget = max(budget, self.min_max_tokens)

        if self._max_request_tokens:
            room = self._max_request_tokens - estimate_prompt_tokens(messages)
            budget = min(budget, room)

        return max(budget, 1)

    def generate(
        self,
        prompt: str,
        temperature: float,
        max_tokens: Optional[int],
        system_prompt: Optional[str],
    ) -> Dict[str, Any]:
        """Generate an answer through the chat-completions API.

        `max_tokens` of None means the model's own limit. Omitting the parameter
        instead does *not* mean that — Groq applies its own 2048 default and the
        reply comes back cut off with `finish_reason: length` — so a number is
        always sent.
        """
        messages: List[Dict[str, Any]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        request: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            # A reasoning model writes its thinking into this budget first, so
            # the floor is what keeps the ceiling from cutting off the answer.
            "max_tokens": self._budget(max_tokens, messages),
        }
        if self.reasoning_format:
            # Not part of the OpenAI API. It travels in extra_body, and only
            # when configured, because OpenAI rejects parameters it does not
            # recognise — which would take down the default path.
            request["extra_body"] = {"reasoning_format": self.reasoning_format}

        response = self._create(request, max_tokens, messages)
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

    def _create(
        self,
        request: Dict[str, Any],
        max_tokens: Optional[int],
        messages: List[Dict[str, Any]],
    ) -> Any:
        """Send the request, learning the provider's ceiling if it refuses.

        Asking for the model's limit is only a usable default because of this:
        a provider that counts the prompt and `max_tokens` together against a
        rate limit refuses before the model sees anything, and says what the
        limit was. Remembering it costs one refused request per provider
        instance — the mind map and the video summary hold one each — and the
        request that provoked it is retried at a budget that fits, so nothing is
        lost but a round trip.

        Args:
            request: The request to send. Its `max_tokens` may be rewritten.
            max_tokens: What the caller asked for, for recomputing the budget.
            messages: The messages, for the clamp.

        Returns:
            The provider's response.

        Raises:
            Exception: whatever the provider raised, when the refusal named no
                ceiling or a ceiling was already known — in which case the
                budget was already clamped and retrying would change nothing.
        """
        try:
            return self._client.chat.completions.create(**request)
        except Exception as e:
            ceiling = token_ceiling_from_error(e)
            if ceiling is None or self._max_request_tokens:
                raise

            self._max_request_tokens = ceiling
            request["max_tokens"] = self._budget(max_tokens, messages)
            logger.warning(
                "Provider refused the request size; retrying inside its ceiling",
                provider=self.name,
                model=self.model,
                request_ceiling=ceiling,
                max_tokens=request["max_tokens"],
            )

            return self._client.chat.completions.create(**request)


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
            max_output_tokens=settings.llm_max_output_tokens,
            max_request_tokens=settings.llm_max_request_tokens,
        )

    if mode in ("local", "auto"):
        return OpenAICompatibleProvider(
            name="local",
            model=settings.ollama_model,
            api_key="not-needed",  # local servers ignore it
            base_url=settings.ollama_base_url,
            max_output_tokens=settings.llm_max_output_tokens,
            max_request_tokens=settings.llm_max_request_tokens,
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
        max_tokens: Optional[int] = 512,
        system_prompt: Optional[str] = None
    ) -> Dict[str, Any]:
        """Generate text using LLM.

        Args:
            prompt: User prompt
            temperature: Sampling temperature (ignored by Claude)
            max_tokens: Maximum tokens to generate, or None to ask for as much
                as the model will give. The default stays a modest number so an
                existing caller's behaviour is unchanged; a caller whose reply
                has to be complete to be usable at all — anything parsing JSON
                back — should pass None.
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

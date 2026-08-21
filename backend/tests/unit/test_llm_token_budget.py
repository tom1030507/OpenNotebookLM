"""Unit tests for how much output the LLM layer asks for.

Sizing a request has to satisfy two limits pulling in opposite directions, and
getting either wrong is silent: too small and a reasoning model spends the budget
on thinking and returns a truncated reply that parses to nothing; too large and
the provider counts the prompt and `max_tokens` together against a rate limit and
refuses the whole request before the model sees it.

So callers ask for the model's limit and this layer decides what one request may
actually use — the model's limit read from the provider, clamped by a ceiling
that is learned from the provider's own refusal.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services import llm as llm_module
from app.services.llm import (
    DEFAULT_MAX_OUTPUT_TOKENS,
    FALLBACK_MODEL,
    LLMService,
    OpenAICompatibleProvider,
    TokenBudgetTooSmallError,
    estimate_prompt_tokens,
    token_ceiling_from_error,
)

# What Groq answers with when prompt + max_tokens exceeds the tier's per-minute
# allowance. Copied from a real refusal.
GROQ_413 = (
    "Error code: 413 - {'error': {'message': 'Request too large for model "
    "`qwen/qwen3.6-27b` in organization `org_01k7` service tier `on_demand` on "
    "tokens per minute (TPM): Limit 8000, Requested 10139, please reduce your "
    "message size and try again.', 'type': 'tokens', 'code': "
    "'rate_limit_exceeded'}}"
)

# What Groq answers with when the tier's daily allowance of *requests* is spent.
# Copied from a real refusal. Same wording and the same `rate_limit_exceeded`
# code as the size refusal above, but "Limit 1000" counts requests, not tokens.
GROQ_429_RPD = (
    "Error code: 429 - {'error': {'message': 'Rate limit reached for model "
    "`qwen/qwen3.6-27b` in organization `org_01k7` service tier `on_demand` on "
    "requests per day (RPD): Limit 1000, Used 1000, Requested 1. Please try "
    "again in 5m3.6s.', 'type': 'requests', 'code': 'rate_limit_exceeded'}}"
)

# The per-minute variant. Its limit only happens to be two digits.
GROQ_429_RPM = (
    "Error code: 429 - {'error': {'message': 'Rate limit reached for model "
    "`qwen/qwen3.6-27b` in organization `org_01k7` service tier `on_demand` on "
    "requests per minute (RPM): Limit 30, Used 30, Requested 1. Please try "
    "again in 2.4s.', 'type': 'requests', 'code': 'rate_limit_exceeded'}}"
)


class TestTokenCeilingFromError:
    """Learning the ceiling is what makes the model's limit a usable default."""

    def test_reads_the_limit_out_of_a_size_refusal(self):
        """The provider says what it applied; there is no need to guess it."""
        assert token_ceiling_from_error(Exception(GROQ_413)) == 8000

    def test_ignores_a_daily_request_quota(self):
        """The limit it names is a request count. Read as tokens it lands below
        any real prompt, so every later call asks for a single token."""
        assert token_ceiling_from_error(Exception(GROQ_429_RPD)) is None

    def test_ignores_a_per_minute_request_quota(self):
        """The same message with a different window, and just as not-a-budget."""
        assert token_ceiling_from_error(Exception(GROQ_429_RPM)) is None

    def test_ignores_a_request_quota_that_is_large_enough_to_look_like_tokens(self):
        """A higher tier's RPM runs into the hundreds, so the number's size
        cannot be what tells a request count from a token count."""
        message = GROQ_429_RPM.replace("Limit 30, Used 30", "Limit 500, Used 500")

        assert token_ceiling_from_error(Exception(message)) is None

    def test_ignores_an_unrelated_failure(self):
        """A dead socket says nothing about how large a request may be."""
        assert token_ceiling_from_error(ConnectionError("no route to host")) is None

    def test_ignores_a_refusal_that_names_no_number(self):
        """Nothing to learn, so nothing is remembered and the error stands."""
        assert token_ceiling_from_error(Exception("429 rate limit exceeded")) is None

    def test_ignores_a_number_that_is_not_a_token_limit(self):
        """A 404 mentioning an id must not be mistaken for a budget."""
        assert token_ceiling_from_error(Exception("404 model not found")) is None


class TestEstimatePromptTokens:
    """Only ever used to leave room, so over-estimating is the safe direction."""

    # Measured against Groq's qwen3.6-27b, prompt_tokens per character: English
    # prose costs 0.18, the same passage in Chinese 0.63. A Han character is
    # nearly a token on its own, so one rate for both scripts cannot err high
    # for both.
    LATIN_TOKENS_PER_CHAR = 0.18
    CJK_TOKENS_PER_CHAR = 0.63

    def test_grows_with_the_prompt(self):
        """A longer prompt leaves less room for the answer."""
        short = estimate_prompt_tokens([{"role": "user", "content": "hello"}])
        long = estimate_prompt_tokens([{"role": "user", "content": "word " * 500}])

        assert long > short

    def test_counts_every_message(self):
        """The system prompt is charged too."""
        one = estimate_prompt_tokens([{"role": "user", "content": "x" * 400}])
        two = estimate_prompt_tokens([
            {"role": "system", "content": "x" * 400},
            {"role": "user", "content": "x" * 400},
        ])

        assert two > one

    def test_is_close_to_what_the_provider_charged(self):
        """Measured: a 3100-character script prompt counted 667 tokens."""
        estimate = estimate_prompt_tokens([{"role": "user", "content": "x" * 3100}])

        # Over-estimating is deliberate; being wildly out would make the clamp
        # either useless or crippling.
        assert 667 <= estimate <= 667 * 1.5

    def test_latin_prose_still_errs_high(self):
        """The English calibration is the one already in production; a
        script-aware estimate must not buy Chinese safety with its accuracy."""
        text = "the quick brown fox jumps over the lazy dog. " * 70

        estimate = estimate_prompt_tokens([{"role": "user", "content": text}])

        assert estimate > len(text) * self.LATIN_TOKENS_PER_CHAR

    def test_chinese_errs_high_as_well(self):
        """The bug: charging a Han character a quarter of a token promised room
        that did not exist, so the request was refused anyway — and by then the
        ceiling was known, which is exactly when the retry gives up."""
        text = "檢索增強生成的筆記本系統會把來源切成段落。" * 150

        estimate = estimate_prompt_tokens([{"role": "user", "content": text}])

        assert estimate > len(text) * self.CJK_TOKENS_PER_CHAR

    def test_is_not_wildly_over_for_chinese(self):
        """Erring high is the point, but doubling the real cost would clamp the
        answer down to nothing on a Chinese project."""
        text = "檢索增強生成的筆記本系統會把來源切成段落。" * 150

        estimate = estimate_prompt_tokens([{"role": "user", "content": text}])

        assert estimate <= len(text) * self.CJK_TOKENS_PER_CHAR * 2

    def test_chinese_costs_more_than_the_same_length_of_latin(self):
        """Length alone does not price a prompt; the script it is written in
        does."""
        chinese = estimate_prompt_tokens([{"role": "user", "content": "語" * 300}])
        latin = estimate_prompt_tokens([{"role": "user", "content": "a" * 300}])

        assert chinese > latin

    def test_mixed_scripts_are_charged_at_their_own_rates(self):
        """The normal prompt here: an English instruction over Chinese sources."""
        mixed = estimate_prompt_tokens([
            {"role": "user", "content": "文" * 100 + "a" * 100},
        ])
        all_latin = estimate_prompt_tokens([{"role": "user", "content": "a" * 200}])
        all_chinese = estimate_prompt_tokens([{"role": "user", "content": "文" * 200}])

        assert all_latin < mixed < all_chinese

    def test_full_width_punctuation_is_charged_as_cjk(self):
        """Chinese prose carries a full-width mark every dozen characters, and
        each is its own token rather than a quarter of one."""
        full_width = estimate_prompt_tokens([{"role": "user", "content": "。" * 200}])
        ascii_stops = estimate_prompt_tokens([{"role": "user", "content": "." * 200}])

        assert full_width > ascii_stops

    def test_tolerates_a_message_carrying_no_text(self):
        """Callers build the message list by hand, so a missing or null content
        must cost something rather than raise."""
        assert estimate_prompt_tokens([{"role": "user"}]) >= 1
        assert estimate_prompt_tokens([{"role": "user", "content": None}]) >= 1
        assert estimate_prompt_tokens([]) >= 1


class FakeModels:
    """Stand-in for the provider's models endpoint."""

    def __init__(self, described=None, error=None):
        """Store what `retrieve` should do.

        Args:
            described: Fields the provider reports for the model.
            error: Raise this instead, as an unreachable provider would.
        """
        self.described = described
        self.error = error
        self.calls = 0

    def retrieve(self, model):
        """Describe the model, counting the call."""
        self.calls += 1
        if self.error:
            raise self.error
        return _Described(self.described or {})

    def list(self):
        """Unused here; present so `check()` stays callable."""
        return []


class _Described:
    """Minimal stand-in for the SDK's Model object."""

    def __init__(self, fields):
        self._fields = fields

    def model_dump(self):
        return dict(self._fields)


class FakeCompletions:
    """Stand-in for chat.completions that can refuse the first request."""

    def __init__(self, refuse_first_with=None):
        """Store the scripted refusal.

        Args:
            refuse_first_with: Exception to raise on the first call only.
        """
        self.refuse_first_with = refuse_first_with
        self.requests: list[dict] = []

    def create(self, **request):
        """Record the request, refusing the first one if scripted to."""
        self.requests.append(request)
        if self.refuse_first_with and len(self.requests) == 1:
            raise self.refuse_first_with
        return _completion()


def _completion():
    """Build a minimal stand-in for a chat completion.

    A function rather than nested classes: a class body is not a closure, so
    inner classes cannot see each other's names.
    """
    message = SimpleNamespace(content='{"ok": true}')

    return SimpleNamespace(
        model="stub-model",
        choices=[SimpleNamespace(message=message)],
        usage=SimpleNamespace(
            prompt_tokens=10, completion_tokens=20, total_tokens=30,
        ),
    )


def build(described=None, models_error=None, refuse_first_with=None, **kwargs):
    """Build a provider whose SDK client is a stand-in.

    Args:
        described: Fields `/v1/models` reports.
        models_error: Raise this from `retrieve` instead.
        refuse_first_with: Exception the first completion call raises.
        **kwargs: Passed through to the provider.

    Returns:
        The provider, with `models` and `completions` stand-ins attached for
        assertions.
    """
    models = FakeModels(described=described, error=models_error)
    completions = FakeCompletions(refuse_first_with=refuse_first_with)

    client = SimpleNamespace(
        models=models,
        chat=SimpleNamespace(completions=completions),
    )

    # The provider imports the SDK inside __init__; patching the attribute after
    # construction avoids needing a real key or a real OpenAI package shape.
    provider = OpenAICompatibleProvider(
        name="test", model="a-model", api_key="k", base_url=None, **kwargs,
    )
    provider._client = client
    provider.models = models
    provider.completions = completions

    return provider


class TestModelOutputLimit:
    """The default budget is read from the provider, not tabulated here."""

    def test_reads_the_limit_the_provider_reports(self):
        """A new model then needs no code change."""
        provider = build(described={"max_completion_tokens": 16384})

        assert provider.max_output_tokens() == 16384

    def test_accepts_the_other_name_for_it(self):
        """Groq reports both; neither is in the OpenAI schema."""
        provider = build(described={"max_output_length": 8192})

        assert provider.max_output_tokens() == 8192

    def test_asks_only_once(self):
        """Every generation would otherwise cost an extra round trip."""
        provider = build(described={"max_completion_tokens": 16384})

        provider.max_output_tokens()
        provider.max_output_tokens()

        assert provider.models.calls == 1

    def test_does_not_re_ask_a_provider_that_would_not_say(self):
        """A local server reports nothing useful, and will keep not doing so."""
        provider = build(described={})

        assert provider.max_output_tokens() == DEFAULT_MAX_OUTPUT_TOKENS
        provider.max_output_tokens()

        assert provider.models.calls == 1

    def test_falls_back_when_the_provider_cannot_be_reached(self):
        """Describing the model is a convenience, not a dependency."""
        provider = build(models_error=ConnectionError("down"))

        assert provider.max_output_tokens() == DEFAULT_MAX_OUTPUT_TOKENS

    def test_configuration_wins_and_costs_no_request(self):
        """An operator who has pinned it should not be second-guessed."""
        provider = build(
            described={"max_completion_tokens": 16384},
            max_output_tokens=1234,
        )

        assert provider.max_output_tokens() == 1234
        assert provider.models.calls == 0


class TestBudget:
    """What actually goes on the wire."""

    def test_none_means_the_models_limit(self):
        """Callers whose reply must be complete ask for this."""
        provider = build(described={"max_completion_tokens": 16384})

        provider.generate("hello", 0.3, None, None)

        assert provider.completions.requests[0]["max_tokens"] == 16384

    def test_a_number_is_honoured(self):
        """An existing caller's behaviour must not change under it."""
        provider = build(described={"max_completion_tokens": 16384})

        provider.generate("hello", 0.3, 512, None)

        assert provider.completions.requests[0]["max_tokens"] == 512

    def test_the_floor_is_applied_to_a_small_request(self):
        """A reasoning model spends a small budget on thinking alone."""
        provider = build(
            described={"max_completion_tokens": 16384},
            min_max_tokens=2048,
        )

        provider.generate("hello", 0.3, 512, None)

        assert provider.completions.requests[0]["max_tokens"] == 2048

    def test_max_tokens_is_always_sent(self):
        """Omitting it does not mean the model's limit — Groq applies its own
        2048 default and the reply comes back cut off."""
        provider = build(described={"max_completion_tokens": 16384})

        provider.generate("hello", 0.3, None, None)

        assert "max_tokens" in provider.completions.requests[0]

    def test_a_known_ceiling_leaves_room_for_the_prompt(self):
        """The provider counts prompt and max_tokens together."""
        provider = build(
            described={"max_completion_tokens": 16384},
            max_request_tokens=8000,
        )

        provider.generate("x" * 4000, 0.3, None, None)

        sent = provider.completions.requests[0]["max_tokens"]
        assert sent < 16384
        assert sent + estimate_prompt_tokens(
            [{"role": "user", "content": "x" * 4000}],
        ) <= 8000

    def test_a_ceiling_below_the_floor_sends_nothing(self):
        """Under the floor there is no answer left to truncate: the whole budget
        goes on hidden thinking and `content` comes back null. The request is
        still billed, so not asking beats paying for an empty reply."""
        provider = build(
            described={"max_completion_tokens": 16384},
            min_max_tokens=2048, max_request_tokens=1000,
        )

        with pytest.raises(TokenBudgetTooSmallError):
            provider.generate("x" * 2000, 0.3, None, None)

        assert provider.completions.requests == []

    def test_a_prompt_larger_than_the_ceiling_sends_nothing(self):
        """Room is negative here, and asking for the one token that clamping to
        a positive number leaves buys precisely nothing."""
        provider = build(
            described={"max_completion_tokens": 16384},
            max_request_tokens=10,
        )

        with pytest.raises(TokenBudgetTooSmallError):
            provider.generate("x" * 4000, 0.3, None, None)

        assert provider.completions.requests == []

    def test_room_exactly_at_the_floor_is_not_enough(self):
        """One condition covers two cases, so it has to hold at the boundary:
        a floor the clamp would have to cut into, and — where no floor is
        configured — a ceiling with nothing at all left under it."""
        prompt = "x" * 4000
        room_for = estimate_prompt_tokens([{"role": "user", "content": prompt}])
        provider = build(
            described={"max_completion_tokens": 16384},
            min_max_tokens=2048, max_request_tokens=room_for + 2048,
        )

        with pytest.raises(TokenBudgetTooSmallError):
            provider.generate(prompt, 0.3, None, None)

    def test_a_ceiling_the_prompt_exactly_fills_sends_nothing(self):
        """A provider with no floor configured — the local one — has the same
        problem in its degenerate form: a budget of zero."""
        prompt = "x" * 4000
        room_for = estimate_prompt_tokens([{"role": "user", "content": prompt}])
        provider = build(
            described={"max_completion_tokens": 16384},
            max_request_tokens=room_for,
        )

        with pytest.raises(TokenBudgetTooSmallError):
            provider.generate(prompt, 0.3, None, None)

    def test_headroom_above_the_floor_is_still_clamped_and_used(self):
        """Refusing to send is for the cases that cannot work; the clamp keeps
        doing its job everywhere else."""
        prompt = "x" * 4000
        room_for = estimate_prompt_tokens([{"role": "user", "content": prompt}])
        provider = build(
            described={"max_completion_tokens": 16384},
            min_max_tokens=2048, max_request_tokens=room_for + 2049,
        )

        provider.generate(prompt, 0.3, None, None)

        assert provider.completions.requests[0]["max_tokens"] == 2049


class TestLearningTheCeiling:
    """One wasted request per process, and then it fits."""

    def test_a_size_refusal_is_retried_inside_the_stated_ceiling(self):
        """This is what makes the model's limit safe as a default."""
        provider = build(
            described={"max_completion_tokens": 16384},
            refuse_first_with=Exception(GROQ_413),
        )

        provider.generate("x" * 4000, 0.3, None, None)

        first, second = provider.completions.requests
        assert first["max_tokens"] == 16384
        assert second["max_tokens"] < first["max_tokens"]
        assert second["max_tokens"] + estimate_prompt_tokens(
            first["messages"],
        ) <= 8000

    def test_the_ceiling_is_remembered_for_the_next_call(self):
        """Paying the refusal once is acceptable; paying it every time is not."""
        provider = build(
            described={"max_completion_tokens": 16384},
            refuse_first_with=Exception(GROQ_413),
        )

        provider.generate("x" * 4000, 0.3, None, None)
        provider.generate("x" * 4000, 0.3, None, None)

        assert provider.completions.requests[-1]["max_tokens"] < 16384

    def test_an_unrelated_failure_is_not_retried(self):
        """A dead provider must surface, not be quietly asked twice."""
        provider = build(
            described={"max_completion_tokens": 16384},
            refuse_first_with=ConnectionError("no route to host"),
        )

        with pytest.raises(ConnectionError):
            provider.generate("hello", 0.3, None, None)

        assert len(provider.completions.requests) == 1

    def test_a_spent_request_quota_does_not_become_a_ceiling(self):
        """Providers are module-level singletons, so a ceiling learned from a
        daily quota outlives the quota itself: every answer would fall back to
        extraction until the process restarts."""
        provider = build(
            described={"max_completion_tokens": 16384},
            refuse_first_with=Exception(GROQ_429_RPD),
        )

        with pytest.raises(Exception):
            provider.generate("x" * 4000, 0.3, None, None)

        assert len(provider.completions.requests) == 1

        # The stand-in refuses the first call only, so this one goes through.
        provider.generate("x" * 4000, 0.3, None, None)

        assert provider.completions.requests[-1]["max_tokens"] == 16384

    def test_a_refusal_with_the_ceiling_already_known_is_not_retried(self):
        """The budget was already clamped, so retrying would change nothing."""
        provider = build(
            described={"max_completion_tokens": 16384},
            max_request_tokens=8000,
            refuse_first_with=Exception(GROQ_413),
        )

        with pytest.raises(Exception):
            provider.generate("hello", 0.3, None, None)

        assert len(provider.completions.requests) == 1

    def test_a_ceiling_too_tight_for_the_floor_is_not_retried_under(self):
        """The refused request cost a round trip; retrying it at a budget that
        can only answer with silence would cost a billed one."""
        provider = build(
            described={"max_completion_tokens": 16384},
            min_max_tokens=2048,
            refuse_first_with=Exception(GROQ_413),
        )

        with pytest.raises(TokenBudgetTooSmallError):
            provider.generate("x" * 28000, 0.3, None, None)

        assert len(provider.completions.requests) == 1

    def test_a_ceiling_too_tight_to_retry_under_is_still_remembered(self):
        """This prompt cannot be answered, but the next one is smaller — and it
        should not have to pay for the same refusal again to find that out."""
        provider = build(
            described={"max_completion_tokens": 16384},
            min_max_tokens=2048,
            refuse_first_with=Exception(GROQ_413),
        )

        with pytest.raises(TokenBudgetTooSmallError):
            provider.generate("x" * 28000, 0.3, None, None)
        provider.generate("hello", 0.3, None, None)

        sent = provider.completions.requests[-1]
        assert sent["max_tokens"] < 16384
        assert sent["max_tokens"] + estimate_prompt_tokens(
            sent["messages"],
        ) <= 8000


class TestTheServiceFallsBack:
    """A budget too small to send must read as 'this provider could not answer'."""

    def test_a_request_not_worth_sending_is_answered_extractively(
        self, monkeypatch,
    ):
        """Not an API error: the caller asked a question and gets the extracted
        passage, exactly as it would if the provider had refused."""
        provider = build(
            described={"max_completion_tokens": 16384},
            min_max_tokens=2048, max_request_tokens=1000,
        )
        monkeypatch.setattr(llm_module, "_build_provider", lambda: provider)
        service = LLMService()

        result = service.generate("x" * 2000, max_tokens=None)

        assert result["model"] == FALLBACK_MODEL
        assert provider.completions.requests == []
        assert service.is_available() is False

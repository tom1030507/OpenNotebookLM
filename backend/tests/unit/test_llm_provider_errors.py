"""What the reader is told when the model provider fails (#230)."""
from __future__ import annotations

import pytest

from app.services.llm import TokenBudgetTooSmallError, describe_provider_error


def provider_error(status_code, module="openai"):
    """Build an exception that looks like one raised by a provider SDK."""
    error_type = type("APIStatusError", (Exception,), {"status_code": status_code})
    error_type.__module__ = module
    return error_type("Error code: %s - {'error': {...}}" % status_code)


@pytest.mark.parametrize(
    ("status_code", "phrase"),
    [
        (401, "API key"),
        (403, "API key"),
        (404, "model name"),
        (429, "try again in a minute"),
        (500, "could not be reached"),
        (None, "could not be reached"),
    ],
)
def test_names_the_cause_without_the_raw_provider_message(status_code, phrase):
    described = describe_provider_error(provider_error(status_code))

    assert phrase in described
    assert "Error code" not in described


def test_covers_the_anthropic_sdk_and_transport_errors_too():
    assert describe_provider_error(provider_error(401, module="anthropic"))
    assert describe_provider_error(provider_error(None, module="httpx"))


def test_explains_a_request_too_large_for_the_model():
    described = describe_provider_error(TokenBudgetTooSmallError("ceiling"))

    assert "fewer sources" in described


def test_leaves_errors_from_elsewhere_to_the_caller():
    assert describe_provider_error(RuntimeError("database is locked")) is None

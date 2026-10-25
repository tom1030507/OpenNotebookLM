"""Provider adapters normalize search results without making live requests."""
import pytest

from app.config import Settings


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


@pytest.mark.parametrize(
    ("provider", "payload", "expected_request", "expected_result"),
    [
        (
            "searxng",
            {"results": [{
                "title": "Searx result",
                "url": "https://EXAMPLE.com/page#section",
                "content": "Searx snippet",
            }]},
            {
                "method": "get",
                "url": "http://searxng:8080/search",
                "kwargs": {"params": {"q": "topic", "format": "json"}},
            },
            {"title": "Searx result", "url": "https://example.com/page", "snippet": "Searx snippet"},
        ),
        (
            "brave",
            {"web": {"results": [{
                "title": "Brave result",
                "url": "https://example.com/brave",
                "description": "Brave snippet",
            }]}},
            {
                "method": "get",
                "url": "https://api.search.brave.com/res/v1/web/search",
                "kwargs": {
                    "params": {"q": "topic", "count": 6},
                    "headers": {"X-Subscription-Token": "brave-key"},
                },
            },
            {"title": "Brave result", "url": "https://example.com/brave", "snippet": "Brave snippet"},
        ),
        (
            "tavily",
            {"results": [{
                "title": "Tavily result",
                "url": "https://example.com/tavily",
                "content": "Tavily snippet",
            }]},
            {
                "method": "post",
                "url": "https://api.tavily.com/search",
                "kwargs": {
                    "headers": {"Authorization": "Bearer tavily-key"},
                    "json": {
                        "query": "topic",
                        "search_depth": "basic",
                        "max_results": 6,
                        "include_answer": False,
                        "include_raw_content": False,
                    },
                },
            },
            {"title": "Tavily result", "url": "https://example.com/tavily", "snippet": "Tavily snippet"},
        ),
    ],
)
def test_provider_requests_are_normalized_and_bounded(
    monkeypatch, provider, payload, expected_request, expected_result
):
    from app.services import web_discovery

    calls = []

    def request(url, **kwargs):
        calls.append({"url": url, "kwargs": kwargs})
        return FakeResponse(payload)

    monkeypatch.setattr(web_discovery.requests, expected_request["method"], request)
    settings = Settings(
        _env_file=None,
        search_provider=provider,
        searxng_url="http://searxng:8080" if provider == "searxng" else None,
        brave_search_api_key="brave-key" if provider == "brave" else None,
        tavily_api_key="tavily-key" if provider == "tavily" else None,
    )

    results = web_discovery.WebSearchService(settings).search("topic", count=6)

    assert calls == [{
        "url": expected_request["url"],
        "kwargs": {**expected_request["kwargs"], "timeout": 10},
    }]
    assert results == [expected_result]


def test_search_drops_unsafe_and_duplicate_urls(monkeypatch):
    from app.services import web_discovery

    payload = {"results": [
        {"title": "First", "url": "https://example.com/page#top", "content": "One"},
        {"title": "Duplicate", "url": "https://EXAMPLE.com/page#other", "content": "Two"},
        {"title": "Internal", "url": "http://127.0.0.1/admin", "content": "Private"},
        {"title": "Bad scheme", "url": "javascript:alert(1)", "content": "Bad"},
    ]}
    monkeypatch.setattr(
        web_discovery.requests,
        "get",
        lambda *_args, **_kwargs: FakeResponse(payload),
    )
    service = web_discovery.WebSearchService(Settings(
        _env_file=None,
        search_provider="searxng",
        searxng_url="http://searxng:8080",
    ))

    results = service.search("topic", count=10)

    assert results == [{
        "title": "First",
        "url": "https://example.com/page",
        "snippet": "One",
    }]

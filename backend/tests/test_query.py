"""Query abuse-control tests over the real HTTP route."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.db.database import get_db
from app.routers import query
from app.routers.auth import get_current_user
from app.routers.rate_limit import get_concurrency_limiter, get_rate_limiter
from app.services.rate_limit import ConcurrencyLimiter, SlidingWindowRateLimiter


QUERY_RESULT = {
    "answer": "answer",
    "sources": [],
    "chunks_used": 0,
    "model_used": "test",
    "usage": {},
}


def query_client(
    monkeypatch,
    rag_service,
    request_limiter=None,
    concurrency=None,
    route_settings=None,
):
    """Build a query client with external retrieval and authentication isolated.

    Args:
        monkeypatch: Pytest monkeypatch fixture.
        rag_service: RAG service double used by the production route.
        request_limiter: Optional request-rate limiter.
        concurrency: Optional concurrency limiter.
        route_settings: Optional settings supplied through FastAPI dependency
            injection.

    Returns:
        TestClient serving the real query route.
    """
    app = FastAPI()
    app.include_router(query.router, prefix="/api")
    request_limiter = request_limiter or SlidingWindowRateLimiter(enabled=False)
    concurrency = concurrency or ConcurrencyLimiter(max_concurrent=2)
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="user-a")
    app.dependency_overrides[get_db] = lambda: object()
    app.dependency_overrides[get_rate_limiter] = lambda: request_limiter
    app.dependency_overrides[get_concurrency_limiter] = lambda: concurrency
    if route_settings is not None:
        app.dependency_overrides[get_settings] = lambda: route_settings
    monkeypatch.setattr(query, "owned_document_ids", lambda *args: [])
    app.dependency_overrides[query.get_rag_service] = lambda: rag_service
    return TestClient(app)


def test_thirty_first_query_for_one_account_returns_429(monkeypatch):
    """Query budget is thirty requests per account per minute."""
    class FastRAG:
        def query(self, **kwargs):
            return QUERY_RESULT

    client = query_client(
        monkeypatch,
        FastRAG(),
        request_limiter=SlidingWindowRateLimiter(),
    )

    responses = [client.post("/api/query", json={"query": "hello"}) for _ in range(31)]

    assert [response.status_code for response in responses[:30]] == [200] * 30
    assert responses[-1].status_code == 429
    assert responses[-1].headers["Retry-After"] == "60"


def test_query_uses_maximum_output_budget_when_caller_omits_limit(monkeypatch):
    """The default query budget leaves a reasoning model room to finish."""
    received_max_tokens = None

    class RecordingRAG:
        def query(self, **kwargs):
            nonlocal received_max_tokens
            received_max_tokens = kwargs["max_tokens"]
            return QUERY_RESULT

    response = query_client(monkeypatch, RecordingRAG()).post(
        "/api/query",
        json={"query": "introduce this document"},
    )

    assert response.status_code == 200
    assert received_max_tokens == 8192


def test_third_concurrent_query_for_one_account_returns_429(monkeypatch):
    """A third active model call cannot consume another worker/budget slot."""
    started = Event()
    release = Event()
    lock = Lock()
    active = 0

    class BlockingRAG:
        def query(self, **kwargs):
            nonlocal active
            with lock:
                active += 1
                if active == 2:
                    started.set()
            release.wait(timeout=5)
            with lock:
                active -= 1
            return QUERY_RESULT

    client = query_client(monkeypatch, BlockingRAG())
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(client.post, "/api/query", json={"query": "one"})
        second = executor.submit(client.post, "/api/query", json={"query": "two"})
        assert started.wait(timeout=5), "two query operations never became active"

        third = client.post("/api/query", json={"query": "three"})
        release.set()

        assert first.result(timeout=5).status_code == 200
        assert second.result(timeout=5).status_code == 200

    assert third.status_code == 429
    assert third.headers["Retry-After"] == "1"


def test_disabled_controls_ignore_an_exhausted_query_rate_window(monkeypatch):
    """RATE_LIMIT_ENABLED=false bypasses the query request window."""
    limiter = SlidingWindowRateLimiter()
    for _ in range(30):
        assert limiter.check("query:user-a", 30, 60).allowed

    class FastRAG:
        def query(self, **kwargs):
            return QUERY_RESULT

    monkeypatch.setattr(query.get_settings(), "rate_limit_enabled", False)
    response = query_client(
        monkeypatch,
        FastRAG(),
        request_limiter=limiter,
    ).post("/api/query", json={"query": "hello"})

    assert response.status_code == 200


def test_disabled_query_controls_follow_settings_override_after_cache_reset(
    monkeypatch,
):
    """A cache reset cannot leave query on an obsolete settings object."""
    limiter = SlidingWindowRateLimiter()
    for _ in range(30):
        assert limiter.check("query:user-a", 30, 60).allowed

    class FastRAG:
        def query(self, **kwargs):
            return QUERY_RESULT

    get_settings.cache_clear()
    try:
        response = query_client(
            monkeypatch,
            FastRAG(),
            request_limiter=limiter,
            route_settings=Settings(rate_limit_enabled=False),
        ).post("/api/query", json={"query": "hello"})
    finally:
        get_settings.cache_clear()

    assert response.status_code == 200


def test_disabled_controls_ignore_an_occupied_query_concurrency_slot(monkeypatch):
    """RATE_LIMIT_ENABLED=false also bypasses active query quotas."""
    concurrency = ConcurrencyLimiter(max_concurrent=1)
    occupied = concurrency.acquire("query:user-a")

    class FastRAG:
        def query(self, **kwargs):
            return QUERY_RESULT

    monkeypatch.setattr(query.get_settings(), "rate_limit_enabled", False)
    try:
        response = query_client(
            monkeypatch,
            FastRAG(),
            concurrency=concurrency,
        ).post("/api/query", json={"query": "hello"})
    finally:
        occupied.release()

    assert response.status_code == 200

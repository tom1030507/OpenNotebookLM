"""Query abuse-control tests over the real HTTP route."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

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


def query_client(monkeypatch, rag_service, request_limiter=None, concurrency=None):
    """Build a query client with external retrieval and authentication isolated.

    Args:
        monkeypatch: Pytest monkeypatch fixture.
        rag_service: RAG service double used by the production route.
        request_limiter: Optional request-rate limiter.
        concurrency: Optional concurrency limiter.

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
    monkeypatch.setattr(query, "owned_document_ids", lambda *args: [])
    monkeypatch.setattr(query, "rag_service", rag_service)
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

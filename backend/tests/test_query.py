"""Query abuse-control tests over the real HTTP route."""
from concurrent.futures import ThreadPoolExecutor
import asyncio
import json
from threading import Event, Lock
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
import pytest
from starlette.requests import ClientDisconnect

from app.config import Settings, get_settings
from app.db.database import get_db
from app.routers import query
from app.routers.auth import get_current_user
from app.routers.rate_limit import get_concurrency_limiter, get_rate_limiter
from app.schemas import SourceSelection
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
    database=None,
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
    database = database if database is not None else object()
    app.dependency_overrides[get_db] = lambda: database
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
    # The window is counted from the first request, so a slow run reports 58 or 59.
    assert 55 <= int(responses[-1].headers["Retry-After"]) <= 60


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


def test_query_response_exposes_citation_checks_from_rag(monkeypatch):
    checks = [{
        "sentence_index": 2,
        "cited_labels": [1, 3],
        "score": 0.42,
        "supported": False,
    }]

    class CheckedRAG:
        def query(self, **kwargs):
            return {**QUERY_RESULT, "citation_checks": checks}

    response = query_client(monkeypatch, CheckedRAG()).post(
        "/api/query", json={"query": "hello"},
    )

    assert response.status_code == 200
    assert response.json()["citation_checks"] == checks


def test_query_response_omits_citation_checks_when_rag_has_none(monkeypatch):
    class LegacyRAG:
        def query(self, **kwargs):
            return QUERY_RESULT

    response = query_client(monkeypatch, LegacyRAG()).post(
        "/api/query", json={"query": "hello"},
    )

    assert response.status_code == 200
    assert "citation_checks" not in response.json()


class ScopeRecordingRAG:
    """Records the document scope the route hands to retrieval."""

    allowed = None

    def query(self, **kwargs):
        self.allowed = kwargs["allowed_document_ids"]
        return QUERY_RESULT


def test_a_source_selection_becomes_the_retrieval_scope(monkeypatch):
    """Selected ids replace the owned set once they resolve as the caller's."""
    rag = ScopeRecordingRAG()
    client = query_client(monkeypatch, rag)
    monkeypatch.setattr(query, "require_documents", lambda db, ids, user, **kwargs: ids)

    response = client.post(
        "/api/query", json={"query": "hello", "document_ids": ["doc-1"]},
    )

    assert response.status_code == 200
    assert rag.allowed == ["doc-1"]


def test_project_conversation_query_scopes_selection_to_visible_project(monkeypatch):
    """A saved chat retrieves only sources linked to its current project."""
    class RecordingRAG:
        allowed = None

        def query_with_conversation(self, **kwargs):
            self.allowed = kwargs["allowed_document_ids"]
            return QUERY_RESULT

    rag = RecordingRAG()
    client = query_client(monkeypatch, rag)
    project_checks = []
    document_scopes = []
    conversation = SimpleNamespace(project_id="project-1")

    def record_project(_db, project_id, _user, min_role="owner"):
        project_checks.append((project_id, min_role))
        return object()

    def record_documents(_db, document_ids, _user, project_id=None):
        document_scopes.append(project_id)
        return document_ids

    monkeypatch.setattr(
        query, "owned_document_ids",
        lambda _db, _user, project_id=None: ["project-doc"] if project_id else ["owned-doc"],
    )
    monkeypatch.setattr(query, "require_project", record_project)
    monkeypatch.setattr(query, "require_conversation", lambda *_args: conversation)
    monkeypatch.setattr(query, "require_documents", record_documents)

    response = client.post(
        "/api/query",
        json={
            "query": "What does the shared source say?",
            "project_id": "project-1",
            "conversation_id": "conversation-1",
            "document_ids": ["project-doc"],
        },
    )

    assert response.status_code == 200, response.text
    assert project_checks == [("project-1", "viewer")]
    assert document_scopes == ["project-1"]
    assert rag.allowed == ["project-doc"]


def test_query_rejects_more_than_500_selected_sources_with_422(monkeypatch):
    """Bound query lookup work before it reaches ownership resolution."""
    class FastRAG:
        def query(self, **kwargs):
            return QUERY_RESULT

    client = query_client(monkeypatch, FastRAG())
    monkeypatch.setattr(query, "require_documents", lambda *args: args[1])

    response = client.post(
        "/api/query",
        json={
            "query": "hello",
            "document_ids": ["doc-%03d" % index for index in range(501)],
        },
    )

    assert response.status_code == 422


def test_query_deduplicates_source_ids_before_ownership_lookup(monkeypatch):
    """Repeated ids resolve once and retain the caller's selection order."""
    rag = ScopeRecordingRAG()
    client = query_client(monkeypatch, rag)
    looked_up = []

    def record_lookup(_db, document_ids, _user):
        looked_up.append(document_ids)
        return document_ids

    monkeypatch.setattr(query, "require_documents", record_lookup)

    response = client.post(
        "/api/query",
        json={
            "query": "hello",
            "document_ids": ["doc-1", "doc-1", "doc-2", "doc-1"],
        },
    )

    assert response.status_code == 200
    assert looked_up == [["doc-1", "doc-2"]]
    assert rag.allowed == ["doc-1", "doc-2"]


def test_query_counts_unique_ids_toward_the_selection_limit(monkeypatch):
    """More than 500 raw entries are allowed when they name one source."""
    rag = ScopeRecordingRAG()
    client = query_client(monkeypatch, rag)
    looked_up = []

    def record_lookup(_db, document_ids, _user):
        looked_up.append(document_ids)
        return document_ids

    monkeypatch.setattr(query, "require_documents", record_lookup)

    response = client.post(
        "/api/query",
        json={"query": "hello", "document_ids": ["doc-1"] * 501},
    )

    assert response.status_code == 200
    assert looked_up == [["doc-1"]]
    assert rag.allowed == ["doc-1"]


def test_studio_selection_rejects_more_than_500_source_ids():
    """Studio's shared selection body has the same request-size ceiling."""
    with pytest.raises(ValidationError):
        SourceSelection(
            document_ids=["doc-%03d" % index for index in range(501)]
        )


def test_studio_selection_deduplicates_source_ids_in_order():
    """Every Studio route sees a stable, unique selection from its schema."""
    selection = SourceSelection(
        document_ids=["doc-1", "doc-1", "doc-2", "doc-1"]
    )

    assert selection.document_ids == ["doc-1", "doc-2"]


def test_studio_selection_caps_unique_ids_after_deduplication():
    """Studio selection accepts repeated copies of a single source id."""
    selection = SourceSelection(document_ids=["doc-1"] * 501)

    assert selection.document_ids == ["doc-1"]


def test_omitting_the_selection_keeps_the_owned_scope(monkeypatch):
    """Without `document_ids` the route scopes exactly as it always has."""
    rag = ScopeRecordingRAG()
    client = query_client(monkeypatch, rag)
    monkeypatch.setattr(query, "owned_document_ids", lambda *args: ["doc-1", "doc-2"])

    response = client.post("/api/query", json={"query": "hello"})

    assert response.status_code == 200
    assert rag.allowed == ["doc-1", "doc-2"]


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


class RecordingDatabase:
    def __init__(self):
        self.rows = []
        self.commits = 0

    def add(self, row):
        self.rows.append(row)

    def commit(self):
        self.commits += 1


def test_query_stream_emits_tokens_then_persists_once_with_final_metadata(monkeypatch):
    database = RecordingDatabase()
    conversation = SimpleNamespace(id="conversation-1", project_id=None)

    class StreamingRAG:
        def stream_query_with_conversation(self, **kwargs):
            assert kwargs["allowed_document_ids"] == ["doc-1"]
            assert database.commits == 0
            yield "delta", "first "
            assert database.commits == 0
            yield "delta", "answer"
            assert database.commits == 0
            yield "complete", {
                **QUERY_RESULT,
                "sources": [{"id": 1, "document_id": "doc-1"}],
            }
            assert database.commits == 1

    monkeypatch.setattr(query, "require_conversation", lambda *_args: conversation)
    monkeypatch.setattr(query, "require_documents", lambda _db, ids, _user, **_: ids)
    client = query_client(
        monkeypatch,
        StreamingRAG(),
        route_settings=Settings(rate_limit_enabled=False),
        database=database,
    )

    response = client.post(
        "/api/query/stream",
        json={
            "query": "hello",
            "conversation_id": "conversation-1",
            "document_ids": ["doc-1"],
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    frames = [frame for frame in response.text.split("\n\n") if frame]
    assert [frame.splitlines()[0] for frame in frames] == [
        "event: token", "event: token", "event: complete",
    ]
    complete = json.loads(frames[-1].split("data: ", 1)[1])
    assert complete["answer"] == "answer"
    assert complete["conversation_id"] == "conversation-1"
    assert complete["message_id"] == database.rows[-1].id
    assert database.commits == 1
    assert [row.role for row in database.rows] == ["user", "assistant"]


def test_query_stream_enforces_the_existing_request_rate_limit(monkeypatch):
    limiter = SlidingWindowRateLimiter()
    for _ in range(30):
        assert limiter.check("query:user-a", 30, 60).allowed

    class StreamingRAG:
        called = False

        def stream_query_with_conversation(self, **_kwargs):
            self.called = True
            yield "complete", QUERY_RESULT

    rag = StreamingRAG()
    response = query_client(
        monkeypatch,
        rag,
        request_limiter=limiter,
        route_settings=Settings(rate_limit_enabled=True),
    ).post("/api/query/stream", json={"query": "hello"})

    assert response.status_code == 429
    assert response.headers["Retry-After"]
    assert rag.called is False


def test_query_stream_reports_generation_errors_after_started_tokens(monkeypatch):
    database = RecordingDatabase()
    conversation = SimpleNamespace(id="conversation-1", project_id=None)

    class FailingRAG:
        def stream_query_with_conversation(self, **_kwargs):
            yield "delta", "partial"
            raise RuntimeError("provider failed")

    monkeypatch.setattr(query, "require_conversation", lambda *_args: conversation)
    client = query_client(
        monkeypatch,
        FailingRAG(),
        route_settings=Settings(rate_limit_enabled=False),
        database=database,
    )

    response = client.post(
        "/api/query/stream",
        json={"query": "hello", "conversation_id": "conversation-1"},
    )

    frames = [frame for frame in response.text.split("\n\n") if frame]
    assert [frame.splitlines()[0] for frame in frames] == [
        "event: token", "event: error",
    ]
    assert json.loads(frames[-1].split("data: ", 1)[1]) == {
        "detail": "provider failed",
    }
    assert database.rows == []
    assert database.commits == 0


def test_query_stream_disconnect_discards_messages_and_releases_lease(monkeypatch):
    database = RecordingDatabase()
    conversation = SimpleNamespace(id="conversation-1", project_id=None)
    limiter = ConcurrencyLimiter(max_concurrent=1)

    class StreamingRAG:
        closed = False

        def stream_query_with_conversation(self, **_kwargs):
            try:
                yield "delta", "partial answer"
                yield "complete", QUERY_RESULT
            finally:
                self.closed = True

    rag = StreamingRAG()
    monkeypatch.setattr(query, "require_conversation", lambda *_args: conversation)
    monkeypatch.setattr(query, "owned_document_ids", lambda *_args: [])
    response = query.stream_query(
        request=query.QueryRequest(
            query="hello", conversation_id="conversation-1",
        ),
        db=database,
        current_user=SimpleNamespace(id="user-a"),
        rag_service=rag,
        request_limiter=SlidingWindowRateLimiter(),
        concurrency_limiter=limiter,
        settings=Settings(rate_limit_enabled=True),
    )

    async def disconnect_after_first_event():
        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            if message["type"] == "http.response.body" and message.get("body"):
                raise OSError("client disconnected")

        with pytest.raises(ClientDisconnect):
            await response(
                {
                    "type": "http",
                    "asgi": {"version": "3.0", "spec_version": "2.4"},
                },
                receive,
                send,
            )

    asyncio.run(disconnect_after_first_event())

    assert rag.closed is True
    assert database.rows == []
    assert database.commits == 0
    limiter.acquire("query:user-a").release()

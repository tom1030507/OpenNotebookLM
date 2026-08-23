"""Ingestion boundary tests for streamed uploads and stable refusals."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db.database import get_db
from app.routers import ingest
from app.routers.auth import get_current_user
from app.routers.rate_limit import get_concurrency_limiter, get_rate_limiter
from app.services.documents import DocumentService, UploadTooLargeError
from app.services.rate_limit import ConcurrencyLimiter, SlidingWindowRateLimiter
from app.utils.network import UnsafeURLError


class OversizedPDFStream:
    """A 50 MiB+ stream that fails the test if production requests all bytes."""

    def __init__(self, size):
        """Initialize the synthetic stream.

        Args:
            size: Total number of bytes exposed by the stream.
        """
        self.remaining = size
        self.read_sizes = []

    def read(self, size=-1):
        """Return at most one requested block without allocating the full file.

        Args:
            size: Maximum bytes requested by production.

        Returns:
            The next synthetic bytes, or an empty block at EOF.
        """
        assert size == 1024 * 1024, "PDF uploads must be read in 1 MiB blocks"
        self.read_sizes.append(size)
        if not self.remaining:
            return b""
        block_size = min(size, self.remaining)
        self.remaining -= block_size
        return b"x" * block_size


def test_oversized_pdf_stops_streaming_and_removes_the_partial_file(tmp_path, monkeypatch):
    """A 50 MiB+ body is rejected without one unbounded in-memory read."""
    stream = OversizedPDFStream(50 * 1024 * 1024 + 1)
    service = DocumentService(chunking_service=object(), embedding_service=object())
    monkeypatch.setattr("app.services.documents.UPLOAD_DIR", tmp_path)

    with pytest.raises(UploadTooLargeError):
        asyncio.run(service.process_pdf_upload(
            db=object(),
            project_id="project",
            user_id="user",
            file=stream,
            filename="large.pdf",
        ))

    assert len(stream.read_sizes) == 51
    assert list(tmp_path.iterdir()) == []


def test_upload_route_returns_413_before_calling_the_document_service(monkeypatch):
    """An oversized declared/body upload gets a stable resource-limit status."""
    app = FastAPI()
    app.include_router(ingest.router, prefix="/api")
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="user")
    app.dependency_overrides[get_db] = lambda: object()
    monkeypatch.setattr(ingest, "require_project", lambda *args: object())
    monkeypatch.setattr(ingest.settings, "max_file_size_mb", 0)

    class MustNotRun:
        async def process_pdf_upload(self, **kwargs):
            raise AssertionError("oversized upload reached document processing")

    monkeypatch.setattr(ingest, "document_service", MustNotRun())

    response = TestClient(app).post(
        "/api/projects/project/upload",
        files={"file": ("large.pdf", b"x", "application/pdf")},
    )

    assert response.status_code == 413


def test_upload_route_rejects_oversized_content_length_before_service(monkeypatch):
    """A declared oversized request is refused before its file is copied."""
    app = FastAPI()
    app.include_router(ingest.router, prefix="/api")
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="user")
    app.dependency_overrides[get_db] = lambda: object()
    monkeypatch.setattr(ingest, "require_project", lambda *args: object())
    monkeypatch.setattr(ingest.settings, "max_file_size_mb", 1)

    class MustNotRun:
        async def process_pdf_upload(self, **kwargs):
            raise AssertionError("declared oversized upload reached the service")

    monkeypatch.setattr(ingest, "document_service", MustNotRun())

    response = TestClient(app).post(
        "/api/projects/project/upload",
        headers={"Content-Length": str(2 * 1024 * 1024)},
        files={"file": ("declared-large.pdf", b"x", "application/pdf")},
    )

    assert response.status_code == 413


def test_url_fetch_boundary_fails_before_any_document_is_created():
    """An unsafe or oversized response cannot leave a queued document behind."""
    service = DocumentService(chunking_service=object(), embedding_service=object())

    class RefusingAdapter:
        def extract_content(self, url):
            raise UnsafeURLError("URL response exceeds the 10MB limit")

    class MustNotTouchDatabase:
        def __getattr__(self, name):
            raise AssertionError("unsafe URL touched the database through %s" % name)

    service.url_adapter = RefusingAdapter()

    with pytest.raises(UnsafeURLError, match="10MB"):
        asyncio.run(service.process_url(
            db=MustNotTouchDatabase(),
            project_id="project",
            user_id="user",
            url="https://example.com/large",
        ))


def test_url_upload_route_returns_400_for_a_fetch_boundary_refusal(monkeypatch):
    """SSRF and response caps have a stable client-visible status code."""
    app = FastAPI()
    app.include_router(ingest.router, prefix="/api")
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="user")
    app.dependency_overrides[get_db] = lambda: object()
    monkeypatch.setattr(ingest, "require_project", lambda *args: object())

    class RefusingService:
        async def process_url(self, **kwargs):
            raise UnsafeURLError("URL destination must be globally routable")

    monkeypatch.setattr(ingest, "document_service", RefusingService())

    response = TestClient(app).post(
        "/api/projects/project/upload-url",
        json={"url": "http://127.0.0.1/admin"},
    )

    assert response.status_code == 400
    assert "globally routable" in response.json()["detail"]


def url_ingest_client(monkeypatch, service, request_limiter=None, concurrency=None):
    """Build a URL-ingestion client with external work isolated.

    Args:
        monkeypatch: Pytest monkeypatch fixture.
        service: Document service double used by the production route.
        request_limiter: Optional request-rate limiter.
        concurrency: Optional active-operation limiter.

    Returns:
        TestClient serving the real ingestion route.
    """
    app = FastAPI()
    app.include_router(ingest.router, prefix="/api")
    request_limiter = request_limiter or SlidingWindowRateLimiter(enabled=False)
    concurrency = concurrency or ConcurrencyLimiter(max_concurrent=2)
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="user")
    app.dependency_overrides[get_db] = lambda: object()
    app.dependency_overrides[get_rate_limiter] = lambda: request_limiter
    app.dependency_overrides[get_concurrency_limiter] = lambda: concurrency
    monkeypatch.setattr(ingest, "require_project", lambda *args: object())
    monkeypatch.setattr(ingest, "document_service", service)
    return TestClient(app)


def test_eleventh_ingestion_for_one_account_returns_429(monkeypatch):
    """Document creation is limited to ten operations per account per minute."""
    class FastService:
        async def process_url(self, completion_callback, **kwargs):
            completion_callback()
            return SimpleNamespace(id="document", status="queued")

    client = url_ingest_client(
        monkeypatch,
        FastService(),
        request_limiter=SlidingWindowRateLimiter(),
    )

    responses = [
        client.post(
            "/api/projects/project/upload-url",
            json={"url": "https://example.com/%s" % index},
        )
        for index in range(11)
    ]

    assert [response.status_code for response in responses[:10]] == [200] * 10
    assert responses[-1].status_code == 429
    assert responses[-1].headers["Retry-After"] == "60"


def test_third_concurrent_ingestion_for_one_account_returns_429(monkeypatch):
    """A third active import cannot consume another worker slot."""
    started = Event()
    release = Event()
    lock = Lock()
    active = 0

    class BlockingService:
        async def process_url(self, completion_callback, **kwargs):
            nonlocal active
            with lock:
                active += 1
                if active == 2:
                    started.set()
            await asyncio.get_running_loop().run_in_executor(
                None, release.wait, 5
            )
            with lock:
                active -= 1
            completion_callback()
            return SimpleNamespace(id="document", status="queued")

    client = url_ingest_client(monkeypatch, BlockingService())
    path = "/api/projects/project/upload-url"
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(client.post, path, json={"url": "https://example.com/1"})
        second = executor.submit(client.post, path, json={"url": "https://example.com/2"})
        assert started.wait(timeout=5), "two ingestion operations never became active"

        third = client.post(path, json={"url": "https://example.com/3"})
        release.set()

        assert first.result(timeout=5).status_code == 200
        assert second.result(timeout=5).status_code == 200

    assert third.status_code == 429
    assert third.headers["Retry-After"] == "1"


def test_background_ingestion_keeps_its_slot_after_response(monkeypatch):
    """Queued extraction/indexing stays active after the upload response."""
    completions = []

    class DeferredService:
        async def process_url(self, completion_callback, **kwargs):
            completions.append(completion_callback)
            return SimpleNamespace(id="document", status="queued")

    client = url_ingest_client(monkeypatch, DeferredService())
    path = "/api/projects/project/upload-url"

    first = client.post(path, json={"url": "https://example.com/1"})
    second = client.post(path, json={"url": "https://example.com/2"})
    third = client.post(path, json={"url": "https://example.com/3"})

    assert first.status_code == second.status_code == 200
    assert third.status_code == 429
    assert len(completions) == 2

    for complete in completions:
        complete()

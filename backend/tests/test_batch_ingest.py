"""Behavior tests for multi-URL and YouTube playlist ingestion."""
import importlib
import importlib.util
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.db.database import get_db
from app.routers import ingest
from app.routers.auth import get_current_user
from app.routers.rate_limit import get_concurrency_limiter, get_rate_limiter
from app.services import batch_ingestion
from app.services.rate_limit import ConcurrencyLimiter, SlidingWindowRateLimiter
from app.utils.network import UnsafeURLError


def batch_client(monkeypatch, service, request_limiter=None, concurrency=None):
    app = FastAPI()
    app.include_router(ingest.router, prefix="/api")
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="user")
    app.dependency_overrides[get_db] = lambda: object()
    app.dependency_overrides[get_rate_limiter] = lambda: request_limiter or SlidingWindowRateLimiter(enabled=False)
    app.dependency_overrides[get_concurrency_limiter] = lambda: concurrency or ConcurrencyLimiter()
    app.dependency_overrides[ingest.get_document_service] = lambda: service
    monkeypatch.setattr(ingest, "require_project", lambda *args, **kwargs: object())
    return TestClient(app)


def test_batch_import_reports_bad_urls_and_keeps_importing_valid_ones(monkeypatch):
    created = []

    class DocumentService:
        async def process_url(self, url, operation_lease, **kwargs):
            created.append(url)
            operation_lease.release()
            return SimpleNamespace(id="doc-%d" % len(created), status="queued")

        async def process_youtube(self, youtube_url, operation_lease, **kwargs):
            raise AssertionError("website URL was misclassified as YouTube")

    def validate(url):
        if "127.0.0.1" in url:
            raise UnsafeURLError("URL destination must be globally routable")
        return url

    monkeypatch.setattr(batch_ingestion, "validate_public_http_url", validate)
    client = batch_client(monkeypatch, DocumentService())

    response = client.post("/api/projects/project/upload-batch", json={"urls": [
        "https://one.example/page",
        "http://127.0.0.1/admin",
        "https://two.example/page",
    ]})

    assert response.status_code == 200
    assert created == ["https://one.example/page", "https://two.example/page"]
    assert [document["doc_id"] for document in response.json()["documents"]] == [
        "doc-1", "doc-2",
    ]
    assert response.json()["failures"] == [{
        "url": "http://127.0.0.1/admin",
        "message": "URL destination must be globally routable",
    }]


def test_batch_import_validates_each_expanded_playlist_video(monkeypatch):
    created = []
    validated = []
    videos = [
        {"url": "https://www.youtube.com/watch?v=one", "title": "One"},
        {"url": "http://127.0.0.1/admin", "title": "Unsafe"},
        {"url": "https://www.youtube.com/watch?v=two", "title": "Two"},
    ]

    class DocumentService:
        async def process_url(self, **kwargs):
            raise AssertionError("playlist entry was misclassified as a website")

        async def process_youtube(self, youtube_url, title, operation_lease, **kwargs):
            created.append((youtube_url, title))
            operation_lease.release()
            return SimpleNamespace(id="doc-%d" % len(created), status="queued")

    def validate(url):
        validated.append(url)
        if "127.0.0.1" in url:
            raise UnsafeURLError("URL destination must be globally routable")
        return url

    monkeypatch.setattr(batch_ingestion, "validate_public_http_url", validate)
    monkeypatch.setattr(
        batch_ingestion,
        "expand_youtube_playlist",
        lambda _url: (videos, False),
    )
    monkeypatch.setattr(ingest.settings, "enable_yt_transcription", True)
    client = batch_client(monkeypatch, DocumentService())

    response = client.post("/api/projects/project/upload-batch", json={
        "urls": ["https://www.youtube.com/playlist?list=PL123"],
    })

    assert response.status_code == 200
    assert created == [
        ("https://www.youtube.com/watch?v=one", "One"),
        ("https://www.youtube.com/watch?v=two", "Two"),
    ]
    assert "http://127.0.0.1/admin" in validated
    assert response.json()["failures"] == [{
        "url": "http://127.0.0.1/admin",
        "message": "URL destination must be globally routable",
    }]


def test_batch_source_cap_reports_urls_that_were_not_queued(monkeypatch):
    videos = [
        {"url": "https://www.youtube.com/watch?v=video-%d" % index, "title": None}
        for index in range(50)
    ]
    queued = []

    class DocumentService:
        async def process_youtube(self, youtube_url, operation_lease, **kwargs):
            queued.append(youtube_url)
            operation_lease.release()
            return SimpleNamespace(id="doc-%d" % len(queued), status="queued")

        async def process_url(self, **kwargs):
            raise AssertionError("URL after the source cap should not be queued")

    monkeypatch.setattr(batch_ingestion, "validate_public_http_url", lambda url: url)
    monkeypatch.setattr(
        batch_ingestion,
        "expand_youtube_playlist",
        lambda _url: (videos, False),
    )
    monkeypatch.setattr(ingest.settings, "rate_limit_enabled", False)
    monkeypatch.setattr(ingest.settings, "enable_yt_transcription", True)
    client = batch_client(monkeypatch, DocumentService())

    response = client.post("/api/projects/project/upload-batch", json={
        "urls": [
            "https://www.youtube.com/playlist?list=PL123",
            "https://example.com/left-for-retry",
        ],
    })

    assert response.status_code == 200
    assert len(queued) == 50
    assert len(response.json()["documents"]) == 50
    assert response.json()["failures"] == [{
        "url": "https://example.com/left-for-retry",
        "message": "Batch limit of 50 sources reached",
    }]
    assert response.json()["truncated"] is True


def test_rate_limit_is_applied_per_batch_source_but_concurrency_per_batch(monkeypatch):
    limiter = ConcurrencyLimiter(max_concurrent=2)
    active_during_enqueue = []

    class DocumentService:
        async def process_url(self, url, operation_lease, **kwargs):
            active_during_enqueue.append(limiter.active("ingest:user"))
            operation_lease.release()
            return SimpleNamespace(id=url.rsplit("/", 1)[-1], status="queued")

    monkeypatch.setattr(batch_ingestion, "validate_public_http_url", lambda url: url)
    monkeypatch.setattr(ingest.settings, "rate_limit_enabled", True)
    client = batch_client(
        monkeypatch,
        DocumentService(),
        request_limiter=SlidingWindowRateLimiter(),
        concurrency=limiter,
    )

    response = client.post("/api/projects/project/upload-batch", json={
        "urls": ["https://example.com/%d" % index for index in range(11)],
    })

    assert response.status_code == 200
    assert len(response.json()["documents"]) == 10
    assert response.json()["failures"] == [{
        "url": "https://example.com/10",
        "message": "Too many requests",
    }]
    assert active_during_enqueue == [1] * 10
    assert limiter.active("ingest:user") == 0


def test_playlist_expansion_caps_entries_and_reports_truncation():
    module_spec = importlib.util.find_spec("app.services.youtube_playlist")
    if module_spec is None:
        pytest.fail("YouTube playlist expansion is not implemented", pytrace=False)
    playlist_service = importlib.import_module("app.services.youtube_playlist")
    observed_options = {}

    class Downloader:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def extract_info(self, url, download):
            assert url == "https://www.youtube.com/playlist?list=PL123"
            assert download is False
            return {
                "_type": "playlist",
                "entries": [
                    {"id": "video-%d" % index, "title": "Video %d" % index}
                    for index in range(51)
                ],
            }

    def factory(options):
        observed_options.update(options)
        return Downloader()

    videos, truncated = playlist_service.expand_youtube_playlist(
        "https://www.youtube.com/playlist?list=PL123",
        youtube_dl_factory=factory,
    )

    assert len(videos) == 50
    assert videos[0] == {
        "url": "https://www.youtube.com/watch?v=video-0",
        "title": "Video 0",
    }
    assert videos[-1] == {
        "url": "https://www.youtube.com/watch?v=video-49",
        "title": "Video 49",
    }
    assert observed_options["playlistend"] == 51
    assert observed_options["extract_flat"] == "in_playlist"
    assert truncated is True

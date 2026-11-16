"""The retrieval models load at start-up, not on the first question (#242)."""
import sys
import threading
from types import ModuleType

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import lifecycle
from app.config import get_settings
from app.db.models import Base
from app.services.auth import get_auth_service


def test_warm_up_builds_the_service_the_routes_reuse(monkeypatch):
    """The first question gets the instance the warm-up already built."""
    created = []

    class FakeRAGService:
        def __init__(self):
            created.append(self)

    rag_module = ModuleType("app.services.rag")
    rag_module.RAGService = FakeRAGService
    monkeypatch.setitem(sys.modules, "app.services.rag", rag_module)
    from app.routers.query import get_rag_service

    get_rag_service.cache_clear()
    try:
        lifecycle.warm_retrieval(FastAPI())

        assert len(created) == 1
        assert get_rag_service() is created[0]
    finally:
        get_rag_service.cache_clear()


def test_warm_up_uses_an_overriding_service():
    """The E2E server swaps in a deterministic service; that one is warmed."""
    from app.routers.query import get_rag_service

    app = FastAPI()
    calls = []
    app.dependency_overrides[get_rag_service] = lambda: calls.append("override")

    lifecycle.warm_retrieval(app)

    assert calls == ["override"]


def test_a_failed_warm_up_does_not_raise():
    """A model that cannot load is retried, and reported, by the first question."""
    from app.routers.query import get_rag_service

    def unavailable():
        raise OSError("model files are missing")

    app = FastAPI()
    app.dependency_overrides[get_rag_service] = unavailable

    assert lifecycle.warm_retrieval(app) is None


def test_startup_does_not_wait_for_the_warm_up(monkeypatch, tmp_path):
    """Readiness stays immediate while the models are still loading."""
    engine = create_engine(
        f"sqlite:///{tmp_path / 'warmup.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    sessions = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    release = threading.Event()
    started = threading.Event()

    def slow_warm_up(app):
        started.set()
        release.wait(timeout=10)

    monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-key-for-lifespan")
    monkeypatch.setattr(lifecycle, "SessionLocal", sessions)
    monkeypatch.setattr(lifecycle, "init_db", lambda: None)
    monkeypatch.setattr(lifecycle, "warm_retrieval", slow_warm_up)
    get_settings.cache_clear()
    get_auth_service.cache_clear()
    try:
        with TestClient(FastAPI(lifespan=lifecycle.lifespan)):
            assert started.wait(timeout=5)
            assert not release.is_set()
    finally:
        release.set()
        get_auth_service.cache_clear()
        get_settings.cache_clear()


def test_concurrent_constructions_load_the_embedding_model_once(monkeypatch):
    """A question during the warm-up waits for that load instead of starting another."""
    from app.services import embeddings

    loads = []
    both_waiting = threading.Barrier(2)

    def slow_load(self):
        loads.append(self)
        threading.Event().wait(0.2)
        embeddings.EmbeddingService._model = object()

    monkeypatch.setattr(embeddings.EmbeddingService, "_model", None)
    monkeypatch.setattr(embeddings.EmbeddingService, "_initialize_model", slow_load)

    def construct():
        both_waiting.wait(timeout=5)
        embeddings.EmbeddingService()

    threads = [threading.Thread(target=construct) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert len(loads) == 1

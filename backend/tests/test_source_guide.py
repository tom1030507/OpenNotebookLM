"""The source guide route returns and caches a guide for ready documents."""
import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import get_db
from app.db.models import Base, Document
from app.routers import ingest
from app.services.llm import FALLBACK_MODEL, LLMService
from app.services.source_digest import extractive_source_guide, invalidate_source_guide
from app.services.source_guide import SourceGuideService
from conftest import authenticated_client, owner_id


SOURCE_TEXT = (
    "The observatory checks telescope equipment each night. "
    "Operators record the weather and exposure settings. "
    "The archive keeps a backup of every image."
)


@pytest.fixture
def env(monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    app = FastAPI()
    app.include_router(ingest.router, prefix="/api")
    app.dependency_overrides[get_db] = lambda: session
    monkeypatch.setattr(
        LLMService,
        "generate",
        lambda self, prompt, **kwargs: {
            "text": "No provider is configured.",
            "model": FALLBACK_MODEL,
            "usage": {},
        },
    )
    client = authenticated_client(app, session)
    try:
        yield client, session
    finally:
        client.close()
        session.close()
        engine.dispose()


def add_document(session, status="ready", content=SOURCE_TEXT, meta_json=None):
    document = Document(
        id="source-1",
        user_id=owner_id(session),
        title="Observatory handbook",
        source_type="text",
        content=content,
        status=status,
        meta_json=meta_json or {},
    )
    session.add(document)
    session.commit()
    return document


def test_ready_source_guide_is_returned_and_cached(env):
    client, session = env
    document = add_document(session)

    first = client.get("/api/docs/source-1/guide")
    second = client.get("/api/docs/source-1/guide")

    assert first.status_code == 200, first.text
    assert first.json() == second.json() == extractive_source_guide(document)
    assert "guide" in document.meta_json


def test_source_guide_requires_a_ready_document(env):
    client, session = env
    document = add_document(session, status="processing")

    response = client.get("/api/docs/source-1/guide")

    assert response.status_code == 409
    assert "guide" not in (document.meta_json or {})


def test_short_extractive_guide_is_cached_between_views(env, monkeypatch):
    client, session = env
    add_document(
        session,
        content="短文介紹設備檢查，還有觀測記錄。",
    )
    calls = []

    def unavailable_model(self, prompt, **kwargs):
        calls.append(prompt)
        return {"text": "No provider is configured.", "model": FALLBACK_MODEL}

    monkeypatch.setattr(LLMService, "generate", unavailable_model)

    first = client.get("/api/docs/source-1/guide")
    second = client.get("/api/docs/source-1/guide")

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert len(calls) == 1


def test_generation_does_not_restore_a_guide_invalidated_concurrently():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    reader = factory()
    writer = factory()
    document = Document(
        id="racing-source",
        user_id=None,
        title="Observatory handbook",
        source_type="text",
        content=SOURCE_TEXT,
        status="ready",
        meta_json={
            "processed_at": "old",
            "guide": {
                "title": "Older title",
                "summary": "Old summary. More old summary.",
                "topics": ["old one", "old two", "old three"],
            },
        },
    )
    reader.add(document)
    reader.commit()

    class ConcurrentInvalidationLLM:
        def generate(self, prompt, **kwargs):
            current = writer.get(Document, "racing-source")
            current.meta_json = {**current.meta_json, "processed_at": "new"}
            invalidate_source_guide(current)
            writer.commit()
            return {
                "text": json.dumps({
                    "summary": "The observatory checks equipment. Staff record conditions.",
                    "topics": ["Equipment", "Observations", "Image backups"],
                }),
                "model": "test-model",
            }

    try:
        SourceGuideService(ConcurrentInvalidationLLM()).guide(reader, document)
        latest = writer.get(Document, "racing-source")

        assert latest.meta_json["processed_at"] == "new"
        assert "guide" not in latest.meta_json
    finally:
        reader.close()
        writer.close()
        engine.dispose()

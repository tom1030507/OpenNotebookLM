"""Tests for the deterministic E2E service boundary."""
import math
import pickle
from pathlib import Path

import numpy as np
import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import Base, Chunk, Document, Embedding
from app.routers.ingest import get_document_service
from app.routers.query import get_rag_service
from scripts.e2e_server import install_fast_overrides, resolve_runtime_root
from scripts.e2e_services import (
    DeterministicEmbeddingService,
    FixedURLAdapter,
    FixedYouTubeAdapter,
)


@pytest.fixture
def db():
    """Create a disposable SQLite session.

    Args:
        None.

    Returns:
        A yielded SQLAlchemy session whose engine is disposed afterward.
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(autocommit=False, autoflush=False, bind=engine)()
    yield session
    session.close()
    engine.dispose()


def test_deterministic_embedding_is_stable_normalized_and_token_sensitive():
    """The same searchable terms must produce a stable cosine signal."""
    service = DeterministicEmbeddingService(dimensions=256)
    passage = service.generate_embedding("observatory access code ORBIT-7319")
    repeated = service.generate_embedding("observatory access code ORBIT-7319")
    related = service.generate_embedding(
        "What is the ORBIT-7319 access code?", role="query"
    )
    unrelated = service.generate_embedding("banana orchard rainfall", role="query")

    assert passage.dtype == np.float32
    assert np.array_equal(passage, repeated)
    assert math.isclose(float(np.linalg.norm(passage)), 1.0, rel_tol=1e-6)
    assert float(np.dot(passage, related)) > float(np.dot(passage, unrelated))


def test_fixed_url_adapter_returns_production_shape():
    """The URL fake must feed the real document lifecycle without branches."""
    result = FixedURLAdapter().extract_content("https://e2e.invalid/observatory")

    assert result["url"] == "https://e2e.invalid/observatory"
    assert result["title"] == "E2E Observatory Field Notes"
    assert "ORBIT-7319" in result["text"]
    assert result["headings"]
    assert result["links"] == []


def test_fixed_youtube_adapter_returns_production_shape():
    """The transcript fake must preserve timing and metadata fields."""
    result = FixedYouTubeAdapter().extract_transcript(
        "https://www.youtube.com/watch?v=e2eOrbit7319"
    )

    assert result["video_id"] == "e2eOrbit7319"
    assert result["language"] == "en"
    assert result["duration"] == 42.0
    assert result["segments"][0]["start"] == 0.0
    assert result["segments"][0]["end"] == 12.0
    assert result["segments"][1]["end"] == 42.0
    assert "ORBIT-7319" in result["text"]


def test_chunk_embeddings_persist_and_search_with_production_payload(db):
    """Stored deterministic vectors must drive scoped dense retrieval."""
    document = Document(
        id="document-1",
        title="Observatory Notes",
        source_type="url",
        status="processing",
        meta_json={},
    )
    relevant = Chunk(
        id="chunk-orbit",
        document_id=document.id,
        text="The observatory access code is ORBIT-7319.",
        start_offset=0,
        end_offset=43,
        heading_path="Observatory Operations",
        meta_json={"section": "Operations"},
    )
    unrelated = Chunk(
        id="chunk-weather",
        document_id=document.id,
        text="Banana orchard rainfall is measured each morning.",
        start_offset=44,
        end_offset=94,
        meta_json={},
    )
    db.add_all([document, relevant, unrelated])
    db.commit()
    service = DeterministicEmbeddingService()

    records = service.embed_chunks(db, document.id)

    assert len(records) == 2
    assert {record.model_name for record in records} == {"e2e-token-hash-v1"}
    assert all(pickle.loads(record.vector).dtype == np.float32 for record in records)
    assert all(len(record.vector_json) == 256 for record in records)
    results = service.search_similar_chunks(
        db,
        query="ORBIT-7319 access code",
        document_ids=[document.id],
        top_k=2,
        threshold=-1.0,
    )
    assert results[0]["chunk_id"] == relevant.id
    assert set(results[0]) == {
        "chunk_id",
        "document_id",
        "document_title",
        "text",
        "score",
        "metadata",
    }
    assert results[0]["metadata"] == {
        "page_num": None,
        "timestamp": None,
        "section": "Operations",
        "heading_path": "Observatory Operations",
    }
    assert service.search_similar_chunks(db, "ORBIT-7319", document_ids=[]) == []


def test_runtime_root_accepts_only_a_named_child(tmp_path):
    """A run directory beneath output/e2e is the only valid target."""
    repo = tmp_path / "repo"
    accepted = repo / "output" / "e2e" / "run-123"

    assert resolve_runtime_root(str(accepted), repo) == accepted.resolve()


@pytest.mark.parametrize(
    "relative", [".", "output", "output/e2e", "data", "uploads", "../outside"]
)
def test_runtime_root_rejects_broad_or_escaped_paths(tmp_path, relative):
    """Broad and escaped paths must never become E2E cleanup targets."""
    repo = tmp_path / "repo"

    with pytest.raises(ValueError, match="runtime root"):
        resolve_runtime_root(str(repo / relative), repo)


def test_fast_overrides_select_the_deterministic_service_graph():
    """FastAPI overrides must replace both production embedding boundaries."""
    application = FastAPI()

    install_fast_overrides(application)

    document_service = application.dependency_overrides[get_document_service]()
    rag_service = application.dependency_overrides[get_rag_service]()
    assert isinstance(
        document_service.embedding_service, DeterministicEmbeddingService
    )
    assert document_service.embedding_service is rag_service.embedding_service
    assert isinstance(document_service.url_adapter, FixedURLAdapter)
    assert isinstance(document_service.youtube_adapter, FixedYouTubeAdapter)

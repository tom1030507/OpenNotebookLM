"""Atomic source-vector refresh behavior for document renames."""
from __future__ import annotations

import numpy as np
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import Base, Chunk, Document, Embedding
from app.services import embeddings as embeddings_module
from app.services.embeddings import EmbeddingService


class MemoryRetrievalIndex:
    """Keep a minimal searchable view for observing refresh publication."""

    def __init__(self):
        self.entries = {
            "chunk-1": {
                "document_id": "document-1",
                "vector": np.array([1.0, 0.0], dtype=np.float32),
                "text": "Source passage",
            },
        }
        self.delete_calls = []

    def delete_document(self, _db, document_id):
        """Remove indexed rows belonging to one document."""
        self.delete_calls.append(document_id)
        self.entries = {
            chunk_id: entry
            for chunk_id, entry in self.entries.items()
            if entry["document_id"] != document_id
        }

    def upsert_chunks(self, _db, chunks):
        """Publish replacement chunk vectors as one in-memory transaction."""
        for chunk in chunks:
            self.entries[chunk.chunk_id] = {
                "document_id": chunk.document_id,
                "vector": chunk.vector.copy(),
                "text": chunk.text,
            }


@pytest.fixture
def reindex_db():
    """Create a ready source with an existing searchable embedding."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(
        bind=engine,
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
    )()
    db.add(Document(
        id="document-1",
        title="New source title",
        source_type="text",
        content="Source passage",
        status="ready",
        meta_json={},
    ))
    db.add(Chunk(
        id="chunk-1",
        document_id="document-1",
        text="Source passage",
        start_offset=0,
        end_offset=15,
        heading_path="Methods",
        meta_json={},
    ))
    db.add(Embedding(
        id="embedding-1",
        chunk_id="chunk-1",
        vector=b"old-vector",
        vector_json=[1.0, 0.0],
        model_name="test-model",
    ))
    db.commit()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


def configure_embedding_service(monkeypatch, index, generate):
    """Build a service with deterministic encoding and a searchable index.

    Args:
        monkeypatch: Pytest fixture for replacing model and index boundaries.
        index: In-memory retrieval-index double.
        generate: Deterministic or failing embedding function.

    Returns:
        An embedding service that uses the supplied test doubles.
    """
    service = object.__new__(EmbeddingService)
    monkeypatch.setattr(service, "generate_embedding", generate)
    monkeypatch.setattr(
        embeddings_module,
        "get_retrieval_index",
        lambda: index,
    )
    monkeypatch.setattr(
        embeddings_module,
        "get_settings",
        lambda: type("Settings", (), {"emb_model_name": "test-model"})(),
    )
    return service


def test_force_regenerate_keeps_existing_vector_until_new_one_publishes(
    reindex_db,
    monkeypatch,
):
    """Re-indexing reads the new title before atomically replacing old vectors."""
    index = MemoryRetrievalIndex()
    observed_inputs = []

    def generate(texts, **_kwargs):
        observed_inputs.extend(texts)
        existing = reindex_db.get(Embedding, "embedding-1")
        assert existing.vector_json == [1.0, 0.0]
        assert index.entries["chunk-1"]["vector"].tolist() == [1.0, 0.0]
        assert index.delete_calls == []
        return np.array([[0.0, 1.0]], dtype=np.float32)

    service = configure_embedding_service(monkeypatch, index, generate)

    records = service.embed_chunks(
        reindex_db,
        "document-1",
        force_regenerate=True,
    )

    assert observed_inputs == [
        "New source title > Methods\n\nSource passage"
    ]
    assert len(records) == 1
    replacement = reindex_db.get(Embedding, "embedding-1")
    assert replacement.vector_json == [0.0, 1.0]
    assert index.entries["chunk-1"]["vector"].tolist() == [0.0, 1.0]
    assert index.delete_calls == []


def test_force_regenerate_failure_preserves_existing_embedding_and_index(
    reindex_db,
    monkeypatch,
):
    """An encoder error cannot commit removal of the last searchable vector."""
    index = MemoryRetrievalIndex()

    def fail_to_generate(_texts, **_kwargs):
        raise RuntimeError("encoder unavailable")

    service = configure_embedding_service(
        monkeypatch,
        index,
        fail_to_generate,
    )

    with pytest.raises(RuntimeError, match="encoder unavailable"):
        service.embed_chunks(
            reindex_db,
            "document-1",
            force_regenerate=True,
        )

    existing = reindex_db.get(Embedding, "embedding-1")
    assert existing.vector_json == [1.0, 0.0]
    assert index.entries["chunk-1"]["vector"].tolist() == [1.0, 0.0]
    assert index.delete_calls == []

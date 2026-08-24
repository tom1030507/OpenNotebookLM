"""Integration contracts between ingestion, RAG, and the retrieval index."""
from __future__ import annotations

import importlib
import pickle
import sys
import types

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import Base, Chunk, Document, Embedding  # noqa: E402
from app.routers import health  # noqa: E402
from app.services import chunking, documents, embeddings, ingestion_jobs  # noqa: E402
from app.services.retrieval_index import (  # noqa: E402
    IndexedChunk,
    RetrievalCandidate,
)


def real_rag_module():
    """Return real RAG code after route tests install their lightweight stub.

    Returns:
        The genuine ``app.services.rag`` module.
    """
    module = sys.modules.get("app.services.rag")
    if (
        module is None
        or not hasattr(module, "RAGService")
        or not hasattr(module.RAGService, "retrieve_with_diagnostics")
    ):
        sys.modules.pop("app.services.rag", None)
        module = importlib.import_module("app.services.rag")
    return module


rag = real_rag_module()


@pytest.fixture
def db():
    """Yield an isolated SQLite session with the application schema."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine, autoflush=False)()
    yield session
    session.close()
    engine.dispose()


class RecordingIndex:
    """Small index double that records lifecycle and retrieval boundaries."""

    def __init__(self):
        self.upserts = []
        self.deletes = []
        self.dense_calls = []
        self.lexical_calls = []
        self.hydrate_calls = []
        self.status_calls = []

    def upsert_chunks(self, db, chunks):
        """Record one transactional chunk batch."""
        self.upserts.append((db, list(chunks)))

    def delete_document(self, db, document_id):
        """Delete shadow rows through the caller's transaction when present."""
        self.deletes.append((db, document_id))
        try:
            result = db.execute(
                text("DELETE FROM test_retrieval_rows WHERE document_id = :id"),
                {"id": document_id},
            )
        except Exception as error:
            if "no such table" not in str(error):
                raise
            return 0
        return result.rowcount

    def dense_search(
        self,
        db,
        query_vector,
        document_ids,
        top_k,
        threshold=0,
    ):
        """Return two ranked dense candidates."""
        self.dense_calls.append(
            (db, np.asarray(query_vector), document_ids, top_k)
        )
        return [
            RetrievalCandidate("chunk-a", "doc-a", 0.9),
            RetrievalCandidate("chunk-b", "doc-a", 0.8),
        ]

    def lexical_search(self, db, query, document_ids, top_k):
        """Return one lexical candidate that overlaps the dense ranking."""
        self.lexical_calls.append((db, query, document_ids, top_k))
        return [RetrievalCandidate("chunk-b", "doc-a", 3.0)]

    def hydrate(self, db, chunk_ids):
        """Return metadata for the bounded union in one operation."""
        self.hydrate_calls.append((db, list(chunk_ids)))
        payloads = {
            "chunk-a": {
                "chunk_id": "chunk-a",
                "document_id": "doc-a",
                "document_title": "Allowed",
                "text": "alpha passage",
                "metadata": {
                    "page_num": None,
                    "timestamp": None,
                    "section": None,
                    "heading_path": None,
                },
            },
            "chunk-b": {
                "chunk_id": "chunk-b",
                "document_id": "doc-a",
                "document_title": "Allowed",
                "text": "beta passage",
                "metadata": {
                    "page_num": None,
                    "timestamp": None,
                    "section": None,
                    "heading_path": None,
                },
            },
        }
        return [payloads[chunk_id] for chunk_id in chunk_ids]

    def status(self, db=None):
        """Return the active backend used for request diagnostics."""
        self.status_calls.append(db)
        return types.SimpleNamespace(
            as_dict=lambda: {"active_dense_backend": "sqlitevec"}
        )


def test_existing_embeddings_backfill_missing_index_rows(db, monkeypatch):
    """A canonical embedding must not skip its missing persistent index row."""
    document = Document(
        id="doc-a",
        title="Document",
        source_type="url",
        status="ready",
        meta_json={},
    )
    chunk = Chunk(
        id="chunk-a",
        document_id=document.id,
        text="indexed passage",
        start_offset=0,
        end_offset=15,
        heading_path="Section",
        meta_json={},
    )
    vector = np.asarray([0.25, 0.75], dtype=np.float32)
    db.add_all(
        [
            document,
            chunk,
            Embedding(
                id="embedding-a",
                chunk_id=chunk.id,
                vector=pickle.dumps(vector),
                vector_json=vector.tolist(),
                model_name="test-model",
            ),
        ]
    )
    db.commit()

    index = RecordingIndex()
    monkeypatch.setattr(embeddings, "get_retrieval_index", lambda: index, raising=False)
    monkeypatch.setattr(embeddings, "IndexedChunk", IndexedChunk, raising=False)
    monkeypatch.setattr(embeddings.EmbeddingService, "_model", object())

    service = embeddings.EmbeddingService()
    records = service.embed_chunks(db, document.id)

    assert [record.id for record in records] == ["embedding-a"]
    assert len(index.upserts) == 1
    indexed = index.upserts[0][1]
    assert [item.chunk_id for item in indexed] == ["chunk-a"]
    np.testing.assert_array_equal(indexed[0].vector, vector)
    assert indexed[0].searchable is True


def test_search_similar_chunks_compatibility_uses_bounded_index(db, monkeypatch):
    """The legacy-shaped API must not deserialize the canonical full table."""
    index = RecordingIndex()
    monkeypatch.setattr(embeddings, "get_retrieval_index", lambda: index)
    service = object.__new__(embeddings.EmbeddingService)
    monkeypatch.setattr(
        service,
        "generate_embedding",
        lambda *args, **kwargs: np.asarray([1.0, 0.0], dtype=np.float32),
    )
    monkeypatch.setattr(
        embeddings.pickle,
        "loads",
        lambda _value: (_ for _ in ()).throw(
            AssertionError("canonical embedding was deserialized")
        ),
    )

    results = service.search_similar_chunks(
        db,
        "alpha",
        document_ids=["doc-a"],
        top_k=2,
        threshold=0.5,
    )

    assert [result["chunk_id"] for result in results] == ["chunk-a", "chunk-b"]
    assert [result["score"] for result in results] == [0.9, 0.8]
    assert len(index.dense_calls) == 1
    assert index.hydrate_calls[0][1] == ["chunk-a", "chunk-b"]


def test_processing_index_is_published_only_with_ready_transition(db, monkeypatch):
    """A closer processing row must remain non-searchable until final commit."""
    document = Document(
        id="doc-processing",
        title="Processing",
        source_type="url",
        status="processing",
        meta_json={},
    )
    chunk = Chunk(
        id="chunk-processing",
        document_id=document.id,
        text="closer but unfinished",
        start_offset=0,
        end_offset=21,
        meta_json={},
    )
    vector = np.asarray([1.0, 0.0], dtype=np.float32)
    db.add_all([
        document,
        chunk,
        Embedding(
            id="embedding-processing",
            chunk_id=chunk.id,
            vector=pickle.dumps(vector),
            vector_json=vector.tolist(),
            model_name="test-model",
        ),
    ])
    db.commit()

    index = RecordingIndex()
    monkeypatch.setattr(embeddings, "get_retrieval_index", lambda: index)
    monkeypatch.setattr(embeddings.EmbeddingService, "_model", object())
    service = embeddings.EmbeddingService()

    service.embed_chunks(db, document.id)
    assert index.upserts[-1][1][0].searchable is False

    document = db.get(Document, document.id)
    document.status = "ready"
    service.publish_document_index(db, document.id)

    assert [call[1][0].searchable for call in index.upserts] == [False, True]


def test_chunk_replacement_deletes_persistent_index_in_same_commit(db, monkeypatch):
    """Replacing canonical chunks must remove vec/FTS rows before commit."""
    document = Document(
        id="doc-replace",
        title="Replacement",
        source_type="text",
        status="processing",
        content="A replacement passage with enough content to be indexed.",
        meta_json={},
    )
    db.add(document)
    db.add(Chunk(
        id="old-chunk",
        document_id=document.id,
        text="stale passage",
        start_offset=0,
        end_offset=13,
        meta_json={},
    ))
    db.commit()
    index = RecordingIndex()
    monkeypatch.setattr(chunking, "get_retrieval_index", lambda: index, raising=False)

    chunking.ChunkingService(chunk_size=200, chunk_overlap=0).chunk_document(
        db,
        document.id,
    )

    assert [(call[1]) for call in index.deletes] == [document.id]


def test_empty_replacement_removes_the_previous_searchable_index(db, monkeypatch):
    """An empty retry must not republish chunks from an older extraction."""
    document = Document(
        id="doc-empty-retry",
        title="Empty retry",
        source_type="text",
        status="processing",
        content="",
        meta_json={},
    )
    db.add(document)
    db.add(Chunk(
        id="old-empty-chunk",
        document_id=document.id,
        text="stale extraction",
        start_offset=0,
        end_offset=16,
        meta_json={},
    ))
    db.commit()
    index = RecordingIndex()
    monkeypatch.setattr(chunking, "get_retrieval_index", lambda: index, raising=False)

    result = chunking.ChunkingService().chunk_document(db, document.id)

    assert result == []
    assert [call[1] for call in index.deletes] == [document.id]
    assert db.query(Chunk).filter(Chunk.document_id == document.id).count() == 0


def test_failed_document_deletes_shadow_index_with_error_status(db, monkeypatch):
    """Failure status and stale-index removal must commit atomically."""
    document = Document(
        id="doc-failed",
        title="Failed",
        source_type="url",
        status="processing",
        meta_json={},
    )
    db.add(document)
    db.execute(text(
        "CREATE TABLE test_retrieval_rows "
        "(document_id TEXT NOT NULL, chunk_id TEXT NOT NULL)"
    ))
    db.execute(
        text("INSERT INTO test_retrieval_rows VALUES (:document_id, :chunk_id)"),
        {"document_id": document.id, "chunk_id": "stale"},
    )
    db.commit()
    index = RecordingIndex()
    monkeypatch.setattr(documents, "get_retrieval_index", lambda: index, raising=False)
    service = object.__new__(documents.DocumentService)

    status = service._mark_failed(db, document.id, "index failed")

    assert status == "error"
    assert db.get(Document, document.id).status == "error"
    assert db.execute(text("SELECT COUNT(*) FROM test_retrieval_rows")).scalar() == 0


def test_worker_index_cleanup_rolls_back_with_canonical_chunks(db, monkeypatch):
    """A worker rollback must restore both canonical and retrieval rows."""
    document = Document(
        id="doc-worker",
        title="Worker",
        source_type="url",
        status="processing",
        meta_json={},
    )
    db.add(document)
    db.add(Chunk(
        id="worker-chunk",
        document_id=document.id,
        text="worker passage",
        start_offset=0,
        end_offset=14,
        meta_json={},
    ))
    db.execute(text(
        "CREATE TABLE test_retrieval_rows "
        "(document_id TEXT NOT NULL, chunk_id TEXT NOT NULL)"
    ))
    db.execute(
        text("INSERT INTO test_retrieval_rows VALUES (:document_id, :chunk_id)"),
        {"document_id": document.id, "chunk_id": "worker-chunk"},
    )
    db.commit()
    index = RecordingIndex()
    monkeypatch.setattr(
        ingestion_jobs,
        "get_retrieval_index",
        lambda: index,
        raising=False,
    )

    ingestion_jobs.IngestionJobWorker._delete_document_index(db, document.id)
    assert [call[1] for call in index.deletes] == [document.id]
    db.rollback()

    assert db.get(Chunk, "worker-chunk") is not None
    assert db.execute(text("SELECT COUNT(*) FROM test_retrieval_rows")).scalar() == 1


class QueryEmbeddingService:
    """Embedding double that forbids the legacy full-scan path."""

    def __init__(self):
        self.generate_calls = []

    def generate_embedding(self, text, **kwargs):
        """Return one deterministic query vector."""
        self.generate_calls.append((text, kwargs))
        return np.asarray([1.0, 0.0], dtype=np.float32)

    def search_similar_chunks(self, *args, **kwargs):
        """Fail if normal retrieval still enters the compatibility scan."""
        raise AssertionError("normal retrieval used the legacy embedding scan")


def test_rag_generates_one_vector_and_hydrates_only_candidate_union(monkeypatch):
    """Normal RAG must do bounded indexed retrieval with request-local stats."""
    index = RecordingIndex()
    monkeypatch.setattr(rag, "get_retrieval_index", lambda: index, raising=False)
    service = object.__new__(rag.RAGService)
    service.embedding_service = QueryEmbeddingService()

    chunks, diagnostics = service.retrieve_with_diagnostics(
        db=object(),
        query="alpha",
        top_k=2,
        allowed_document_ids=["doc-a"],
    )

    assert len(service.embedding_service.generate_calls) == 1
    assert len(index.dense_calls) == 1
    assert len(index.lexical_calls) == 1
    assert index.dense_calls[0][2] == ["doc-a"]
    assert index.lexical_calls[0][2] == ["doc-a"]
    assert index.hydrate_calls[0][1] == ["chunk-a", "chunk-b"]
    assert index.status_calls == [None]
    assert [chunk["chunk_id"] for chunk in chunks] == ["chunk-b", "chunk-a"]
    assert set(diagnostics) == {
        "dense_candidates",
        "lexical_candidates",
        "fused_candidates",
        "latency_ms",
        "active_backend",
    }
    assert diagnostics["dense_candidates"] == 2
    assert diagnostics["lexical_candidates"] == 1
    assert diagnostics["fused_candidates"] == 2
    assert diagnostics["active_backend"] == "sqlitevec"
    assert diagnostics["latency_ms"] >= 0


def test_health_normalizes_retrieval_status_without_loading_embedding_model(
    monkeypatch,
):
    """Liveness must expose index selection from a dataclass-like status."""
    status_payload = {
        "requested_backend": "sqlitevec+fts5",
        "configured_backend": "sqlitevec+fts5",
        "active_backend": "sqlitevec+fts5",
        "dense_backend": "sqlitevec",
        "lexical_backend": "fts5",
        "dense_available": True,
        "lexical_available": True,
        "sqlitevec_version": "0.1.9",
        "fallback_reason": None,
    }
    index = types.SimpleNamespace(
        status=lambda: types.SimpleNamespace(as_dict=lambda: status_payload)
    )
    monkeypatch.setattr(health, "get_retrieval_index", lambda: index, raising=False)

    app = FastAPI()
    app.include_router(health.router)
    response = TestClient(app).get("/healthz")

    assert response.status_code == 200
    assert response.json()["retrieval"] == status_payload

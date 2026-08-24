"""Resource-ceiling tests for document indexing."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import Base, Chunk, Document, Embedding
from app.services.documents import DocumentService


DOCUMENT_ID = "document-1"
LIMIT_MESSAGE = (
    "Document produced 1001 chunks, exceeding the limit of 1000. "
    "Reduce the source size or increase CHUNK_SIZE before retrying."
)


class CommittingChunker:
    """Mimic the real chunker's commit before returning created rows."""

    def __init__(self, count: int):
        self.count = count

    def chunk_document(self, db, document_id: str) -> list[Chunk]:
        for existing in db.query(Chunk).filter(Chunk.document_id == document_id).all():
            db.delete(existing)
        db.flush()
        chunks = [
            Chunk(
                id=f"chunk-{index}",
                document_id=document_id,
                text=f"chunk {index}",
                start_offset=index,
                end_offset=index + 1,
                meta_json={},
            )
            for index in range(self.count)
        ]
        db.add_all(chunks)
        db.commit()
        return chunks


class RecordingEmbedder:
    """Persist one embedding per chunk and record whether it was invoked."""

    def __init__(self):
        self.calls = 0

    def embed_chunks(self, db, document_id: str) -> list[Embedding]:
        self.calls += 1
        chunks = db.query(Chunk).filter(Chunk.document_id == document_id).all()
        embeddings = [
            Embedding(
                id=f"embedding-{index}",
                chunk_id=chunk.id,
                vector_json=[0.1, 0.2],
                model_name="fake",
            )
            for index, chunk in enumerate(chunks)
        ]
        db.add_all(embeddings)
        db.commit()
        return embeddings


@pytest.fixture
def db():
    """Return a database containing one processing document."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session = sessionmaker(autocommit=False, autoflush=False, bind=engine)()
    Base.metadata.create_all(bind=engine)
    session.add(Document(
        id=DOCUMENT_ID,
        title="Large source",
        source_type="url",
        content="body",
        status="processing",
        meta_json={"source": "kept"},
    ))
    session.commit()

    yield session

    session.close()
    engine.dispose()


def test_exactly_one_thousand_chunks_are_embedded_and_ready(db) -> None:
    """Changing the comparison from ``>`` to ``>=`` would reject the limit."""
    embedder = RecordingEmbedder()
    service = DocumentService(
        chunking_service=CommittingChunker(1_000),
        embedding_service=embedder,
    )

    try:
        status = service._index_document(db, DOCUMENT_ID, "URL")
    finally:
        service.executor.shutdown(wait=True)

    db.expire_all()
    document = db.query(Document).filter(Document.id == DOCUMENT_ID).one()
    assert status == document.status == "ready"
    assert embedder.calls == 1
    assert db.query(Chunk).filter(Chunk.document_id == DOCUMENT_ID).count() == 1_000
    assert db.query(Embedding).count() == 1_000


def test_one_thousand_and_one_chunks_fail_before_embedding_and_are_removed(db) -> None:
    """Committed over-limit chunks cannot survive or reach embedding/cache writes."""
    embedder = RecordingEmbedder()
    service = DocumentService(
        chunking_service=CommittingChunker(1_001),
        embedding_service=embedder,
    )

    try:
        status = service._index_document(db, DOCUMENT_ID, "URL")
    finally:
        service.executor.shutdown(wait=True)

    db.expire_all()
    document = db.query(Document).filter(Document.id == DOCUMENT_ID).one()
    assert status == document.status == "error"
    assert document.error_message == LIMIT_MESSAGE
    assert document.meta_json == {
        "source": "kept",
        "indexing_failure": {
            "code": "chunk_limit_exceeded",
            "chunk_count": 1_001,
            "max_chunks": 1_000,
            "action": "Reduce the source size or increase CHUNK_SIZE before retrying.",
        },
    }
    assert embedder.calls == 0
    assert db.query(Chunk).filter(Chunk.document_id == DOCUMENT_ID).count() == 0
    assert db.query(Embedding).count() == 0

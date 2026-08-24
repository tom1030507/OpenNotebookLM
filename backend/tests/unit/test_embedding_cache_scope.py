"""Document-scoped coverage for the production passage embedding cache path."""
from __future__ import annotations

import numpy as np
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import Base, Chunk, Document
from app.services import embeddings as embeddings_module
from app.services.cache import CacheService
from app.services.embeddings import EmbeddingService


class RecordingModel:
    """Return deterministic vectors and count actual encoder batches."""

    def __init__(self) -> None:
        self.calls: list[object] = []

    def encode(self, texts, **_kwargs):
        """Encode one string or batch while recording the uncached work.

        Args:
            texts: One string or a batch of strings.
            **_kwargs: SentenceTransformer options ignored by this fake.

        Returns:
            One vector or one vector per input string.
        """
        self.calls.append(texts)
        if isinstance(texts, str):
            return np.array([1.0, 2.0], dtype=np.float32)
        return np.array(
            [[float(index + 1), 2.0] for index, _text in enumerate(texts)],
            dtype=np.float32,
        )


@pytest.fixture
def db():
    """Return two documents whose prepared passage text is identical."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session = sessionmaker(autocommit=False, autoflush=False, bind=engine)()
    Base.metadata.create_all(bind=engine)
    for document_id in ("document-one", "document-two"):
        session.add(Document(
            id=document_id,
            title="Same title",
            source_type="url",
            content="Same passage",
            status="processing",
            meta_json={},
        ))
        session.add(Chunk(
            id=f"{document_id}-chunk",
            document_id=document_id,
            text="Same passage",
            start_offset=0,
            end_offset=12,
            heading_path="Same heading",
            meta_json={},
        ))
    session.commit()

    yield session

    session.close()
    engine.dispose()


def test_passage_batches_use_document_scope_and_real_invalidation(
    db,
    monkeypatch,
) -> None:
    """Invalidating one document must make only its real passage entry miss."""
    model = RecordingModel()
    service = object.__new__(EmbeddingService)
    cache = CacheService(
        redis_url=None,
        namespace="embedding-scope-test",
        max_entries=100,
    )
    monkeypatch.setattr(EmbeddingService, "_model", model)
    monkeypatch.setattr(embeddings_module, "cache_service", cache)

    service.embed_chunks(db, "document-one")
    service.embed_chunks(db, "document-two")

    # Identical text owned by a different document must not share an
    # invalidation scope, even though the resulting vectors may be identical.
    assert len(model.calls) == 2

    cache.invalidate_document_cache("document-one")
    service.embed_chunks(db, "document-one", force_regenerate=True)
    assert len(model.calls) == 3

    # The sibling document's version remains reachable after the first
    # document rotates its scope.
    service.embed_chunks(db, "document-two", force_regenerate=True)
    assert len(model.calls) == 3

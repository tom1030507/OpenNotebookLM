"""Tests for the document indexing lifecycle.

``ready`` is the status the UI trusts before it lets anyone query a source, so
it has to mean *retrievable*: the chunks and their embeddings must already
exist when a document starts reporting it. These tests pin that ordering, and
pin what happens when indexing fails or finds nothing to index.
"""
import asyncio
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import Base, Chunk, Document, Embedding, Project, ProjectDocument
from app.services.documents import DocumentService


PROJECT_ID = "project-1"
DOC_ID = "document-1"


def current_status(db, doc_id=DOC_ID):
    """Read the status a reader would see right now."""
    return db.query(Document).filter(Document.id == doc_id).first().status


class FakeChunkingService:
    """Chunking stand-in that records the status it was called with."""

    def __init__(self, timeline, num_chunks=2, failure=None):
        self.timeline = timeline
        self.num_chunks = num_chunks
        self.failure = failure

    def chunk_document(self, db, document_id):
        self.timeline.append(("chunk", current_status(db, document_id)))

        if self.failure:
            raise self.failure

        chunks = [
            Chunk(
                id=f"{document_id}-chunk-{index}",
                document_id=document_id,
                text=f"chunk {index}",
                start_offset=index,
                end_offset=index + 1,
            )
            for index in range(self.num_chunks)
        ]
        for chunk in chunks:
            db.add(chunk)
        db.commit()

        return chunks


class FakeEmbeddingService:
    """Embedding stand-in that records the status it was called with."""

    def __init__(self, timeline, failure=None):
        self.timeline = timeline
        self.failure = failure

    def embed_chunks(self, db, document_id, force_regenerate=False):
        self.timeline.append(("embed", current_status(db, document_id)))

        if self.failure:
            db.rollback()
            raise self.failure

        chunks = db.query(Chunk).filter(Chunk.document_id == document_id).all()
        embeddings = [
            Embedding(
                id=f"{chunk.id}-embedding",
                chunk_id=chunk.id,
                vector_json=[0.1, 0.2],
                model_name="fake-model",
            )
            for chunk in chunks
        ]
        for embedding in embeddings:
            db.add(embedding)
        db.commit()

        return embeddings


class FakePDFAdapter:
    def extract_text_from_file(self, file_path):
        return {
            "text": "Extracted PDF body.",
            "num_pages": 3,
            "metadata": {"author": "Someone"},
        }


class FakeURLAdapter:
    def extract_content(self, url):
        return {
            "text": "Extracted page body.",
            "title": "Example Domain",
            "metadata": {"description": "An example"},
            "headings": ["Example Domain"],
            "links": ["https://example.com/more"],
        }


class FakeYouTubeAdapter:
    def extract_transcript(self, youtube_url):
        return {
            "text": "Spoken words.",
            "video_id": "abc123",
            "duration": 42.0,
            "language": "en",
            "metadata": {"channel": "Example"},
            "segments": [{"text": "Spoken words."}],
        }


@pytest.fixture
def db():
    """An isolated in-memory database with one queued URL document."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(autocommit=False, autoflush=False, bind=engine)()

    session.add(Project(id=PROJECT_ID, name="Research notes", meta_json={}))
    session.add(
        Document(
            id=DOC_ID,
            title="https://example.com",
            source_type="url",
            source_url="https://example.com",
            status="queued",
            meta_json={"url": "https://example.com", "upload_time": "2026-08-13T00:00:00"},
        )
    )
    session.add(ProjectDocument(project_id=PROJECT_ID, document_id=DOC_ID))
    session.commit()

    yield session

    session.close()
    engine.dispose()


def build_service(timeline, chunk_failure=None, embed_failure=None, num_chunks=2):
    """A DocumentService with the slow, external pieces stubbed out."""
    service = DocumentService(
        chunking_service=FakeChunkingService(timeline, num_chunks, chunk_failure),
        embedding_service=FakeEmbeddingService(timeline, embed_failure),
    )
    service.pdf_adapter = FakePDFAdapter()
    service.url_adapter = FakeURLAdapter()
    service.youtube_adapter = FakeYouTubeAdapter()

    return service


def embedding_count(db, doc_id=DOC_ID):
    return (
        db.query(Embedding)
        .join(Chunk, Chunk.id == Embedding.chunk_id)
        .filter(Chunk.document_id == doc_id)
        .count()
    )


class TestReadyMeansRetrievable:
    """A document must not report ``ready`` before it can be retrieved."""

    def test_url_document_is_ready_only_after_indexing(self, db):
        timeline = []
        service = build_service(timeline)

        asyncio.run(service._process_url_async(db, DOC_ID, "https://example.com"))

        # Neither indexing step may see a document that already claims to be
        # ready — that is the window where a query finds nothing.
        assert timeline == [("chunk", "processing"), ("embed", "processing")]
        assert current_status(db) == "ready"
        assert embedding_count(db) == 2

    def test_pdf_document_is_ready_only_after_indexing(self, db):
        db.query(Document).filter(Document.id == DOC_ID).update({"source_type": "pdf"})
        db.commit()
        timeline = []
        service = build_service(timeline)

        asyncio.run(service._process_pdf_async(db, DOC_ID, Path("uploads/example.pdf")))

        assert timeline == [("chunk", "processing"), ("embed", "processing")]
        assert current_status(db) == "ready"
        assert embedding_count(db) == 2

    def test_youtube_document_is_ready_only_after_indexing(self, db):
        db.query(Document).filter(Document.id == DOC_ID).update({"source_type": "youtube"})
        db.commit()
        timeline = []
        service = build_service(timeline)

        asyncio.run(
            service._process_youtube_async(db, DOC_ID, "https://youtu.be/abc123")
        )

        assert timeline == [("chunk", "processing"), ("embed", "processing")]
        assert current_status(db) == "ready"
        assert embedding_count(db) == 2


class TestIndexingFailures:
    """A document that cannot be indexed must not pass itself off as ready."""

    def test_embedding_failure_marks_the_document_failed(self, db):
        service = build_service([], embed_failure=RuntimeError("embedding model exploded"))

        asyncio.run(service._process_url_async(db, DOC_ID, "https://example.com"))

        document = db.query(Document).filter(Document.id == DOC_ID).first()
        assert document.status == "error"
        assert "embedding model exploded" in document.error_message

    def test_chunking_failure_marks_the_document_failed(self, db):
        service = build_service([], chunk_failure=RuntimeError("chunker exploded"))

        asyncio.run(service._process_url_async(db, DOC_ID, "https://example.com"))

        document = db.query(Document).filter(Document.id == DOC_ID).first()
        assert document.status == "error"
        assert "chunker exploded" in document.error_message

    def test_source_without_searchable_text_is_not_ready(self, db):
        service = build_service([], num_chunks=0)

        asyncio.run(service._process_url_async(db, DOC_ID, "https://example.com"))

        document = db.query(Document).filter(Document.id == DOC_ID).first()
        assert document.status == "error"
        assert "searchable text" in document.error_message.lower()

    def test_extraction_failure_still_reports_its_own_error(self, db):
        service = build_service([])

        class ExplodingURLAdapter:
            def extract_content(self, url):
                raise RuntimeError("site unreachable")

        service.url_adapter = ExplodingURLAdapter()

        asyncio.run(service._process_url_async(db, DOC_ID, "https://example.com"))

        document = db.query(Document).filter(Document.id == DOC_ID).first()
        assert document.status == "error"
        assert "site unreachable" in document.error_message

    def test_background_failure_releases_the_ingestion_lease(self, db):
        """A failed background import cannot permanently consume a slot."""
        service = build_service([])
        released = []

        class ExplodingURLAdapter:
            def extract_content(self, url):
                raise RuntimeError("site unreachable")

        service.url_adapter = ExplodingURLAdapter()

        asyncio.run(service._process_url_async(
            db,
            DOC_ID,
            "https://example.com",
            completion_callback=lambda: released.append(True),
        ))

        assert released == [True]


class TestProcessingMetadata:
    """meta_json is a plain JSON column, so it has to be reassigned to persist."""

    def test_url_processing_metadata_reaches_the_database(self, db):
        service = build_service([])

        asyncio.run(service._process_url_async(db, DOC_ID, "https://example.com"))

        db.expire_all()
        meta = db.query(Document).filter(Document.id == DOC_ID).first().meta_json
        assert "processed_at" in meta
        assert meta["headings"] == ["Example Domain"]
        assert meta["num_links"] == 1
        # The keys recorded at upload time must survive the update.
        assert meta["url"] == "https://example.com"

    def test_pdf_processing_metadata_reaches_the_database(self, db):
        db.query(Document).filter(Document.id == DOC_ID).update({"source_type": "pdf"})
        db.commit()
        service = build_service([])

        asyncio.run(service._process_pdf_async(db, DOC_ID, Path("uploads/example.pdf")))

        db.expire_all()
        meta = db.query(Document).filter(Document.id == DOC_ID).first().meta_json
        assert meta["num_pages"] == 3
        assert "processed_at" in meta

    def test_youtube_processing_metadata_reaches_the_database(self, db):
        db.query(Document).filter(Document.id == DOC_ID).update({"source_type": "youtube"})
        db.commit()
        service = build_service([])

        asyncio.run(
            service._process_youtube_async(db, DOC_ID, "https://youtu.be/abc123")
        )

        db.expire_all()
        meta = db.query(Document).filter(Document.id == DOC_ID).first().meta_json
        assert meta["video_id"] == "abc123"
        assert meta["num_segments"] == 1
        assert "processed_at" in meta

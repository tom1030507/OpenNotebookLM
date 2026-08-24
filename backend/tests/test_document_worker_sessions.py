"""Regression tests for detached document-worker database ownership."""
import asyncio
from contextlib import contextmanager
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import Base, Document
from app.services.documents import DocumentService


class ReadyChunkingService:
    """Return a searchable chunk without involving the real chunker."""

    def chunk_document(self, db, document_id, max_chunks=None):
        """Return one chunk marker for the indexed document.

        Args:
            db: Worker-owned database session.
            document_id: Document being indexed.
            max_chunks: Optional production chunk ceiling, unused by this fake.

        Returns:
            A non-empty chunk collection.
        """
        del max_chunks
        return [document_id]


class ReadyEmbeddingService:
    """Return an embedding marker without loading ML dependencies."""

    def embed_chunks(self, db, document_id):
        """Return one embedding marker for the indexed document.

        Args:
            db: Worker-owned database session.
            document_id: Document being embedded.

        Returns:
            A non-empty embedding collection.
        """
        return [document_id]


class PDFAdapter:
    """Supply a complete local PDF extraction result."""

    def extract_text_from_file(self, file_path):
        """Return the shape the document service persists for PDFs.

        Args:
            file_path: Ignored local fixture path.

        Returns:
            Extracted PDF content metadata.
        """
        return {
            "text": "PDF body",
            "num_pages": 1,
            "metadata": {},
            "pages": [],
        }


class URLAdapter:
    """Supply a complete local URL extraction result."""

    def extract_content(self, url):
        """Return the shape the document service persists for URLs.

        Args:
            url: Ignored controlled URL.

        Returns:
            Extracted URL content metadata.
        """
        return {
            "text": "URL body",
            "title": "URL title",
            "metadata": {},
            "headings": [],
            "links": [],
        }


class YouTubeAdapter:
    """Supply a complete local YouTube extraction result."""

    def extract_transcript(self, youtube_url):
        """Return the shape the document service persists for transcripts.

        Args:
            youtube_url: Ignored controlled YouTube URL.

        Returns:
            Extracted transcript content metadata.
        """
        return {
            "text": "Transcript body",
            "video_id": "session-test",
            "duration": 1.0,
            "language": "en",
            "metadata": {},
            "segments": [],
        }


class FailingContentCommitSession:
    """Make the worker's extracted-content commit leave SQLAlchemy unusable."""

    def __init__(self, session, document_id: str):
        """Wrap a worker session and fail its second commit with a duplicate row.

        Args:
            session: Real SQLAlchemy session owned by the worker context.
            document_id: Existing document ID to duplicate during content persistence.

        Returns:
            None.
        """
        self.session = session
        self.document_id = document_id
        self.commit_attempts = 0
        self.rollback_calls = 0
        self.closed = False

    def commit(self):
        """Fail the extracted-content commit through a real database constraint.

        Args:
            None.

        Returns:
            None.
        """
        self.commit_attempts += 1
        if self.commit_attempts == 2:
            self.session.add(
                Document(
                    id=self.document_id,
                    title="duplicate document",
                    source_type="url",
                    status="queued",
                    meta_json={},
                )
            )
        self.session.commit()

    def rollback(self):
        """Record and delegate transaction recovery to the wrapped session.

        Args:
            None.

        Returns:
            None.
        """
        self.rollback_calls += 1
        self.session.rollback()

    def close(self):
        """Record and close the session owned by the worker context.

        Args:
            None.

        Returns:
            None.
        """
        self.closed = True
        self.session.close()

    def __getattr__(self, name):
        """Delegate SQLAlchemy operations not explicitly instrumented here.

        Args:
            name: Name of the wrapped session attribute.

        Returns:
            The requested wrapped session attribute.
        """
        return getattr(self.session, name)


@pytest.mark.parametrize("source_type", ["pdf", "url", "youtube"])
def test_detached_worker_opens_and_closes_its_own_session(source_type):
    """A closed request session cannot affect any detached ingestion worker."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    opened_sessions = []
    closed_sessions = []

    @contextmanager
    def worker_session_context():
        """Create, commit, and close a fresh session for one worker.

        Yields:
            A session owned solely by the detached worker.
        """
        session = session_factory()
        opened_sessions.append(session)
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
            closed_sessions.append(session)

    request_session = session_factory()
    document_id = f"{source_type}-document"
    request_session.add(
        Document(
            id=document_id,
            title="queued source",
            source_type=source_type,
            status="queued",
            meta_json={},
        )
    )
    request_session.commit()
    request_session.close()

    service = DocumentService(
        chunking_service=ReadyChunkingService(),
        embedding_service=ReadyEmbeddingService(),
        pdf_adapter=PDFAdapter(),
        url_adapter=URLAdapter(),
        youtube_adapter=YouTubeAdapter(),
        session_context=worker_session_context,
    )

    if source_type == "pdf":
        asyncio.run(service._process_pdf_async(document_id, Path("fixture.pdf")))
    elif source_type == "url":
        asyncio.run(service._process_url_async(document_id, "https://e2e.invalid/source"))
    else:
        asyncio.run(service._process_youtube_async(document_id, "https://youtu.be/session-test"))

    with session_factory() as verification_session:
        assert verification_session.get(Document, document_id).status == "ready"
    assert opened_sessions == closed_sessions
    assert opened_sessions[0] is not request_session
    engine.dispose()


@pytest.mark.parametrize("source_type", ["pdf", "url", "youtube"])
def test_detached_worker_recovers_failed_content_commit_in_its_owned_session(source_type):
    """A failed content commit is rolled back before the worker persists error state."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    opened_sessions = []
    closed_sessions = []
    document_id = f"{source_type}-failed-content-commit"

    @contextmanager
    def worker_session_context():
        """Create and close the instrumented session owned by a detached worker.

        Yields:
            An owned session that fails only its extracted-content commit.
        """
        wrapped_session = FailingContentCommitSession(session_factory(), document_id)
        opened_sessions.append(wrapped_session)
        try:
            yield wrapped_session
            wrapped_session.commit()
        except Exception:
            wrapped_session.rollback()
            raise
        finally:
            wrapped_session.close()
            closed_sessions.append(wrapped_session)

    with session_factory() as seed_session:
        seed_session.add(
            Document(
                id=document_id,
                title="queued source",
                source_type=source_type,
                status="queued",
                meta_json={},
            )
        )
        seed_session.commit()

    service = DocumentService(
        chunking_service=ReadyChunkingService(),
        embedding_service=ReadyEmbeddingService(),
        pdf_adapter=PDFAdapter(),
        url_adapter=URLAdapter(),
        youtube_adapter=YouTubeAdapter(),
        session_context=worker_session_context,
    )

    if source_type == "pdf":
        asyncio.run(service._process_pdf_async(document_id, Path("fixture.pdf")))
    elif source_type == "url":
        asyncio.run(service._process_url_async(document_id, "https://e2e.invalid/source"))
    else:
        asyncio.run(service._process_youtube_async(document_id, "https://youtu.be/session-test"))

    with session_factory() as verification_session:
        document = verification_session.get(Document, document_id)
        assert document.status == "error"
        assert "UNIQUE constraint failed" in document.error_message
    assert opened_sessions == closed_sessions
    assert opened_sessions[0].rollback_calls >= 1
    assert opened_sessions[0].closed
    engine.dispose()

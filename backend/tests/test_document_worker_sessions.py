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

    def chunk_document(self, db, document_id):
        """Return one chunk marker for the indexed document.

        Args:
            db: Worker-owned database session.
            document_id: Document being indexed.

        Returns:
            A non-empty chunk collection.
        """
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

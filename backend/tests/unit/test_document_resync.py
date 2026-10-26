import hashlib
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.adapters.office import OfficeAdapter
from app.db.models import Base, Document, IngestionJob
from app.services.documents import DocumentService
from app.services.ingestion_jobs import IngestionJobWorker, recover_abandoned_jobs
from app.utils.time import utc_now


class URLAdapter:
    def __init__(self, text):
        self.text = text

    def extract_content(self, _url):
        return {"text": self.text, "title": "Updated title"}


class Chunker:
    def __init__(self):
        self.calls = 0

    def chunk_document(self, *_args, **_kwargs):
        self.calls += 1
        return [object()]


class Embedder:
    def embed_chunks(self, *_args, **_kwargs):
        return [object()]


def make_service(text, chunker):
    service = DocumentService(
        chunking_service=chunker,
        embedding_service=Embedder(),
        url_adapter=URLAdapter(text),
    )
    service._publish_document_index = lambda *_args: None
    return service


def make_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    db = factory()
    db.add(Document(
        id="source-1",
        title="Old title",
        source_type="url",
        source_url="https://example.com/source",
        content="same text",
        status="processing",
        content_hash=hashlib.sha256(b"same text").hexdigest(),
    ))
    db.commit()
    return engine, db


def test_resync_of_unchanged_url_skips_chunking_and_embedding():
    engine, db = make_db()
    chunker = Chunker()
    try:
        service = make_service("same text", chunker)
        status = service.process_ingestion_job(
            db,
            "source-1",
            "resync",
            {"url": "https://example.com/source", "previous_status": "ready"},
        )

        document = db.get(Document, "source-1")
        assert status == "ready"
        assert document.id == "source-1"
        assert document.content_hash == hashlib.sha256(b"same text").hexdigest()
        assert document.last_sync_changed is False
        assert document.last_synced_at is not None
        assert chunker.calls == 0
    finally:
        db.close()
        engine.dispose()


def test_resync_of_changed_url_updates_same_document_and_reindexes():
    engine, db = make_db()
    chunker = Chunker()
    try:
        service = make_service("new text", chunker)
        status = service.process_ingestion_job(
            db,
            "source-1",
            "resync",
            {"url": "https://example.com/source", "previous_status": "ready"},
        )

        document = db.get(Document, "source-1")
        assert status == "ready"
        assert document.id == "source-1"
        assert document.content == "new text"
        assert document.content_hash == hashlib.sha256(b"new text").hexdigest()
        assert document.last_sync_changed is True
        assert document.last_synced_at is not None
        assert "_resync_index_started" not in document.meta_json
        assert chunker.calls == 1
    finally:
        db.close()
        engine.dispose()


@pytest.mark.parametrize(
    ("current_title", "previous_auto_title", "expected_title"),
    [
        ("Old note", "Old note", "New note"),
        ("note.md", None, "New note"),
        ("Custom label", "Old note", "Custom label"),
    ],
)
def test_git_markdown_resync_updates_generated_titles_but_keeps_manual_renames(
    current_title,
    previous_auto_title,
    expected_title,
    tmp_path,
):
    engine, db = make_db()
    document = db.get(Document, "source-1")
    source_path = tmp_path / "note.md"
    source_path.write_text("---\ntitle: New note\n---\nUpdated body", encoding="utf-8")
    document.title = current_title
    document.source_type = "md"
    document.source_url = str(source_path)
    document.content = "Old body"
    document.meta_json = {
        "filename": "note.md",
        "file_extension": ".md",
        "file_size": source_path.stat().st_size,
        "git_repository_id": "repository-1",
        "metadata": {
            "format": "md",
            "title": previous_auto_title,
        },
    }
    db.commit()
    chunker = Chunker()
    service = DocumentService(
        chunking_service=chunker,
        embedding_service=Embedder(),
        office_adapter=OfficeAdapter(),
    )
    service._publish_document_index = lambda *_args: None

    try:
        status = service.process_ingestion_job(
            db,
            "source-1",
            "resync",
            {"file_path": str(source_path), "previous_status": "ready"},
        )

        assert status == "ready"
        assert document.title == expected_title
        assert document.content == "Updated body"
    finally:
        db.close()
        engine.dispose()


@pytest.mark.parametrize(
    ("previous_status", "previous_error", "index_started", "expected_status"),
    [
        ("ready", None, False, "ready"),
        ("error", "old failure", False, "error"),
        ("ready", None, True, "error"),
    ],
)
def test_failed_resync_restores_or_fails_source_based_on_index_checkpoint(
    previous_status,
    previous_error,
    index_started,
    expected_status,
):
    engine, db = make_db()
    document = db.get(Document, "source-1")
    document.error_message = None
    if index_started:
        document.meta_json = {"_resync_index_started": True}
    job = IngestionJob(
        id="resync-job",
        document_id=document.id,
        job_type="resync",
        payload_json={
            "url": document.source_url,
            "previous_status": previous_status,
            "previous_error_message": previous_error,
        },
        status="running",
        attempts=1,
        started_at=utc_now(),
    )
    db.add(job)
    db.commit()
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    def fail_refresh(*_args):
        raise RuntimeError("refresh failed")

    worker = IngestionJobWorker(session_factory, processor=fail_refresh)
    try:
        worker._process_claimed_job(job.id)
        db.expire_all()
        document = db.get(Document, "source-1")
        assert document.status == expected_status
        assert document.error_message == (
            "refresh failed" if index_started else previous_error
        )
        assert "_resync_index_started" not in (document.meta_json or {})
    finally:
        db.close()
        engine.dispose()


def test_recovering_abandoned_resync_keeps_source_processing():
    engine, db = make_db()
    document = db.get(Document, "source-1")
    document.status = "processing"
    job = IngestionJob(
        id="abandoned-resync",
        document_id=document.id,
        job_type="resync",
        payload_json={"url": document.source_url, "previous_status": "ready"},
        status="running",
        attempts=1,
        started_at=utc_now(),
    )
    db.add(job)
    db.commit()
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        assert recover_abandoned_jobs(session_factory) == 1
        db.expire_all()
        assert db.get(IngestionJob, job.id).status == "queued"
        assert db.get(Document, document.id).status == "processing"
    finally:
        db.close()
        engine.dispose()

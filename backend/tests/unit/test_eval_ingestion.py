"""The retrieval evaluation indexes cached pages only in its own database."""
from functools import partial

import pytest
import requests
from sqlalchemy.orm import Session

from app.adapters import url as url_adapter
from app.db import database
from app.db.models import Chunk, Document, Embedding, ProjectDocument
from app.services import documents
from scripts import eval_corpus, eval_retrieval
from scripts.e2e_services import DeterministicEmbeddingService


def _forbid_external_access(*args, **kwargs):
    raise AssertionError("eval ingestion accessed the application DB or network")


def test_ingest_corpus_persists_cached_pages_in_eval_database(tmp_path, monkeypatch):
    """Real extraction/indexing must stay offline and commit into the eval DB.

    Args:
        tmp_path: Isolated cache and database directory.
        monkeypatch: Fixture restoring dependency overrides after the test.

    Returns:
        None.
    """
    monkeypatch.setattr(eval_corpus, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(database, "SessionLocal", _forbid_external_access)
    monkeypatch.setattr(url_adapter, "resolve_public_http_url", _forbid_external_access)
    monkeypatch.setattr(requests.Session, "send", _forbid_external_access)
    # Only the expensive model is replaced: the document service, HTML parser,
    # chunker, and index publisher still exercise their real persistence paths.
    monkeypatch.setattr(
        documents,
        "DocumentService",
        partial(
            documents.DocumentService,
            embedding_service=DeterministicEmbeddingService(),
        ),
    )
    eval_corpus.cache_path("fixture").write_text(
        "<html><head><title>Frozen eval page</title></head><body><article>"
        "<h1>Energy storage</h1>"
        "<p>Rechargeable batteries store chemical energy for later use. "
        "Lithium ions move between the electrodes during charging and "
        "discharging. The separator allows ion movement while keeping "
        "the electrodes apart to prevent a short circuit.</p>"
        "</article></body></html>",
        encoding="utf-8",
    )
    db, engine = eval_retrieval.build_session(tmp_path / "eval.db")
    try:
        doc_ids = eval_retrieval.ingest_corpus(
            db,
            [{"id": "fixture", "url": "https://example.com/frozen"}],
            "eval-project",
        )
        # A new reader catches a missing final ready-state commit as well as
        # accidental writes to a different session's database.
        with Session(engine) as reader:
            document = reader.get(Document, doc_ids["fixture"])
            assert document.status == "ready"
            assert document.title == "Frozen eval page"
            assert "Rechargeable batteries store chemical energy" in document.content
            assert document.error_message is None
            assert reader.query(ProjectDocument).filter_by(
                project_id="eval-project", document_id=document.id,
            ).one()
            chunks = reader.query(Chunk).filter_by(document_id=document.id).all()
            assert chunks
            assert reader.query(Embedding).filter(
                Embedding.chunk_id.in_([chunk.id for chunk in chunks]),
            ).count() == len(chunks)
    finally:
        db.close()
        engine.dispose()


def test_cache_replay_rejects_urls_outside_the_corpus(monkeypatch):
    """Cache replay never falls back to a live download for an unknown URL.

    Args:
        monkeypatch: Fixture restoring the blocked network boundary.

    Returns:
        None.
    """
    monkeypatch.setattr(url_adapter, "resolve_public_http_url", _forbid_external_access)
    adapter = url_adapter.URLAdapter()
    with eval_corpus.serve_from_cache([]):
        with pytest.raises(requests.RequestException, match="not part of the eval corpus"):
            adapter.extract_content("https://example.com/unlisted")

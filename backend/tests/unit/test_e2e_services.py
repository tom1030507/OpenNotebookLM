"""Tests for the deterministic E2E service boundary."""
import importlib
import math
import os
import pickle
import subprocess
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

import numpy as np
import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import Base, Chunk, Document, Embedding
from app.routers.ingest import get_document_service
from app.routers.query import get_rag_service
from scripts.e2e_server import (
    install_fast_overrides,
    resolve_frontend_url,
    resolve_runtime_root,
)
from scripts.e2e_services import (
    DeterministicEmbeddingService,
    FixedURLAdapter,
    FixedYouTubeAdapter,
)


def _real_rag_module():
    """Return the real RAG module when a route test left a no-file stub behind.

    Args:
        None.

    Returns:
        The importable production RAG module.
    """
    module = sys.modules.get("app.services.rag")
    if module is None or getattr(module, "__file__", None) is None:
        sys.modules.pop("app.services.rag", None)
        module = importlib.import_module("app.services.rag")
    return module


def _create_directory_link(link: Path, target: Path) -> None:
    """Create a directory symlink or Windows junction for a containment test.

    Args:
        link: Exact link path owned by the current test.
        target: Existing directory the link should resolve to.

    Returns:
        None.
    """
    try:
        link.symlink_to(target, target_is_directory=True)
        return
    except OSError as symlink_error:
        if os.name != "nt":
            pytest.skip(f"Directory symlinks are unavailable: {symlink_error}")

    completed = subprocess.run(
        ["cmd", "/d", "/c", "mklink", "/J", str(link), str(target)],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        if os.path.lexists(link):
            _remove_directory_link(link)
        pytest.skip(
            "Directory links are unavailable: "
            f"{completed.stderr.strip() or completed.stdout.strip()}"
        )


def _remove_directory_link(link: Path) -> None:
    """Remove only the exact link created by the current test.

    Args:
        link: Symlink or junction path to unlink without traversing its target.

    Returns:
        None.
    """
    if not os.path.lexists(link):
        return
    if link.is_symlink():
        link.unlink()
        return
    link.rmdir()


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


def test_equal_similarity_scores_use_chunk_id_as_a_stable_tiebreaker(db):
    """Equal dense scores must return the same order on every database backend."""
    document = Document(
        id="document-ties",
        title="Tie Notes",
        source_type="url",
        status="processing",
        meta_json={},
    )
    db.add_all(
        [
            document,
            Chunk(
                id="chunk-zeta",
                document_id=document.id,
                text="Identical searchable text.",
                start_offset=0,
                end_offset=26,
                meta_json={},
            ),
            Chunk(
                id="chunk-alpha",
                document_id=document.id,
                text="Identical searchable text.",
                start_offset=1,
                end_offset=27,
                meta_json={},
            ),
        ]
    )
    db.commit()
    service = DeterministicEmbeddingService()
    service.embed_chunks(db, document.id)

    results = service.search_similar_chunks(
        db,
        query="Identical searchable text.",
        document_ids=[document.id],
        top_k=2,
        threshold=-1.0,
    )

    assert [result["chunk_id"] for result in results] == [
        "chunk-alpha",
        "chunk-zeta",
    ]


def test_runtime_root_accepts_only_a_named_child(tmp_path):
    """A run directory beneath output/e2e is the only valid target."""
    repo = tmp_path / "repo"
    accepted = repo / "output" / "e2e" / "run-123"

    assert resolve_runtime_root(str(accepted), repo) == accepted.resolve()


def test_frontend_url_defaults_to_the_task_2_loopback_origin():
    """Direct Task 2 launches must retain their original safe CORS origin."""
    assert resolve_frontend_url(None) == "http://127.0.0.1:3100"


@pytest.mark.parametrize(
    "origin",
    [
        "http://localhost:3100",
        "http://127.0.0.1:3100",
        "http://[::1]:3100",
    ],
)
def test_frontend_url_accepts_only_supported_loopback_hosts(origin):
    """The browser origin may use a supported loopback spelling."""
    assert resolve_frontend_url(origin) == origin


@pytest.mark.parametrize(
    "origin",
    [
        "",
        " http://localhost:3100",
        "http://localhost:3100 ",
        "https://localhost:3100",
        "http://example.com:3100",
        "http://localhost",
        "http://localhost:31000",
        "http://localhost:3100/path",
        "http://localhost:3100?query=yes",
        "http://localhost:3100#fragment",
        "http://user:password@localhost:3100",
    ],
)
def test_frontend_url_rejects_non_origin_or_non_e2e_values(origin):
    """Untrusted or malformed values must not enter the CORS allowlist."""
    with pytest.raises(ValueError, match="frontend URL"):
        resolve_frontend_url(origin)


@pytest.mark.parametrize(
    "relative", [".", "output", "output/e2e", "data", "uploads", "../outside"]
)
def test_runtime_root_rejects_broad_or_escaped_paths(tmp_path, relative):
    """Broad and escaped paths must never become E2E cleanup targets."""
    repo = tmp_path / "repo"

    with pytest.raises(ValueError, match="runtime root"):
        resolve_runtime_root(str(repo / relative), repo)


def test_runtime_root_rejects_linked_allowed_parent(tmp_path):
    """The trusted output/e2e parent must not resolve outside the repository."""
    repo = tmp_path / "repo"
    linked_parent = repo / "output" / "e2e"
    linked_parent.parent.mkdir(parents=True)
    external_parent = tmp_path / "external-parent"
    (external_parent / "run-123").mkdir(parents=True)
    _create_directory_link(linked_parent, external_parent)

    try:
        with pytest.raises(ValueError, match="runtime root"):
            resolve_runtime_root(str(linked_parent / "run-123"), repo)
    finally:
        _remove_directory_link(linked_parent)
    assert (external_parent / "run-123").is_dir()


def test_runtime_root_rejects_linked_child(tmp_path):
    """A named child must not resolve through a link to an external tree."""
    repo = tmp_path / "repo"
    allowed_parent = repo / "output" / "e2e"
    allowed_parent.mkdir(parents=True)
    external_child = tmp_path / "external-child"
    external_child.mkdir()
    linked_child = allowed_parent / "run-linked"
    _create_directory_link(linked_child, external_child)

    try:
        with pytest.raises(ValueError, match="runtime root"):
            resolve_runtime_root(str(linked_child), repo)
    finally:
        _remove_directory_link(linked_child)
    assert external_child.is_dir()


def test_runtime_root_rejects_external_alias_to_an_internal_child(tmp_path):
    """An external raw path must not be trusted because it resolves internally."""
    repo = tmp_path / "repo"
    internal_child = repo / "output" / "e2e" / "run-123"
    internal_child.mkdir(parents=True)
    external_alias = tmp_path / "external-alias"
    _create_directory_link(external_alias, internal_child)

    try:
        with pytest.raises(ValueError, match="runtime root"):
            resolve_runtime_root(str(external_alias), repo)
    finally:
        _remove_directory_link(external_alias)
    assert internal_child.is_dir()


def test_fast_overrides_select_the_deterministic_service_graph(monkeypatch):
    """Fast overrides must replace both route and durable-worker boundaries."""
    class StubRAGService:
        """No-file stand-in matching the route tests' unused dependency stub."""

    stale_module = ModuleType("app.services.rag")
    stale_module.RAGService = StubRAGService
    monkeypatch.setitem(sys.modules, "app.services.rag", stale_module)

    real_rag = _real_rag_module()
    assert real_rag is not stale_module
    assert real_rag.RAGService is not StubRAGService

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
    assert isinstance(rag_service, real_rag.RAGService)

    calls = []
    document_service.process_ingestion_job = lambda db, **kwargs: calls.append(
        (db, kwargs)
    )
    database = object()
    application.state.ingestion_job_processor(
        database,
        SimpleNamespace(
            document_id="document-id",
            job_type="url",
            payload_json={"url": "https://e2e.invalid/source"},
        ),
    )
    assert calls == [(
        database,
        {
            "document_id": "document-id",
            "job_type": "url",
            "payload": {"url": "https://e2e.invalid/source"},
        },
    )]

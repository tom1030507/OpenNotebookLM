# OpenNotebookLM End-to-End Test Suite Implementation Plan

> **Historical implementation record:** Version pins and runtime details in
> this task-by-task plan reflect the original implementation sequence. Use
> `e2e/README.md`, the tracked requirements files, and the current workflow as
> the authoritative operating contract.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build deterministic browser-to-database E2E coverage for OpenNotebookLM's critical workflows, plus an opt-in full production-embedding retrieval test.

**Architecture:** Playwright drives a real Chromium browser against isolated Next.js and FastAPI processes on ports 3100 and 8100. The fast project keeps the real routers, ownership checks, services, SQLite persistence, PDF extraction, chunking, and LLM fallback while injecting deterministic embeddings and fixed URL/YouTube adapters; the nightly project uses the production embedding service. Every run owns a validated directory under `output/e2e/<run-id>` and retains complete diagnostics only when it fails.

**Tech Stack:** Python 3.10, FastAPI, SQLAlchemy, SQLite, Next.js, TypeScript, Node.js 22, Playwright, Chromium, pdf-lib, GitHub Actions

**Spec:** `e2e/README.md`

## Global Constraints

- Work only in the live `backend/app/` tree; never extend the orphan root-level `app/` tree.
- Keep FastAPI routers thin: validate and authorize, then delegate through an injected service.
- Every new public Python function and method must have a docstring containing `Args:` and `Returns:` sections; methods with no arguments beyond `self` must explicitly say `Args: None`.
- Use four-space Python indentation and the existing two-space, semicolon, single-quote TypeScript style.
- Use ports `3100` and `8100`; set `reuseExistingServer: false` so an occupied port fails the run.
- Fast E2E must not import or install torch or sentence-transformers and must not require an API key or public network.
- Full-RAG E2E must set `LLM_MODE=none`; it verifies local production embeddings and retrieval, not remote model wording.
- Run Chromium only, desktop viewport `1440x900`, one worker, zero local retries, and one CI retry.
- Never use fixed sleeps. Synchronize with locators, named HTTP responses, status polling, downloads, dialogs, and reload assertions.
- Each test owns a unique account derived from run and test identity; tests must not rely on order or state created by another test.
- Put databases, uploads, generated PDFs, server logs, reports, traces, screenshots, and videos only below `output/e2e/<run-id>`.
- Before recursively deleting a runtime directory, resolve it and prove it is a strict descendant of `<repo>/output/e2e`; reject empty paths and repository, home, output, `data`, or `uploads` roots.
- Preserve existing frontend Vitest and backend pytest suites as independent gates; E2E supplements them.
- Follow TDD in each task: add a failing focused test, observe the expected failure, implement the minimum behavior, rerun focused and relevant regression tests, then commit one concern.
- Use Conventional Commit prefixes and never commit credentials, model files, runtime databases, uploads, or Playwright artifacts.

## File and Responsibility Map

| File | Responsibility |
| --- | --- |
| `backend/app/routers/ingest.py` | Provide a lazy cached `DocumentService` dependency and inject it only into mutation routes. |
| `backend/app/routers/query.py` | Provide a lazy cached `RAGService` dependency and inject it only into the query route. |
| `backend/app/services/documents.py` | Accept injected services/adapters without importing the production embedding implementation. |
| `backend/app/services/rag.py` | Accept injected embedding and LLM services without importing the production embedding implementation. |
| `backend/tests/unit/test_service_dependencies.py` | Prove construction is lazy, cached, injectable, and preserves explicitly supplied falsey test doubles. |
| `backend/scripts/e2e_services.py` | Implement deterministic token-hash embeddings and fixed URL/YouTube adapters with production-compatible interfaces. |
| `backend/scripts/e2e_server.py` | Validate runtime isolation, configure the app before import, and apply fast-tier dependency overrides. |
| `backend/tests/unit/test_e2e_services.py` | Prove deterministic ranking, persistence shape, adapter contracts, and safe runtime-path validation. |
| `backend/requirements-e2e.txt` | Install only the backend dependencies required by deterministic E2E. |
| `backend/requirements-e2e-rag.txt` | Add the production embedding dependency set for nightly/manual full-RAG E2E. |
| `e2e/package.json`, `e2e/package-lock.json` | Define the standalone Playwright package and reproducible scripts. |
| `e2e/tsconfig.json` | Type-check the standalone config, helpers, reporter, and specs under strict NodeNext rules. |
| `e2e/playwright.config.ts` | Select projects, start both real servers, isolate artifacts, and configure retries/diagnostics. |
| `e2e/support/runtime.ts` | Derive run paths/environment and enforce cleanup containment. |
| `e2e/support/run-service.ts` | Spawn backend/frontend cross-platform and tee their output to retained logs. |
| `e2e/support/cleanup-reporter.ts` | Remove a successful local runtime only after reporters finish; retain failed runs. |
| `e2e/support/api.ts` | Expose typed authenticated setup and persistence-check APIs. |
| `e2e/support/diagnostics.ts` | Collect unexpected page, console, request, response, and application errors. |
| `e2e/support/fixtures.ts` | Compose Playwright fixtures and turn collected diagnostics into failures/attachments. |
| `e2e/support/ui.ts` | Centralize account generation and repeated UI actions without hiding assertions. |
| `e2e/support/pdf.ts` | Generate valid per-test PDFs containing unique searchable facts. |
| `e2e/tests/runtime.spec.ts` | Prove the isolated frontend/backend stack is the one under test. |
| `e2e/tests/runtime-paths.spec.ts` | Protect lexical/real runtime containment and marked cleanup assumptions. |
| `e2e/tests/api-helper.spec.ts` | Exercise setup-client authentication, project creation, and conversation CRUD contracts. |
| `e2e/tests/pdf-fixture.spec.ts` | Prove generated PDF fixtures are structurally valid. |
| `e2e/tests/auth.spec.ts` | Cover anonymous redirect, registration/session, wrong password, and logout. |
| `e2e/tests/projects.spec.ts` | Cover project persistence and two-account isolation. |
| `e2e/tests/sources.spec.ts` | Cover PDF, fixed URL, and fixed YouTube lifecycles. |
| `e2e/tests/chat.spec.ts` | Cover retrieval/citations/message persistence and conversation CRUD. |
| `e2e/tests/studio-and-settings.spec.ts` | Cover mind map, report, export, video/audio fallback, and theme persistence. |
| `e2e/tests/full-rag.spec.ts` | Cover production embedding ingestion and retrieval with a generated local PDF. |
| `.github/workflows/e2e.yml` | Run fast E2E on pull requests/pushes and full RAG nightly/on demand. |
| `README.md` | Document supported local E2E commands and tier expectations. |
| `e2e/README.md` | Change the approved design status to implemented after final verification. |

---

### Task 1: Make document and RAG services lazy and injectable

**Files:**

- Create: `backend/tests/unit/test_service_dependencies.py`
- Modify: `backend/tests/unit/test_rag_retrieval_query.py:25-40,123-132`
- Modify: `backend/tests/unit/test_retrieval_scope.py:35-49,130-138`
- Modify: `backend/app/routers/ingest.py:1-228`
- Modify: `backend/app/routers/query.py:1-196`
- Modify: `backend/app/services/documents.py:1-40`
- Modify: `backend/app/services/rag.py:1-39`

**Interfaces:**

- Consumes: FastAPI `Depends`, `functools.lru_cache`, existing `DocumentService.process_*`, and existing `RAGService.query_with_conversation` behavior.
- Produces: `get_document_service() -> Any`, `get_rag_service() -> Any`, `DocumentService(chunking_service: Any | None = None, embedding_service: Any | None = None, pdf_adapter: Any | None = None, url_adapter: Any | None = None, youtube_adapter: Any | None = None)`, and `RAGService(embedding_service: Any | None = None, llm_service: Any | None = None)`.
- Later tasks override `get_document_service` and `get_rag_service` through `app.dependency_overrides`; do not rename them or wrap them in lambdas inside route declarations.

- [ ] **Step 1: Add focused tests for lazy providers and constructor injection**

Create `backend/tests/unit/test_service_dependencies.py` with tests that replace the production embedding module before importing the service under test, clear both providers' caches, and verify the injected object is retained by identity:

```python
"""Tests for lazy, injectable document and RAG dependencies."""
import importlib
import subprocess
import sys
from types import ModuleType, SimpleNamespace


class FalseyDouble:
    """A falsey dependency used to catch `value or Default()` regressions."""

    def __bool__(self):
        """Report false while remaining a valid dependency.

        Args:
            None.

        Returns:
            False.
        """
        return False


def test_service_modules_do_not_import_embeddings_for_injected_dependencies(monkeypatch):
    """Injected services must work when the ML module cannot be imported."""
    monkeypatch.delitem(sys.modules, "app.services.documents", raising=False)
    monkeypatch.delitem(sys.modules, "app.services.rag", raising=False)
    monkeypatch.setitem(sys.modules, "app.services.embeddings", None)

    documents = importlib.import_module("app.services.documents")
    rag = importlib.import_module("app.services.rag")
    embedding = FalseyDouble()
    chunking = FalseyDouble()
    llm = FalseyDouble()

    document_service = documents.DocumentService(
        chunking_service=chunking,
        embedding_service=embedding,
        pdf_adapter=FalseyDouble(),
        url_adapter=FalseyDouble(),
        youtube_adapter=FalseyDouble(),
    )
    rag_service = rag.RAGService(embedding_service=embedding, llm_service=llm)

    assert document_service.embedding_service is embedding
    assert document_service.chunking_service is chunking
    assert rag_service.embedding_service is embedding
    assert rag_service.llm_service is llm


def test_router_service_providers_are_lazy_cached_dependencies(monkeypatch):
    """Providers must construct once and remain addressable for overrides."""
    created = {"documents": 0, "rag": 0}

    class FakeDocumentService:
        def __init__(self):
            created["documents"] += 1

    class FakeRAGService:
        def __init__(self):
            created["rag"] += 1

    document_module = ModuleType("app.services.documents")
    document_module.DocumentService = FakeDocumentService
    rag_module = ModuleType("app.services.rag")
    rag_module.RAGService = FakeRAGService
    monkeypatch.setitem(sys.modules, "app.services.documents", document_module)
    monkeypatch.setitem(sys.modules, "app.services.rag", rag_module)

    from app.routers.ingest import get_document_service
    from app.routers.query import get_rag_service

    get_document_service.cache_clear()
    get_rag_service.cache_clear()
    try:
        assert get_document_service() is get_document_service()
        assert get_rag_service() is get_rag_service()
        assert created == {"documents": 1, "rag": 1}
    finally:
        get_document_service.cache_clear()
        get_rag_service.cache_clear()


def test_importing_routers_does_not_import_the_embedding_module():
    """A fresh router import must not cross the ML dependency boundary."""
    code = """
import sys
from app.config import Settings, get_settings
Settings.model_config["env_file"] = None
get_settings.cache_clear()
import app.routers.ingest
import app.routers.query
print("app.services.embeddings" in sys.modules)
"""
    completed = subprocess.run(
        [sys.executable, "-c", code],
        check=True,
        capture_output=True,
        text=True,
    )
    assert completed.stdout.strip() == "False"
```

- [ ] **Step 2: Run the focused tests and confirm the eager-import failure**

Run from `backend/` in the documented ML-capable test environment:

```bash
python -m pytest tests/unit/test_service_dependencies.py -q
```

Expected: collection or execution fails because `documents.py` and `rag.py` import `EmbeddingService` at module scope, the routers construct services at import time, constructors replace falsey injected values, and adapter injection parameters do not exist.

- [ ] **Step 3: Add lazy cached providers to the ingest and query routers**

In `backend/app/routers/ingest.py`, remove the module-scope `DocumentService` import and instance, add `Any` and `lru_cache`, and inject the provider only into `upload_file`, `upload_url`, `upload_youtube`, and `delete_document`:

```python
from functools import lru_cache
from typing import Any, Optional


@lru_cache
def get_document_service() -> Any:
    """Return the process-wide document service on first use.

    Args:
        None.

    Returns:
        The production document service.
    """
    from app.services.documents import DocumentService

    return DocumentService()
```

Each mutation handler receives the same named dependency and delegates through it:

```python
async def upload_url(
    project_id: str,
    request: URLUploadRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    document_service: Any = Depends(get_document_service),
):
```

Apply the identical dependency parameter to the other three mutation handlers; status/detail/download handlers do not need the service and must remain unchanged.

In `backend/app/routers/query.py`, remove the module-scope `RAGService` import and instance, define the parallel provider, and inject it only into `query`:

```python
@lru_cache
def get_rag_service() -> Any:
    """Return the process-wide RAG service on first use.

    Args:
        None.

    Returns:
        The production RAG service.
    """
    from app.services.rag import RAGService

    return RAGService()


def query(
    request: QueryRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    rag_service: Any = Depends(get_rag_service),
):
```

Keep all existing authorization, request shaping, and response shaping in both routers exactly as they are.

- [ ] **Step 4: Make service constructors preserve explicit dependencies and defer the ML import**

In `backend/app/services/documents.py`, delete the top-level `EmbeddingService` import and expand the constructor:

```python
def __init__(
    self,
    chunking_service=None,
    embedding_service=None,
    pdf_adapter=None,
    url_adapter=None,
    youtube_adapter=None,
):
    """Initialize document processing dependencies.

    Args:
        chunking_service: Optional chunking implementation.
        embedding_service: Optional embedding implementation.
        pdf_adapter: Optional PDF extraction implementation.
        url_adapter: Optional URL extraction implementation.
        youtube_adapter: Optional YouTube transcript implementation.

    Returns:
        None.
    """
    if embedding_service is None:
        from app.services.embeddings import EmbeddingService

        embedding_service = EmbeddingService()

    self.pdf_adapter = pdf_adapter if pdf_adapter is not None else PDFAdapter(use_pymupdf=False)
    self.url_adapter = url_adapter if url_adapter is not None else URLAdapter()
    self.youtube_adapter = youtube_adapter
    self.executor = ThreadPoolExecutor(max_workers=4)
    self.chunking_service = (
        chunking_service if chunking_service is not None else ChunkingService()
    )
    self.embedding_service = embedding_service
```

The existing lazy YouTube branch (`if not self.youtube_adapter`) must become an identity check so a falsey valid adapter is preserved:

```python
if self.youtube_adapter is None:
    self.youtube_adapter = YouTubeAdapter()
```

In `backend/app/services/rag.py`, delete the top-level `EmbeddingService` import and implement:

```python
def __init__(self, embedding_service=None, llm_service=None):
    """Initialize RAG dependencies.

    Args:
        embedding_service: Optional embedding and dense-search implementation.
        llm_service: Optional answer-generation implementation.

    Returns:
        None.
    """
    if embedding_service is None:
        from app.services.embeddings import EmbeddingService

        embedding_service = EmbeddingService()

    self.embedding_service = embedding_service
    self.llm_service = llm_service if llm_service is not None else LLMService()
```

- [ ] **Step 5: Run focused and route regression tests**

Before running the suite, update the two focused RAG tests that currently detect a real module with `hasattr(module, "EmbeddingService")`. The lazy import intentionally removes that module attribute. Detect the route-test stub by module origin, and pass the doubles through the public constructor:

```python
def real_rag_module():
    """Return the real module when a route test left its no-file stub behind.

    Args:
        None.

    Returns:
        The filesystem-backed RAG module.
    """
    module = sys.modules.get("app.services.rag")
    if module is None or getattr(module, "__file__", None) is None:
        sys.modules.pop("app.services.rag", None)
        module = importlib.import_module("app.services.rag")
    return module
```

In `test_rag_retrieval_query.py`, replace the patched construction with:

```python
instance = module.RAGService(
    embedding_service=embeddings,
    llm_service=llm,
)
```

In `test_retrieval_scope.py`, replace it with:

```python
instance = module.RAGService(
    embedding_service=embeddings,
    llm_service=RecordingLLMService(),
)
```

Remove `from unittest import mock` from both files; no remaining test uses it.

Run from `backend/` in the ML-capable environment:

```bash
python -m pytest tests/unit/test_service_dependencies.py tests/unit/test_rag_retrieval_query.py tests/unit/test_retrieval_scope.py tests/test_api_authentication.py tests/test_document_indexing.py tests/test_conversations.py tests/test_user_isolation.py -q
```

Expected: all selected tests pass, and importing the routers does not construct either service until its provider is requested.

- [ ] **Step 6: Commit the injectable service boundary**

```bash
git add backend/app/routers/ingest.py backend/app/routers/query.py backend/app/services/documents.py backend/app/services/rag.py backend/tests/unit/test_service_dependencies.py backend/tests/unit/test_rag_retrieval_query.py backend/tests/unit/test_retrieval_scope.py
git commit -m "refactor: make document and rag services injectable"
```

---

### Task 2: Build deterministic E2E services and the isolated backend entry point

**Files:**

- Create: `backend/scripts/e2e_services.py`
- Create: `backend/scripts/e2e_server.py`
- Create: `backend/tests/unit/test_e2e_services.py`
- Create: `backend/requirements-e2e.txt`
- Create: `backend/requirements-e2e-rag.txt`

**Interfaces:**

- Consumes: Task 1's `get_document_service`, `get_rag_service`, adapter constructor injection, SQLAlchemy `Document`, `Chunk`, `Embedding`, `ChunkingService`, and `LLMService`.
- Produces: `DeterministicEmbeddingService(dimensions: int = 256)`, `FixedURLAdapter.extract_content(url: str) -> dict[str, Any]`, `FixedYouTubeAdapter.extract_transcript(url: str) -> dict[str, Any]`, `resolve_runtime_root(raw_path: str, repo_root: Path) -> Path`, `create_application() -> tuple[Any, Any]`, and executable `main() -> None`.
- `DeterministicEmbeddingService` must implement the production signatures `generate_embedding`, `embed_chunks`, and `search_similar_chunks` and persist `float32` pickle plus JSON vectors.

- [ ] **Step 1: Write deterministic embedding and adapter contract tests**

Create `backend/tests/unit/test_e2e_services.py` with its own focused in-memory database fixture because `backend/tests/conftest.py` provides auth helpers but no database fixture:

```python
"""Tests for the deterministic E2E service boundary."""
import math
import pickle

import numpy as np
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import Base, Chunk, Document, Embedding
from scripts.e2e_services import (
    DeterministicEmbeddingService,
    FixedURLAdapter,
    FixedYouTubeAdapter,
)


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
    related = service.generate_embedding("What is the ORBIT-7319 access code?", role="query")
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
```

- [ ] **Step 2: Run the deterministic service tests and confirm the module is missing**

Run from `backend/`:

```bash
python -m pytest tests/unit/test_e2e_services.py -q
```

Expected: collection fails with `ModuleNotFoundError: No module named 'scripts.e2e_services'`.

- [ ] **Step 3: Implement stable token-hash embeddings**

Create `backend/scripts/e2e_services.py`. Tokenization must lowercase Unicode word/hyphen sequences, SHA-256 each token, use the first four digest bytes for the bucket, the next byte for sign, accumulate counts, and normalize once. Use the same function for passage and query roles so exact unique identifiers remain retrievable:

```python
"""Deterministic service substitutes used only by browser E2E tests."""
from __future__ import annotations

import hashlib
import pickle
import re
import uuid
from typing import Any, List, Optional, Union

import numpy as np
from sqlalchemy.orm import Session

from app.db.models import Chunk, Document, Embedding

TOKEN_PATTERN = re.compile(r"[\w-]+", re.UNICODE)
MODEL_NAME = "e2e-token-hash-v1"


class DeterministicEmbeddingService:
    """Small stable embedding implementation with the production interface."""

    def __init__(self, dimensions: int = 256):
        """Configure vector width.

        Args:
            dimensions: Number of token-hash buckets.

        Returns:
            None.
        """
        if dimensions < 8:
            raise ValueError("dimensions must be at least 8")
        self.dimensions = dimensions

    def _vector(self, text: str, normalize: bool) -> np.ndarray:
        vector = np.zeros(self.dimensions, dtype=np.float32)
        for token in TOKEN_PATTERN.findall(text.casefold()):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            bucket = int.from_bytes(digest[:4], "big") % self.dimensions
            vector[bucket] += 1.0 if digest[4] & 1 else -1.0
        norm = float(np.linalg.norm(vector))
        if normalize and norm:
            vector /= norm
        return vector

    def generate_embedding(
        self,
        text: Union[str, List[str]],
        normalize: bool = True,
        use_cache: bool = True,
        role: str = "passage",
    ) -> Union[np.ndarray, List[np.ndarray]]:
        """Generate stable embeddings without a model download.

        Args:
            text: One string or a list of strings.
            normalize: Whether to L2-normalize each vector.
            use_cache: Accepted for production interface compatibility.
            role: Accepted for production interface compatibility.

        Returns:
            One float32 vector or a list of float32 vectors.
        """
        del use_cache, role
        if isinstance(text, str):
            return self._vector(text, normalize)
        return [self._vector(item, normalize) for item in text]

    def embed_chunks(
        self,
        db: Session,
        document_id: str,
        force_regenerate: bool = False,
    ) -> List[Embedding]:
        """Persist deterministic embeddings for every document chunk.

        Args:
            db: Database session.
            document_id: Document whose chunks are indexed.
            force_regenerate: Whether to replace existing vectors.

        Returns:
            All embedding rows for the document's chunks.
        """
        document = db.query(Document).filter(Document.id == document_id).first()
        if document is None:
            raise ValueError(f"Document {document_id} not found")
        chunks = db.query(Chunk).filter(
            Chunk.document_id == document_id
        ).order_by(Chunk.start_offset, Chunk.id).all()
        if not chunks:
            return []
        chunk_ids = [chunk.id for chunk in chunks]
        if force_regenerate:
            db.query(Embedding).filter(Embedding.chunk_id.in_(chunk_ids)).delete(
                synchronize_session=False
            )
            db.commit()
        existing = {
            row.chunk_id: row
            for row in db.query(Embedding).filter(Embedding.chunk_id.in_(chunk_ids)).all()
        }
        pending = [chunk for chunk in chunks if chunk.id not in existing]
        texts = []
        for chunk in pending:
            context = [part for part in (document.title, chunk.heading_path) if part]
            prefix = " > ".join(context)
            texts.append(f"{prefix}\n\n{chunk.text}" if prefix else chunk.text)
        vectors = self.generate_embedding(texts, role="passage") if texts else []
        for chunk, vector in zip(pending, vectors):
            vector = vector.astype(np.float32)
            db.add(Embedding(
                id=str(uuid.uuid4()),
                chunk_id=chunk.id,
                vector=pickle.dumps(vector),
                vector_json=vector.tolist(),
                model_name=MODEL_NAME,
            ))
        db.commit()
        return db.query(Embedding).filter(Embedding.chunk_id.in_(chunk_ids)).all()

    def search_similar_chunks(
        self,
        db: Session,
        query: str,
        document_ids: Optional[List[str]] = None,
        top_k: int = 5,
        threshold: float = 0.7,
    ) -> List[dict[str, Any]]:
        """Rank stored chunks by deterministic cosine similarity.

        Args:
            db: Database session.
            query: Search text.
            document_ids: Optional exact document scope; an empty list means none.
            top_k: Maximum number of results.
            threshold: Minimum cosine score.

        Returns:
            Production-shaped chunk payloads sorted best first.
        """
        if document_ids is not None and not document_ids:
            return []
        rows = db.query(Embedding).join(Chunk)
        if document_ids is not None:
            rows = rows.filter(Chunk.document_id.in_(document_ids))
        query_vector = self.generate_embedding(query, role="query")
        ranked = []
        for record in rows.all():
            score = float(np.dot(query_vector, pickle.loads(record.vector)))
            if score < threshold:
                continue
            chunk = record.chunk
            document = db.query(Document).filter(Document.id == chunk.document_id).first()
            ranked.append({
                "chunk_id": chunk.id,
                "document_id": chunk.document_id,
                "document_title": document.title if document else "Unknown",
                "text": chunk.text,
                "score": score,
                "metadata": {
                    "page_num": chunk.page_num,
                    "timestamp": chunk.ts_start,
                    "section": chunk.meta_json.get("section") if chunk.meta_json else None,
                    "heading_path": chunk.heading_path,
                },
            })
        ranked.sort(key=lambda item: item["score"], reverse=True)
        return ranked[:top_k]
```

Every public method must repeat the exact production argument names/defaults so `DocumentService` and `RAGService` can use either implementation without a branch.

- [ ] **Step 4: Implement fixed URL and YouTube adapters**

In the same module, return complete production-shaped data with a unique shared fact:

```python
class FixedURLAdapter:
    """Return controlled URL content without public network access."""

    def extract_content(self, url: str) -> dict[str, Any]:
        """Return a fixed article for the requested URL.

        Args:
            url: Source URL retained in the result.

        Returns:
            Extracted-content data matching URLAdapter.
        """
        return {
            "url": url,
            "title": "E2E Observatory Field Notes",
            "text": (
                "# Observatory Operations\n\n"
                "The observatory access code is ORBIT-7319. "
                "Use it only for the deterministic browser test."
            ),
            "html": "<h1>Observatory Operations</h1><p>The observatory access code is ORBIT-7319.</p>",
            "metadata": {"description": "Controlled E2E source", "url": url},
            "headings": [{"level": 1, "text": "Observatory Operations", "tag": "h1"}],
            "links": [],
        }


class FixedYouTubeAdapter:
    """Return a controlled transcript without contacting YouTube."""

    def extract_transcript(self, url: str) -> dict[str, Any]:
        """Return a fixed timed transcript.

        Args:
            url: YouTube URL retained in metadata.

        Returns:
            Transcript data matching YouTubeAdapter.
        """
        video_id = "e2eOrbit7319"
        segments = [
            {"text": "Welcome to the observatory.", "start": 0.0, "end": 12.0, "duration": 12.0},
            {"text": "The access code is ORBIT-7319.", "start": 12.0, "end": 42.0, "duration": 30.0},
        ]
        return {
            "video_id": video_id,
            "url": url,
            "text": "Welcome to the observatory. The access code is ORBIT-7319.",
            "segments": segments,
            "duration": 42.0,
            "metadata": {
                "video_id": video_id,
                "url": url,
                "language": "en",
                "is_generated": False,
                "duration": 42.0,
            },
            "language": "en",
        }
```

- [ ] **Step 5: Add safe runtime-path tests before writing the E2E server**

Extend `backend/tests/unit/test_e2e_services.py` with a parameterized path check:

```python
from pathlib import Path

import pytest

from fastapi import FastAPI

from app.routers.ingest import get_document_service
from app.routers.query import get_rag_service
from scripts.e2e_server import install_fast_overrides, resolve_runtime_root


def test_runtime_root_accepts_only_a_named_child(tmp_path):
    """A run directory beneath output/e2e is the only valid target."""
    repo = tmp_path / "repo"
    accepted = repo / "output" / "e2e" / "run-123"

    assert resolve_runtime_root(str(accepted), repo) == accepted.resolve()


@pytest.mark.parametrize("relative", [".", "output", "output/e2e", "data", "uploads", "../outside"])
def test_runtime_root_rejects_broad_or_escaped_paths(tmp_path, relative):
    """Broad and escaped paths must never become E2E cleanup targets."""
    repo = tmp_path / "repo"

    with pytest.raises(ValueError, match="runtime root"):
        resolve_runtime_root(str(repo / relative), repo)


def test_fast_overrides_select_the_deterministic_service_graph():
    """FastAPI overrides must replace both production embedding boundaries."""
    application = FastAPI()

    install_fast_overrides(application)

    document_service = application.dependency_overrides[get_document_service]()
    rag_service = application.dependency_overrides[get_rag_service]()
    assert isinstance(document_service.embedding_service, DeterministicEmbeddingService)
    assert document_service.embedding_service is rag_service.embedding_service
    assert isinstance(document_service.url_adapter, FixedURLAdapter)
    assert isinstance(document_service.youtube_adapter, FixedYouTubeAdapter)
```

Run:

```bash
python -m pytest tests/unit/test_e2e_services.py -q
```

Expected: adapter/embedding cases pass and runtime-path/override cases fail because `scripts.e2e_server` does not exist.

- [ ] **Step 6: Implement the E2E server entry point and dependency overrides**

Create `backend/scripts/e2e_server.py` with import-safe path helpers. Only `create_application` imports application modules, after environment and working directory are fixed:

```python
"""Run an isolated FastAPI instance for Playwright E2E tests."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any


def resolve_runtime_root(raw_path: str, repo_root: Path) -> Path:
    """Validate a run-specific directory beneath repository output/e2e.

    Args:
        raw_path: Candidate runtime path from E2E_RUNTIME_ROOT.
        repo_root: Resolved repository root.

    Returns:
        The resolved safe runtime directory.
    """
    if not raw_path.strip():
        raise ValueError("E2E runtime root is empty")
    root = repo_root.resolve()
    allowed_parent = (root / "output" / "e2e").resolve()
    candidate = Path(raw_path).resolve()
    if candidate == allowed_parent or allowed_parent not in candidate.parents:
        raise ValueError(f"Unsafe E2E runtime root: {candidate}")
    if candidate in {root, Path.home().resolve(), root / "data", root / "uploads"}:
        raise ValueError(f"Unsafe E2E runtime root: {candidate}")
    return candidate


def install_fast_overrides(application: Any) -> None:
    """Install deterministic substitutes at expensive/external boundaries.

    Args:
        application: FastAPI application receiving dependency overrides.

    Returns:
        None.
    """
    from app.adapters.pdf import PDFAdapter
    from app.routers.ingest import get_document_service
    from app.routers.query import get_rag_service
    from app.services.chunking import ChunkingService
    from app.services.documents import DocumentService
    from app.services.llm import LLMService
    from app.services.rag import RAGService
    from scripts.e2e_services import (
        DeterministicEmbeddingService,
        FixedURLAdapter,
        FixedYouTubeAdapter,
    )

    embedding = DeterministicEmbeddingService()
    document_service = DocumentService(
        chunking_service=ChunkingService(),
        embedding_service=embedding,
        pdf_adapter=PDFAdapter(use_pymupdf=False),
        url_adapter=FixedURLAdapter(),
        youtube_adapter=FixedYouTubeAdapter(),
    )
    rag_service = RAGService(
        embedding_service=embedding,
        llm_service=LLMService(),
    )
    application.dependency_overrides[get_document_service] = lambda: document_service
    application.dependency_overrides[get_rag_service] = lambda: rag_service


def create_application() -> tuple[Any, Any]:
    """Configure and create the isolated FastAPI application.

    Args:
        None.

    Returns:
        The application and its resolved settings.
    """
    repo_root = Path(__file__).resolve().parents[2]
    runtime_root = resolve_runtime_root(os.environ.get("E2E_RUNTIME_ROOT", ""), repo_root)
    runtime_root.mkdir(parents=True, exist_ok=True)
    os.chdir(runtime_root)
    database = runtime_root / "opennotebook.db"
    os.environ.update(
        {
            "APP_ENV": "test",
            "APP_PORT": "8100",
            "DEBUG": "false",
            "DB_PATH": str(database),
            "DATABASE_URL": f"sqlite:///{database.as_posix()}",
            "JWT_SECRET_KEY": "e2e-only-signing-key-not-a-secret",
            "LLM_MODE": "none",
            "OPENAI_API_KEY": "",
            "CLAUDE_API_KEY": "",
            "YT_API_KEY": "",
            "RATE_LIMIT_ENABLED": "false",
            "CORS_ORIGINS": "http://127.0.0.1:3100",
            "ENABLE_YT_TRANSCRIPTION": "true",
        }
    )

    from app.config import get_settings

    get_settings.cache_clear()
    from app.main import app

    if os.environ.get("FULL_RAG_E2E") == "1":
        from app.routers.ingest import get_document_service
        from app.routers.query import get_rag_service

        get_document_service()
        get_rag_service()
    else:
        install_fast_overrides(app)
    return app, get_settings()


def main() -> None:
    """Start the single-process E2E backend.

    Args:
        None.

    Returns:
        None.
    """
    import uvicorn

    application, settings = create_application()
    uvicorn.run(
        application,
        host="127.0.0.1",
        port=settings.app_port,
        workers=1,
        reload=False,
    )


if __name__ == "__main__":
    main()
```

Because `app.main` is imported only inside `create_application` after environment setup, database initialization points at the runtime database and relative upload/data/model paths resolve inside the changed runtime root. Full-RAG mode installs no overrides and eagerly initializes the production providers before `/healthz` becomes reachable, so model download/loading is part of server readiness rather than the first upload request.

- [ ] **Step 7: Define deterministic and full-RAG dependency sets**

Create `backend/requirements-e2e.txt`:

```text
-r requirements-minimal.txt
bcrypt==4.3.0
beautifulsoup4==4.12.2
numpy==1.24.3
pdfminer.six==20221105
python-jose[cryptography]==3.3.0
requests==2.34.2
```

Create `backend/requirements-e2e-rag.txt`:

```text
-r requirements-e2e.txt
huggingface-hub==0.25.2
sentence-transformers==2.2.2
transformers==4.44.2
```

The `huggingface-hub` upper-compatible pin is required because sentence-transformers 2.2.2 imports the pre-0.26 `cached_download` API. Do not add torch or sentence-transformers to the fast requirements file; pip resolves torch only for the full-RAG install.

- [ ] **Step 8: Run backend unit tests and verify the reduced dependency import boundary**

Run in the backend test environment:

```bash
python -m pytest tests/unit/test_service_dependencies.py tests/unit/test_e2e_services.py -q
python -c "from scripts.e2e_services import DeterministicEmbeddingService; print(DeterministicEmbeddingService().generate_embedding('ready').shape)"
```

Expected: all focused tests pass and the import command prints `(256,)` without loading `app.services.embeddings`.

- [ ] **Step 9: Commit deterministic backend support**

```bash
git add backend/scripts/e2e_server.py backend/scripts/e2e_services.py backend/tests/unit/test_e2e_services.py backend/requirements-e2e.txt backend/requirements-e2e-rag.txt
git commit -m "test: add deterministic e2e backend"
```

---

### Task 3: Create the standalone Playwright runtime and diagnostic harness

**Files:**

- Create: `e2e/package.json`
- Create: `e2e/package-lock.json`
- Create: `e2e/tsconfig.json`
- Create: `e2e/playwright.config.ts`
- Create: `e2e/support/runtime.ts`
- Create: `e2e/support/run-service.ts`
- Create: `e2e/support/cleanup-reporter.ts`
- Create: `e2e/support/diagnostics.ts`
- Create: `e2e/support/fixtures.ts`
- Create: `e2e/tests/runtime-paths.spec.ts`
- Create: `e2e/tests/runtime.spec.ts`

**Interfaces:**

- Consumes: Task 2's `python -m scripts.e2e_server`, FastAPI `/healthz`, frontend `/login`, and the ignored repository `output/` directory.
- Produces: `runtime` (`RuntimePaths`), `assertSafeRuntimePath(candidate: string): string`, `prepareRuntimeDirectory(repository: string, outputRoot: string, runRoot: string): boolean`, `safeRemoveRuntime(candidate: string): void`, `BrowserDiagnostics`, and the base `test`/`expect` exports from `support/fixtures.ts`.
- Tasks 4-8 import only `test` and `expect` from `support/fixtures.ts`, `runtime` from `support/runtime.ts`, and never import `@playwright/test` directly in specs.

- [ ] **Step 1: Define the reproducible E2E package**

Create `e2e/package.json`:

```json
{
  "name": "opennotebooklm-e2e",
  "version": "1.0.0",
  "private": true,
  "type": "module",
  "engines": {
    "node": ">=22"
  },
  "scripts": {
    "test": "playwright test --project=chromium-fast",
    "test:headed": "playwright test --project=chromium-fast --headed",
    "test:debug": "playwright test --project=chromium-fast --debug",
    "test:full-rag": "cross-env FULL_RAG_E2E=1 playwright test --project=chromium-full-rag",
    "typecheck": "tsc --noEmit"
  },
  "devDependencies": {
    "@playwright/test": "1.62.1",
    "@types/node": "22.20.1",
    "cross-env": "10.1.0",
    "pdf-lib": "1.17.1",
    "tsx": "4.23.12",
    "typescript": "5.9.3"
  }
}
```

Create `e2e/tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "NodeNext",
    "moduleResolution": "NodeNext",
    "strict": true,
    "noEmit": true,
    "types": ["node", "@playwright/test"],
    "skipLibCheck": true
  },
  "include": ["playwright.config.ts", "support/**/*.ts", "tests/**/*.ts"]
}
```

From `e2e/`, run:

```bash
npm install --package-lock-only
npm ci
```

Expected: `package-lock.json` records the exact top-level versions and `npm ci` exits 0.

- [ ] **Step 2: Write runtime containment tests before the runtime helper**

Create `e2e/tests/runtime-paths.spec.ts` temporarily as a focused Node-side Playwright test:

```typescript
import { existsSync, mkdirSync, symlinkSync, writeFileSync } from 'node:fs';
import path from 'node:path';

import { expect, test } from '@playwright/test';

import {
  assertSafeRuntimePath,
  outputRoot,
  prepareRuntimeDirectory,
  runtime,
  safeRemoveRuntime,
} from '../support/runtime.js';

test('accepts only strict children of output/e2e', () => {
  const run = path.join(outputRoot, 'run-safe-123');

  expect(assertSafeRuntimePath(run)).toBe(path.resolve(run));
  expect(() => assertSafeRuntimePath(outputRoot)).toThrow(/unsafe e2e runtime/i);
  expect(() => assertSafeRuntimePath(path.dirname(outputRoot))).toThrow(/unsafe e2e runtime/i);
  expect(() => assertSafeRuntimePath(path.resolve(outputRoot, '..', '..', 'uploads'))).toThrow(
    /unsafe e2e runtime/i,
  );
});

test('requires a matching marker before recursive cleanup', () => {
  const candidate = path.join(outputRoot, `cleanup-contract-${runtime.runId}`);
  mkdirSync(candidate, { recursive: true });
  writeFileSync(path.join(candidate, '.e2e-runtime'), 'wrong-run', 'utf8');

  expect(() => safeRemoveRuntime(candidate)).toThrow(/marker/i);
  expect(existsSync(candidate)).toBe(true);

  writeFileSync(path.join(candidate, '.e2e-runtime'), runtime.runId, 'utf8');
  safeRemoveRuntime(candidate);
  expect(existsSync(candidate)).toBe(false);
});

test('rejects an output link before creating a run outside its repository', ({}, testInfo) => {
  const sandbox = testInfo.outputPath('linked-output');
  const repository = path.join(sandbox, 'repo');
  const outputParent = path.join(repository, 'output');
  const linkedOutput = path.join(outputParent, 'e2e');
  const outside = path.join(sandbox, 'outside');
  const escapedRun = path.join(outside, 'must-not-exist');
  mkdirSync(outputParent, { recursive: true });
  mkdirSync(outside, { recursive: true });
  try {
    symlinkSync(outside, linkedOutput, process.platform === 'win32' ? 'junction' : 'dir');
  } catch (error) {
    test.skip(true, `This host cannot create a directory link: ${String(error)}`);
    return;
  }

  expect(() => prepareRuntimeDirectory(
    repository,
    linkedOutput,
    path.join(linkedOutput, 'must-not-exist'),
  )).toThrow(/symbolic link|junction/i);
  expect(existsSync(escapedRun)).toBe(false);
});
```

Run from `e2e/` without starting web servers:

```bash
npx playwright test tests/runtime-paths.spec.ts --list
npm run typecheck
```

Expected: both commands fail because `support/runtime.ts` does not exist. After Step 3 passes, keep this file as a permanent cleanup-safety regression test and add it to the file map.

- [ ] **Step 3: Implement runtime derivation and guarded cleanup**

Create `e2e/support/runtime.ts`:

```typescript
import { randomUUID } from 'node:crypto';
import { existsSync, mkdirSync, readFileSync, realpathSync, rmSync, writeFileSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';

export interface RuntimePaths {
  repoRoot: string;
  outputRoot: string;
  root: string;
  generated: string;
  serverLogs: string;
  testResults: string;
  htmlReport: string;
  runId: string;
  apiUrl: string;
  frontendUrl: string;
}

export const repoRoot = path.resolve(import.meta.dirname, '..', '..');
export const outputRoot = path.join(repoRoot, 'output', 'e2e');

export function assertSafeRuntimePath(candidatePath: string): string {
  const candidate = path.resolve(candidatePath);
  const relative = path.relative(path.resolve(outputRoot), candidate);
  const forbidden = new Set([
    path.resolve(repoRoot),
    path.resolve(outputRoot),
    path.resolve(os.homedir()),
    path.resolve(repoRoot, 'data'),
    path.resolve(repoRoot, 'uploads'),
  ]);
  if (
    !candidatePath.trim()
    || !relative
    || relative.startsWith(`..${path.sep}`)
    || relative === '..'
    || path.isAbsolute(relative)
    || forbidden.has(candidate)
  ) {
    throw new Error(`Unsafe E2E runtime path: ${candidatePath}`);
  }
  return candidate;
}

function pathsEqual(first: string, second: string): boolean {
  return path.relative(first, second) === '';
}

export function prepareRuntimeDirectory(
  repositoryPath: string,
  candidateOutputRoot: string,
  candidateRoot: string,
): boolean {
  const realRepository = realpathSync(repositoryPath);
  const outputParent = path.dirname(candidateOutputRoot);
  mkdirSync(outputParent, { recursive: true });
  const realOutputParent = realpathSync(outputParent);
  const expectedOutputParent = path.join(realRepository, 'output');
  if (!pathsEqual(expectedOutputParent, realOutputParent)) {
    throw new Error(`E2E output parent crosses a symbolic link or junction: ${realOutputParent}`);
  }
  if (!existsSync(candidateOutputRoot)) {
    mkdirSync(candidateOutputRoot);
  }
  const realOutput = realpathSync(candidateOutputRoot);
  const expectedOutput = path.join(realRepository, 'output', 'e2e');
  if (!pathsEqual(expectedOutput, realOutput)) {
    throw new Error(`E2E output root crosses a symbolic link or junction: ${realOutput}`);
  }
  const existed = existsSync(candidateRoot);
  if (!existed) {
    mkdirSync(candidateRoot);
  }
  const realRoot = realpathSync(candidateRoot);
  const realRelative = path.relative(realOutput, realRoot);
  if (!realRelative || realRelative.startsWith(`..${path.sep}`) || path.isAbsolute(realRelative)) {
    throw new Error(`Unsafe real E2E runtime path: ${realRoot}`);
  }
  return existed;
}

const runId = process.env.E2E_RUN_ID
  ?? `${Date.now().toString(36)}-${randomUUID().slice(0, 8)}`;
if (!/^[A-Za-z0-9._-]+$/.test(runId)) {
  throw new Error(`Invalid E2E_RUN_ID: ${runId}`);
}
process.env.E2E_RUN_ID = runId;

const root = assertSafeRuntimePath(path.join(outputRoot, runId));
export const runtime: RuntimePaths = {
  repoRoot,
  outputRoot,
  root,
  generated: path.join(root, 'generated'),
  serverLogs: path.join(root, 'server-logs'),
  testResults: path.join(root, 'test-results'),
  htmlReport: path.join(root, 'playwright-report'),
  runId,
  apiUrl: 'http://127.0.0.1:8100/api',
  frontendUrl: 'http://127.0.0.1:3100',
};

const existed = prepareRuntimeDirectory(repoRoot, outputRoot, runtime.root);
const realRoot = realpathSync(runtime.root);
const runtimeMarker = path.join(realRoot, '.e2e-runtime');
if (existed) {
  if (!existsSync(runtimeMarker) || readFileSync(runtimeMarker, 'utf8') !== runtime.runId) {
    throw new Error(`Existing E2E runtime has no matching marker: ${realRoot}`);
  }
} else {
  writeFileSync(runtimeMarker, runtime.runId, 'utf8');
}
for (const directory of [runtime.generated, runtime.serverLogs, runtime.testResults]) {
  mkdirSync(directory, { recursive: true });
}

export function safeRemoveRuntime(candidatePath: string): void {
  const safePath = assertSafeRuntimePath(candidatePath);
  if (!existsSync(safePath)) {
    return;
  }
  const realOutput = realpathSync(outputRoot);
  const realCandidate = realpathSync(safePath);
  const realRelative = path.relative(realOutput, realCandidate);
  if (!realRelative || realRelative.startsWith(`..${path.sep}`) || path.isAbsolute(realRelative)) {
    throw new Error(`Unsafe real E2E runtime path: ${realCandidate}`);
  }
  const marker = path.join(realCandidate, '.e2e-runtime');
  if (!existsSync(marker) || readFileSync(marker, 'utf8') !== runtime.runId) {
    throw new Error(`Missing or invalid E2E runtime marker: ${marker}`);
  }
  rmSync(safePath, {
    recursive: true,
    force: true,
    maxRetries: 5,
    retryDelay: 200,
  });
}

const inheritedEnvironment = Object.fromEntries(
  Object.entries(process.env).filter((entry): entry is [string, string] => entry[1] !== undefined),
);
export const serverEnvironment: Record<string, string> = {
  ...inheritedEnvironment,
  E2E_RUNTIME_ROOT: runtime.root,
  E2E_API_URL: runtime.apiUrl,
  E2E_FRONTEND_URL: runtime.frontendUrl,
  NEXT_PUBLIC_API_URL: runtime.apiUrl,
};
```

Run:

```bash
npm run typecheck
npx playwright test tests/runtime-paths.spec.ts --list
```

Expected: TypeScript succeeds and Playwright lists all three containment/cleanup tests. Do not run them until webServer configuration exists in Step 6.

- [ ] **Step 4: Implement a cross-platform server runner with retained logs**

Create `e2e/support/run-service.ts`:

```typescript
import { spawn, spawnSync, type ChildProcess } from 'node:child_process';
import { createWriteStream } from 'node:fs';
import path from 'node:path';

import { runtime, serverEnvironment } from './runtime.js';

type ServiceName = 'backend' | 'frontend';

let stopping = false;

function start(service: ServiceName): ChildProcess {
  const isBackend = service === 'backend';
  const executable = isBackend ? (process.env.E2E_PYTHON ?? 'python') : process.execPath;
  const args = isBackend
    ? ['-m', 'scripts.e2e_server']
    : [
        path.join(runtime.repoRoot, 'frontend', 'node_modules', 'next', 'dist', 'bin', 'next'),
        'dev',
        '--turbopack',
        '--hostname',
        '127.0.0.1',
        '--port',
        '3100',
      ];
  const cwd = path.join(runtime.repoRoot, isBackend ? 'backend' : 'frontend');
  const log = createWriteStream(path.join(runtime.serverLogs, `${service}.log`), { flags: 'a' });
  const child = spawn(executable, args, {
    cwd,
    env: serverEnvironment,
    stdio: ['ignore', 'pipe', 'pipe'],
    windowsHide: true,
    detached: process.platform !== 'win32',
  });

  child.stdout?.on('data', (chunk: Buffer) => {
    process.stdout.write(chunk);
    log.write(chunk);
  });
  child.stderr?.on('data', (chunk: Buffer) => {
    process.stderr.write(chunk);
    log.write(chunk);
  });
  child.on('error', (error) => {
    log.end(`\nFailed to start ${service}: ${error.stack ?? error.message}\n`);
    process.exitCode = 1;
  });
  child.on('exit', (code, signal) => {
    log.end(`\n${service} exited code=${String(code)} signal=${String(signal)}\n`);
    process.exitCode = stopping ? 0 : (code ?? (signal ? 1 : 0));
  });
  return child;
}

function stopTree(child: ChildProcess, signal: NodeJS.Signals): void {
  if (child.pid === undefined) {
    return;
  }
  stopping = true;
  if (process.platform === 'win32') {
    spawnSync('taskkill', ['/pid', String(child.pid), '/t', '/f'], {
      stdio: 'ignore',
      windowsHide: true,
    });
    return;
  }
  try {
    process.kill(-child.pid, signal);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== 'ESRCH') {
      throw error;
    }
  }
}

function main(): void {
  const service = process.argv[2];
  if (service !== 'backend' && service !== 'frontend') {
    throw new Error('Usage: run-service.ts backend|frontend');
  }
  const child = start(service);
  for (const signal of ['SIGINT', 'SIGTERM'] as const) {
    process.once(signal, () => stopTree(child, signal));
  }
}

main();
```

Run:

```bash
npm run typecheck
```

Expected: TypeScript succeeds on both Windows and Linux types. The frontend starts through Node's Next.js entry point instead of a shell-only `.cmd` shim, and termination reaches the entire service process tree.

- [ ] **Step 5: Add automatic browser diagnostics and cleanup-after-reporting**

Create `e2e/support/diagnostics.ts`:

```typescript
import type { Page, TestInfo } from '@playwright/test';

import { runtime } from './runtime.js';

export class BrowserDiagnostics {
  private readonly issues: string[] = [];

  private isApplicationUrl(url: string): boolean {
    return url.startsWith(runtime.frontendUrl) || url.startsWith(runtime.apiUrl);
  }

  install(page: Page): void {
    page.on('pageerror', (error) => this.issues.push(`pageerror: ${error.stack ?? error.message}`));
    page.on('console', (message) => {
      if (message.type() === 'error') {
        this.issues.push(`console.error: ${message.text()}`);
      }
    });
    page.on('requestfailed', (request) => {
      if (
        this.isApplicationUrl(request.url())
        && request.failure()?.errorText !== 'net::ERR_ABORTED'
      ) {
        this.issues.push(
          `requestfailed: ${request.method()} ${request.url()} ${request.failure()?.errorText ?? ''}`,
        );
      }
    });
    page.on('response', (response) => {
      if (this.isApplicationUrl(response.url()) && response.status() >= 500) {
        this.issues.push(`http ${response.status()}: ${response.request().method()} ${response.url()}`);
      }
    });
  }

  async verify(testInfo: TestInfo): Promise<void> {
    if (this.issues.length === 0) {
      return;
    }
    const body = Buffer.from(`${this.issues.join('\n')}\n`, 'utf8');
    await testInfo.attach('unexpected-browser-diagnostics.txt', {
      body,
      contentType: 'text/plain',
    });
    if (testInfo.status === undefined || testInfo.status === testInfo.expectedStatus) {
      throw new Error(`Unexpected browser diagnostics:\n${this.issues.join('\n')}`);
    }
  }
}
```

Create `e2e/support/fixtures.ts`:

```typescript
import { test as base, expect } from '@playwright/test';

import { BrowserDiagnostics } from './diagnostics.js';

type AutomaticFixtures = {
  browserDiagnostics: BrowserDiagnostics;
};

export const test = base.extend<AutomaticFixtures>({
  browserDiagnostics: [async ({ page }, use, testInfo) => {
    const diagnostics = new BrowserDiagnostics();
    diagnostics.install(page);
    await use(diagnostics);
    await diagnostics.verify(testInfo);
  }, { auto: true }],
});

export { expect };
```

Create `e2e/support/cleanup-reporter.ts`:

```typescript
import type { FullResult, Reporter, TestCase, TestResult } from '@playwright/test/reporter';

import { runtime, safeRemoveRuntime } from './runtime.js';

export default class CleanupReporter implements Reporter {
  private hadFailedAttempt = false;
  private succeeded = false;

  onTestEnd(_test: TestCase, result: TestResult): void {
    if (!['passed', 'skipped'].includes(result.status)) {
      this.hadFailedAttempt = true;
    }
  }

  onEnd(result: FullResult): void {
    this.succeeded = result.status === 'passed' && !this.hadFailedAttempt;
  }

  async onExit(): Promise<void> {
    if (this.succeeded && process.env.E2E_KEEP_RUNTIME !== '1') {
      try {
        safeRemoveRuntime(runtime.root);
      } catch (error) {
        process.stderr.write(`E2E cleanup warning: ${String(error)}\n`);
      }
    }
  }
}
```

Cleanup stays in `onExit`, after all reporters have built their output; a failed or interrupted run is never removed.

- [ ] **Step 6: Configure two real web servers and both Chromium projects**

Create `e2e/playwright.config.ts`:

```typescript
import { defineConfig, devices } from '@playwright/test';

import { runtime, serverEnvironment } from './support/runtime.js';

const isCI = process.env.CI === 'true';

export default defineConfig({
  testDir: './tests',
  timeout: process.env.FULL_RAG_E2E === '1' ? 10 * 60_000 : 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  retries: isCI ? 1 : 0,
  retryStrategy: 'isolated',
  forbidOnly: isCI,
  failOnFlakyTests: isCI,
  outputDir: runtime.testResults,
  reporter: [
    ['list'],
    ['html', { outputFolder: runtime.htmlReport, open: 'never' }],
    ['./support/cleanup-reporter.ts'],
  ],
  use: {
    baseURL: runtime.frontendUrl,
    viewport: { width: 1440, height: 900 },
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    trace: 'retain-on-failure',
  },
  webServer: [
    {
      command: 'node --import tsx support/run-service.ts backend',
      cwd: import.meta.dirname,
      env: serverEnvironment,
      url: 'http://127.0.0.1:8100/healthz',
      reuseExistingServer: false,
      timeout: process.env.FULL_RAG_E2E === '1' ? 10 * 60_000 : 120_000,
      stdout: 'pipe',
      stderr: 'pipe',
    },
    {
      command: 'node --import tsx support/run-service.ts frontend',
      cwd: import.meta.dirname,
      env: serverEnvironment,
      url: 'http://127.0.0.1:3100/login',
      reuseExistingServer: false,
      timeout: 180_000,
      stdout: 'pipe',
      stderr: 'pipe',
    },
  ],
  projects: [
    {
      name: 'chromium-fast',
      use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } },
      testIgnore: /full-rag\.spec\.ts/,
    },
    ...(process.env.FULL_RAG_E2E === '1' ? [{
      name: 'chromium-full-rag',
      use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } },
      testMatch: /full-rag\.spec\.ts/,
    }] : []),
  ],
});
```

Do not use `reuseExistingServer: !process.env.CI`: local reuse could silently connect to a developer process and its database. Both readiness URLs must remain explicit and the backend must start before tests even if the frontend happens to compile first.

- [ ] **Step 7: Add and run the first browser-to-backend smoke test**

Create `e2e/tests/runtime.spec.ts`:

```typescript
import { test, expect } from '../support/fixtures.js';
import { runtime } from '../support/runtime.js';

test('serves the isolated backend and protects the workspace', async ({ page, request }) => {
  const health = await request.get('http://127.0.0.1:8100/healthz');

  expect(health.ok()).toBe(true);
  expect(await health.json()).toMatchObject({
    ok: true,
    database: 'healthy',
    environment: 'test',
    config: { llm_mode: 'none', debug: false },
  });

  await page.goto('/');
  await expect(page).toHaveURL(`${runtime.frontendUrl}/login`);
  await expect(page.getByRole('button', { name: 'Login' })).toBeVisible();
});
```

Install Chromium and run from `e2e/` with the fast backend requirements available:

```bash
npx playwright install chromium
npm run typecheck
npm test -- tests/runtime-paths.spec.ts tests/runtime.spec.ts
```

Expected: both tests pass, server logs are written below the run root while executing, and the successful run directory disappears after the HTML reporter completes. Repeat with `E2E_KEEP_RUNTIME=1` and verify the directory contains `server-logs/backend.log` and `server-logs/frontend.log`.

- [ ] **Step 8: Prove occupied ports fail safely**

In a separate terminal, start a disposable listener owned by this verification step:

```bash
node -e "require('http').createServer((_, res) => res.end('disposable')).listen(8100, '127.0.0.1', () => console.log('disposable listener ready'))"
```

After it prints `disposable listener ready`, run in the E2E terminal:

```bash
npm test -- tests/runtime.spec.ts
```

Expected: Playwright exits nonzero with a port-in-use/web-server startup error and does not reuse the disposable process. Press Ctrl-C in the listener terminal to stop only that Node process; do not terminate unrelated listeners.

- [ ] **Step 9: Commit the Playwright runtime**

```bash
git add e2e/package.json e2e/package-lock.json e2e/tsconfig.json e2e/playwright.config.ts e2e/support/runtime.ts e2e/support/run-service.ts e2e/support/cleanup-reporter.ts e2e/support/diagnostics.ts e2e/support/fixtures.ts e2e/tests/runtime-paths.spec.ts e2e/tests/runtime.spec.ts
git commit -m "test: add isolated playwright runtime"
```

---

### Task 4: Add typed setup helpers and authentication/project workflows

**Files:**

- Create: `e2e/support/api.ts`
- Create: `e2e/support/ui.ts`
- Modify: `e2e/support/fixtures.ts`
- Create: `e2e/tests/auth.spec.ts`
- Create: `e2e/tests/projects.spec.ts`

**Interfaces:**

- Consumes: Task 3's base fixture, frontend routes `/` and `/login`, and backend `/api/auth/*`, `/api/projects*`, `/api/docs/*`, `/api/query`, and `/api/conversations/*` contracts.
- Produces: `Account`, `Project`, `DocumentRecord`, `DocumentStatus`, `Conversation`, `ConversationDetail`, `QueryResult`, `E2EApi`, `accountFor(testInfo, suffix)`, `loginThroughUi`, `registerThroughUi`, `createProjectThroughUi`, `signOutThroughUi`, and `openAddSourceDialog`.
- Account identity includes `testInfo.retry`; CI retry isolation depends on this exact input.

- [ ] **Step 1: Write an API-helper contract test before the helper exists**

Create `e2e/tests/api-helper.spec.ts`:

```typescript
import { test, expect } from '../support/fixtures.js';
import { accountFor } from '../support/ui.js';

test('creates isolated authenticated setup data through the real API', async ({ api }, testInfo) => {
  const account = accountFor(testInfo, 'api-contract');
  await api.register(account);
  await api.login(account);
  const project = await api.createProject('API Contract Project', 'Owned by this test');

  expect(project.name).toBe('API Contract Project');
  await expect.poll(async () => (await api.listProjects()).map((item) => item.id)).toContain(project.id);
});
```

Run:

```bash
npm run typecheck
```

Expected: TypeScript fails because the `api` fixture and `support/api.ts`/`support/ui.ts` exports do not exist.

- [ ] **Step 2: Implement the typed backend setup client**

Create `e2e/support/api.ts` with these stable types and methods:

```typescript
import { expect, type APIRequestContext, type APIResponse } from '@playwright/test';

import type { Account } from './ui.js';
import { runtime } from './runtime.js';

export interface Project {
  id: string;
  name: string;
  description: string | null;
  document_count: number;
  conversation_count: number;
}

export interface DocumentRecord {
  id: string;
  title: string;
  source_type: 'pdf' | 'url' | 'youtube';
  source_url: string | null;
  status: 'queued' | 'processing' | 'ready' | 'error';
  error_message: string | null;
  chunk_count: number;
}

export interface DocumentStatus {
  id: string;
  status: 'queued' | 'processing' | 'ready' | 'error';
  error_message: string | null;
  progress: number | null;
}

export interface Conversation {
  id: string;
  project_id: string;
  title: string;
  message_count: number;
}

export interface ConversationDetail {
  id: string;
  project_id: string;
  title: string;
  messages: Array<{
    id: string;
    role: 'user' | 'assistant';
    text: string;
    citations: Array<{
      document_id: string;
      document_title: string;
      chunk_id: string;
      text_preview: string;
    }>;
  }>;
}

export interface QueryResult {
  answer: string;
  sources: Array<{
    id: number;
    document_id: string;
    document_title: string;
    chunk_id: string;
    text_preview: string;
    score: number;
  }>;
  chunks_used: number;
  model_used: string | null;
  conversation_id: string;
}

export class E2EApi {
  private token: string | undefined;

  constructor(private readonly request: APIRequestContext) {}

  private authorization(): Record<string, string> {
    if (!this.token) {
      throw new Error('E2EApi.login must be called before an authenticated request');
    }
    return { Authorization: `Bearer ${this.token}` };
  }

  private async json<T>(response: APIResponse): Promise<T> {
    if (!response.ok()) {
      throw new Error(`${response.url()} returned ${response.status()}: ${await response.text()}`);
    }
    return response.json() as Promise<T>;
  }

  async register(account: Account): Promise<void> {
    await this.json(await this.request.post(`${runtime.apiUrl}/auth/register`, {
      data: account,
    }));
  }

  async login(account: Pick<Account, 'username' | 'password'>): Promise<string> {
    const result = await this.json<{ access_token: string }>(
      await this.request.post(`${runtime.apiUrl}/auth/token`, { form: account }),
    );
    this.token = result.access_token;
    return result.access_token;
  }

  async createProject(name: string, description = ''): Promise<Project> {
    return this.json(await this.request.post(`${runtime.apiUrl}/projects`, {
      headers: this.authorization(),
      data: { name, description },
    }));
  }

  async listProjects(): Promise<Project[]> {
    const result = await this.json<{ projects: Project[] }>(
      await this.request.get(`${runtime.apiUrl}/projects`, { headers: this.authorization() }),
    );
    return result.projects;
  }

  async projectDocumentsResponse(projectId: string): Promise<APIResponse> {
    return this.request.get(`${runtime.apiUrl}/projects/${projectId}/documents`, {
      headers: this.authorization(),
    });
  }

  async listProjectDocuments(projectId: string): Promise<DocumentRecord[]> {
    return this.json(await this.projectDocumentsResponse(projectId));
  }

  async uploadUrl(projectId: string, url: string): Promise<string> {
    const result = await this.json<{ doc_id: string }>(
      await this.request.post(`${runtime.apiUrl}/projects/${projectId}/upload-url`, {
        headers: this.authorization(),
        data: { url, title: url },
      }),
    );
    return result.doc_id;
  }

  async documentStatus(documentId: string): Promise<DocumentStatus> {
    return this.json(await this.request.get(`${runtime.apiUrl}/docs/${documentId}/status`, {
      headers: this.authorization(),
    }));
  }

  async waitForDocumentReady(documentId: string, timeout = 30_000): Promise<DocumentStatus> {
    let latest: DocumentStatus | undefined;
    await expect.poll(async () => {
      latest = await this.documentStatus(documentId);
      if (latest.status === 'error') {
        throw new Error(`Document ${documentId} failed: ${latest.error_message ?? 'unknown error'}`);
      }
      return latest.status;
    }, { timeout, intervals: [250, 500, 1_000] }).toBe('ready');
    return latest as DocumentStatus;
  }

  async createConversation(projectId: string, title: string): Promise<Conversation> {
    return this.json(await this.request.post(`${runtime.apiUrl}/projects/${projectId}/conversations`, {
      headers: this.authorization(),
      data: { title },
    }));
  }

  async listConversations(projectId: string): Promise<Conversation[]> {
    return this.json(await this.request.get(`${runtime.apiUrl}/projects/${projectId}/conversations`, {
      headers: this.authorization(),
    }));
  }

  async conversation(conversationId: string): Promise<ConversationDetail> {
    return this.json(await this.request.get(`${runtime.apiUrl}/conversations/${conversationId}`, {
      headers: this.authorization(),
    }));
  }

  async query(projectId: string, conversationId: string, query: string): Promise<QueryResult> {
    return this.json(await this.request.post(`${runtime.apiUrl}/query`, {
      headers: this.authorization(),
      data: { project_id: projectId, conversation_id: conversationId, query },
    }));
  }
}
```

Keep `projectDocumentsResponse` raw so the ownership test can assert a deliberate 404 without teaching the global diagnostics collector to ignore authorization errors. The UI-driven wrong-password 401 is also safe because diagnostics fail only 5xx responses.

- [ ] **Step 3: Add the typed API fixture**

Replace the fixture type and `base.extend` block in `e2e/support/fixtures.ts`:

```typescript
import { E2EApi } from './api.js';
import { BrowserDiagnostics } from './diagnostics.js';

type Fixtures = {
  api: E2EApi;
  browserDiagnostics: BrowserDiagnostics;
};

export const test = base.extend<Fixtures>({
  api: async ({ request }, use) => {
    await use(new E2EApi(request));
  },
  browserDiagnostics: [async ({ page }, use, testInfo) => {
    const diagnostics = new BrowserDiagnostics();
    diagnostics.install(page);
    await use(diagnostics);
    await diagnostics.verify(testInfo);
  }, { auto: true }],
});
```

Keep the existing `base`/`expect` imports and `export { expect }` statement.

- [ ] **Step 4: Implement account and UI action helpers**

Create `e2e/support/ui.ts`:

```typescript
import { createHash } from 'node:crypto';

import { expect, type Page, type TestInfo } from '@playwright/test';

export interface Account {
  username: string;
  email: string;
  password: string;
}

export function accountFor(testInfo: TestInfo, suffix: string): Account {
  const digest = createHash('sha256')
    .update([
      process.env.E2E_RUN_ID,
      testInfo.project.name,
      testInfo.file,
      testInfo.title,
      testInfo.retry,
      suffix,
    ].join('|'))
    .digest('hex')
    .slice(0, 18);
  return {
    username: `e2e_${digest}`,
    email: `e2e_${digest}@example.test`,
    password: 'E2E-pass-7319!',
  };
}

export async function loginThroughUi(page: Page, account: Account): Promise<void> {
  await page.goto('/login');
  await page.getByLabel('Username').fill(account.username);
  await page.getByLabel('Password').fill(account.password);
  const tokenResponse = page.waitForResponse(
    (response) => response.url().endsWith('/api/auth/token') && response.request().method() === 'POST',
  );
  await page.getByRole('button', { name: 'Login', exact: true }).click();
  expect((await tokenResponse).status()).toBe(200);
  await expect(page).toHaveURL('/');
  await expect(page.getByRole('button', { name: 'User menu' })).toBeVisible();
}

export async function registerThroughUi(page: Page, account: Account): Promise<void> {
  await page.goto('/login');
  await page.getByRole('button', { name: 'Register', exact: true }).click();
  await page.getByLabel('Username').fill(account.username);
  await page.getByLabel('Email').fill(account.email);
  await page.getByLabel('Password', { exact: true }).fill(account.password);
  await page.getByLabel('Confirm Password').fill(account.password);
  const registration = page.waitForResponse(
    (response) => response.url().endsWith('/api/auth/register') && response.request().method() === 'POST',
  );
  const tokenResponse = page.waitForResponse(
    (response) => response.url().endsWith('/api/auth/token') && response.request().method() === 'POST',
  );
  await page.getByRole('button', { name: 'Register', exact: true }).click();
  expect((await registration).status()).toBe(200);
  expect((await tokenResponse).status()).toBe(200);
  await expect(page).toHaveURL('/');
}

export async function createProjectThroughUi(
  page: Page,
  name: string,
  description: string,
): Promise<{ id: string; name: string }> {
  await page.getByRole('banner').getByRole('button', { name: 'New Project', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'Create New Project' });
  await dialog.getByLabel('Project Name').fill(name);
  await dialog.getByLabel('Project Description').fill(description);
  const created = page.waitForResponse(
    (response) => response.url().endsWith('/api/projects') && response.request().method() === 'POST',
  );
  await dialog.getByRole('button', { name: 'Create Project', exact: true }).click();
  const result = await created;
  expect(result.status()).toBe(200);
  return result.json() as Promise<{ id: string; name: string }>;
}

export async function signOutThroughUi(page: Page): Promise<void> {
  await page.getByRole('button', { name: 'User menu' }).click();
  await page.getByRole('button', { name: 'Sign out' }).click();
  await expect(page).toHaveURL('/login');
}

export async function openAddSourceDialog(page: Page) {
  const sources = page.getByRole('complementary', { name: 'Sources' });
  await sources.getByRole('button', { name: 'Add Source', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'Add Source' });
  await expect(dialog).toBeVisible();
  return dialog;
}
```

Run:

```bash
npm run typecheck
npm test -- tests/api-helper.spec.ts
```

Expected: the helper contract passes against real FastAPI authentication and SQLite persistence.

- [ ] **Step 5: Write the four independent authentication workflows**

Create `e2e/tests/auth.spec.ts`:

```typescript
import { test, expect } from '../support/fixtures.js';
import {
  accountFor,
  loginThroughUi,
  registerThroughUi,
  signOutThroughUi,
} from '../support/ui.js';

test('redirects an anonymous workspace visit to login', async ({ page }) => {
  await page.goto('/');
  await expect(page).toHaveURL('/login');
  await expect(page.getByRole('button', { name: 'Login', exact: true })).toBeVisible();
});

test('registers and restores the signed-in session after reload', async ({ page }, testInfo) => {
  const account = accountFor(testInfo, 'register');
  await registerThroughUi(page, account);

  await expect(page.getByRole('button', { name: 'User menu' })).toBeVisible();
  const stored = await page.evaluate(() => ({
    access: localStorage.getItem('access_token'),
    auth: localStorage.getItem('auth_token'),
    user: localStorage.getItem('user'),
  }));
  expect(stored.access).toBeTruthy();
  expect(stored.auth).toBe(stored.access);
  expect(JSON.parse(stored.user ?? '{}')).toMatchObject({ username: account.username });

  await page.reload();
  await expect(page).toHaveURL('/');
  await expect(page.getByRole('button', { name: 'User menu' })).toBeVisible();
});

test('rejects a wrong password without creating browser session state', async ({ api, page }, testInfo) => {
  const account = accountFor(testInfo, 'wrong-password');
  await api.register(account);
  await page.goto('/login');
  await page.getByLabel('Username').fill(account.username);
  await page.getByLabel('Password').fill('incorrect-password');
  const rejected = page.waitForResponse(
    (response) => response.url().endsWith('/api/auth/token') && response.status() === 401,
  );
  await page.getByRole('button', { name: 'Login', exact: true }).click();
  await rejected;

  await expect(page.getByText('Incorrect username or password', { exact: true })).toBeVisible();
  expect(await page.evaluate(() => [
    localStorage.getItem('access_token'),
    localStorage.getItem('auth_token'),
    localStorage.getItem('user'),
  ])).toEqual([null, null, null]);
  expect((await page.context().cookies()).find((cookie) => cookie.name === 'auth_token')).toBeUndefined();
});

test('signs out, clears the session, and protects browser back navigation', async ({ api, page }, testInfo) => {
  const account = accountFor(testInfo, 'logout');
  await api.register(account);
  await loginThroughUi(page, account);

  await signOutThroughUi(page);
  expect(await page.evaluate(() => [
    localStorage.getItem('access_token'),
    localStorage.getItem('auth_token'),
    localStorage.getItem('user'),
  ])).toEqual([null, null, null]);
  expect((await page.context().cookies()).find((cookie) => cookie.name === 'auth_token')).toBeUndefined();

  await page.goBack();
  await expect(page).toHaveURL('/login');
});
```

Run:

```bash
npm test -- tests/auth.spec.ts
```

Expected: four tests pass. The negative 401 is observed explicitly and does not create any storage/cookie state.

- [ ] **Step 6: Write project creation, persistence, and ownership tests**

Create `e2e/tests/projects.spec.ts`:

```typescript
import { test, expect } from '../support/fixtures.js';
import {
  accountFor,
  createProjectThroughUi,
  loginThroughUi,
  signOutThroughUi,
} from '../support/ui.js';

test('creates, selects, and reloads a project from the backend', async ({ api, page }, testInfo) => {
  const account = accountFor(testInfo, 'project-persistence');
  await api.register(account);
  await api.login(account);
  await loginThroughUi(page, account);
  const name = `E2E Project ${testInfo.retry}`;
  const created = await createProjectThroughUi(page, name, 'Persistence coverage');

  await expect(page.getByRole('combobox', { name: 'Select a project' })).toHaveValue(created.id);
  await expect(page.getByRole('heading', { name, exact: true })).toBeVisible();

  const projectsLoaded = page.waitForResponse(
    (response) => response.url().endsWith('/api/projects') && response.request().method() === 'GET',
  );
  await page.reload();
  expect((await projectsLoaded).status()).toBe(200);
  await expect(page.getByRole('combobox', { name: 'Select a project' })).toHaveValue(created.id);
  await expect(page.getByRole('heading', { name, exact: true })).toBeVisible();
  expect((await api.listProjects()).map((project) => project.id)).toContain(created.id);
});

test('never exposes another account project or source', async ({ api, page }, testInfo) => {
  const accountA = accountFor(testInfo, 'owner-a');
  const accountB = accountFor(testInfo, 'owner-b');
  await api.register(accountA);
  await api.login(accountA);
  const projectA = await api.createProject('Account A Observatory', 'Private A data');
  const documentA = await api.uploadUrl(projectA.id, 'https://e2e.invalid/observatory');
  await api.waitForDocumentReady(documentA);

  await api.register(accountB);
  await api.login(accountB);
  const projectB = await api.createProject('Account B Notebook', 'Private B data');

  await loginThroughUi(page, accountA);
  await expect(page.getByRole('heading', { name: projectA.name, exact: true })).toBeVisible();
  await expect(page.getByText('E2E Observatory Field Notes', { exact: true })).toBeVisible();
  await signOutThroughUi(page);
  await page.reload();

  const projectsLoaded = page.waitForResponse(
    (response) => response.url().endsWith('/api/projects') && response.request().method() === 'GET',
  );
  await loginThroughUi(page, accountB);
  expect((await projectsLoaded).status()).toBe(200);
  await expect(page.getByRole('heading', { name: projectB.name, exact: true })).toBeVisible();
  await expect(page.getByText(projectA.name, { exact: true })).toHaveCount(0);
  await expect(page.getByText('E2E Observatory Field Notes', { exact: true })).toHaveCount(0);

  const forbidden = await api.projectDocumentsResponse(projectA.id);
  expect(forbidden.status()).toBe(404);
});
```

Run:

```bash
npm test -- tests/projects.spec.ts
```

Expected: both tests pass. The account switch crosses a full `/login` reload before B signs in, preventing stale in-memory Zustand data from being mistaken for an authorization result; the direct 404 proves backend ownership enforcement as well.

- [ ] **Step 7: Run the Task 4 regression slice and commit**

```bash
npm run typecheck
npm test -- tests/runtime.spec.ts tests/api-helper.spec.ts tests/auth.spec.ts tests/projects.spec.ts
git add e2e/support/api.ts e2e/support/ui.ts e2e/support/fixtures.ts e2e/tests/api-helper.spec.ts e2e/tests/auth.spec.ts e2e/tests/projects.spec.ts
git commit -m "test: cover authentication and project e2e flows"
```

Expected: the selected Playwright tests pass in one worker, and no account collision occurs when a single test is retried with `--retries=1`.

---

### Task 5: Cover PDF, URL, and YouTube source lifecycles

**Files:**

- Create: `e2e/support/pdf.ts`
- Modify: `e2e/support/ui.ts`
- Create: `e2e/tests/sources.spec.ts`

**Interfaces:**

- Consumes: Task 4's `E2EApi`, `accountFor`, `loginThroughUi`, and `openAddSourceDialog`; Task 2's fixed URL title `E2E Observatory Field Notes` and fixed video id `e2eOrbit7319`.
- Produces: `generatePdf(outputPath: string, title: string, fact: string) -> Promise<void>`, `setupWorkspace(api: E2EApi, page: Page, testInfo: TestInfo, suffix: string) -> Promise<{ account: Account; project: Project }>`, `setupReadyUrlWorkspace(api: E2EApi, page: Page, testInfo: TestInfo, suffix: string) -> Promise<{ account: Account; project: Project; documentId: string }>`, and `sourceRow(page: Page, title: string) -> Locator`.
- Source deletion assertions target the project membership endpoint and list. The UI calls `DELETE /api/projects/{projectId}/documents/{documentId}`; it does not promise that the underlying `/api/docs/{id}` row is destroyed.

- [ ] **Step 1: Add a failing PDF fixture contract test**

Create `e2e/tests/pdf-fixture.spec.ts`:

```typescript
import { readFile } from 'node:fs/promises';

import { PDFDocument } from 'pdf-lib';

import { test, expect } from '../support/fixtures.js';
import { generatePdf } from '../support/pdf.js';

test('generates a valid searchable PDF inside the test output', async ({}, testInfo) => {
  const outputPath = testInfo.outputPath('generated-observatory.pdf');
  await generatePdf(outputPath, 'Observatory Field Notes', 'The access code is ORBIT-7319.');

  const bytes = await readFile(outputPath);
  const document = await PDFDocument.load(bytes);
  expect(document.getPageCount()).toBe(1);
  expect(bytes.subarray(0, 4).toString('ascii')).toBe('%PDF');
});
```

Run:

```bash
npm run typecheck
```

Expected: TypeScript fails because `support/pdf.ts` does not exist.

- [ ] **Step 2: Implement valid per-test PDF generation**

Create `e2e/support/pdf.ts`:

```typescript
import { writeFile } from 'node:fs/promises';

import { PDFDocument, StandardFonts, rgb } from 'pdf-lib';

export async function generatePdf(
  outputPath: string,
  title: string,
  fact: string,
): Promise<void> {
  const document = await PDFDocument.create();
  const font = await document.embedFont(StandardFonts.Helvetica);
  const bold = await document.embedFont(StandardFonts.HelveticaBold);
  const page = document.addPage([612, 792]);
  page.drawText(title, { x: 72, y: 700, size: 20, font: bold, color: rgb(0.1, 0.1, 0.1) });
  page.drawText(fact, { x: 72, y: 650, size: 12, font, color: rgb(0.1, 0.1, 0.1) });
  page.drawText('Generated locally for deterministic browser testing.', {
    x: 72,
    y: 625,
    size: 10,
    font,
    color: rgb(0.3, 0.3, 0.3),
  });
  await writeFile(outputPath, await document.save());
}
```

Run:

```bash
npm test -- tests/pdf-fixture.spec.ts
```

Expected: the generated file parses as a one-page PDF and remains inside that test's Playwright output directory.

- [ ] **Step 3: Add workspace, ready-source, and source-row helpers**

Extend `e2e/support/ui.ts` imports and exports:

```typescript
import { expect, type Locator, type Page, type TestInfo } from '@playwright/test';

import type { E2EApi, Project } from './api.js';

export async function setupWorkspace(
  api: E2EApi,
  page: Page,
  testInfo: TestInfo,
  suffix: string,
): Promise<{ account: Account; project: Project }> {
  const account = accountFor(testInfo, suffix);
  await api.register(account);
  await api.login(account);
  const project = await api.createProject(`E2E ${suffix} ${testInfo.retry}`, 'Browser workflow');
  await loginThroughUi(page, account);
  await expect(page.getByRole('heading', { name: project.name, exact: true })).toBeVisible();
  return { account, project };
}

export function sourceRow(page: Page, title: string): Locator {
  const sources = page.getByRole('complementary', { name: 'Sources' });
  return sources
    .getByText(title, { exact: true })
    .locator('..')
    .locator('..')
    .locator('..');
}

export async function setupReadyUrlWorkspace(
  api: E2EApi,
  page: Page,
  testInfo: TestInfo,
  suffix: string,
): Promise<{ account: Account; project: Project; documentId: string }> {
  const { account, project } = await setupWorkspace(api, page, testInfo, suffix);
  const documentId = await api.uploadUrl(project.id, 'https://e2e.invalid/observatory');
  await api.waitForDocumentReady(documentId);
  const documentsLoaded = page.waitForResponse(
    (response) => response.url().endsWith(`/api/projects/${project.id}/documents`)
      && response.request().method() === 'GET',
  );
  await page.reload();
  expect((await documentsLoaded).status()).toBe(200);
  await expect(sourceRow(page, 'E2E Observatory Field Notes').getByText('Ready', { exact: true }))
    .toBeVisible({ timeout: 10_000 });
  return { account, project, documentId };
}
```

Merge the type-only `Page`/`TestInfo` import with the existing import instead of leaving duplicate imports. `sourceRow` climbs from the `<h3>` through its content and flex wrappers to the source-card `<div>` that owns the preview/delete buttons. The ready-source helper reloads after API ingestion and waits for the real project-documents request because the frontend status watcher only polls document ids already present in Zustand; without the reload, an API-created source can never enter the browser store.

- [ ] **Step 4: Write the PDF upload, readiness, protected preview, and unlink test**

Create `e2e/tests/sources.spec.ts` with the PDF case:

```typescript
import { test, expect } from '../support/fixtures.js';
import { generatePdf } from '../support/pdf.js';
import { openAddSourceDialog, setupWorkspace, sourceRow } from '../support/ui.js';

test('uploads, indexes, previews, and removes a PDF source', async ({ api, page }, testInfo) => {
  const { project } = await setupWorkspace(api, page, testInfo, 'pdf-source');
  const filename = 'observatory-field-notes.pdf';
  const filePath = testInfo.outputPath(filename);
  await generatePdf(filePath, 'Observatory Field Notes', 'The observatory access code is ORBIT-7319.');

  const dialog = await openAddSourceDialog(page);
  await dialog.locator('input[type="file"]').setInputFiles(filePath);
  const uploadResponse = page.waitForResponse(
    (response) => response.url().endsWith(`/api/projects/${project.id}/upload`)
      && response.request().method() === 'POST',
  );
  await dialog.getByRole('button', { name: 'Upload 1 file(s)', exact: true }).click();
  const uploaded = await uploadResponse;
  expect(uploaded.status()).toBe(200);
  const { doc_id: documentId } = await uploaded.json() as { doc_id: string };

  await api.waitForDocumentReady(documentId);
  const row = sourceRow(page, filename);
  await expect(row.getByText('Ready', { exact: true })).toBeVisible({ timeout: 10_000 });

  await row.hover();
  const protectedFile = page.waitForResponse(
    (response) => response.url().endsWith(`/api/docs/${documentId}/file`) && response.status() === 200,
  );
  await row.getByRole('button', { name: 'Preview document' }).click();
  await protectedFile;
  const preview = page.getByRole('dialog', { name: filename });
  await expect(preview.locator(`iframe[title="${filename}"]`)).toHaveAttribute('src', /^blob:/);
  await preview.getByRole('button', { name: 'Close document preview dialog' }).click();

  page.once('dialog', async (confirmation) => {
    expect(confirmation.message()).toBe('Are you sure you want to delete this document?');
    await confirmation.accept();
  });
  const removed = page.waitForResponse(
    (response) => response.url().endsWith(`/api/projects/${project.id}/documents/${documentId}`)
      && response.request().method() === 'DELETE',
  );
  await row.hover();
  await row.getByRole('button', { name: 'Delete document' }).click();
  expect((await removed).status()).toBe(200);
  await expect(sourceRow(page, filename)).toHaveCount(0);
  expect((await api.listProjectDocuments(project.id)).map((document) => document.id)).not.toContain(documentId);
});
```

Run:

```bash
npm test -- tests/sources.spec.ts --grep "PDF source"
```

Expected: the test observes queued/processing asynchronously through the API, reaches visible `Ready`, loads authenticated PDF bytes into a blob iframe, and removes only the project's membership/list item.

- [ ] **Step 5: Add the fixed URL lifecycle and search test**

Append to `e2e/tests/sources.spec.ts`:

```typescript
test('imports, searches, and removes a controlled URL source', async ({ api, page }, testInfo) => {
  const { project } = await setupWorkspace(api, page, testInfo, 'url-source');
  const dialog = await openAddSourceDialog(page);
  await dialog.getByRole('button', { name: 'URL', exact: true }).click();
  await dialog.getByPlaceholder('Enter website URL...').fill('https://e2e.invalid/observatory');
  const importResponse = page.waitForResponse(
    (response) => response.url().endsWith(`/api/projects/${project.id}/upload-url`)
      && response.request().method() === 'POST',
  );
  await dialog.getByRole('button', { name: 'Add', exact: true }).click();
  const imported = await importResponse;
  expect(imported.status()).toBe(200);
  const { doc_id: documentId } = await imported.json() as { doc_id: string };

  await api.waitForDocumentReady(documentId);
  const title = 'E2E Observatory Field Notes';
  const row = sourceRow(page, title);
  await expect(row.getByText('Ready', { exact: true })).toBeVisible({ timeout: 10_000 });
  await page.getByLabel('Search sources').fill('Observatory');
  await expect(row).toBeVisible();
  await page.getByLabel('Search sources').fill('missing-source');
  await expect(row).toHaveCount(0);
  await page.getByLabel('Search sources').clear();

  const visibleRow = sourceRow(page, title);
  page.once('dialog', (confirmation) => confirmation.accept());
  const removed = page.waitForResponse(
    (response) => response.url().endsWith(`/api/projects/${project.id}/documents/${documentId}`)
      && response.request().method() === 'DELETE',
  );
  await visibleRow.hover();
  await visibleRow.getByRole('button', { name: 'Delete document' }).click();
  expect((await removed).status()).toBe(200);
  await expect(sourceRow(page, title)).toHaveCount(0);
});
```

Do not open the URL preview: it intentionally renders the external URL in an iframe and would make public network behavior part of a deterministic test.

Run:

```bash
npm test -- tests/sources.spec.ts --grep "controlled URL"
```

Expected: the final backend-supplied title is searchable and removed without any request to `e2e.invalid`.

- [ ] **Step 6: Add the fixed YouTube transcript lifecycle test**

Append:

```typescript
test('imports a controlled YouTube transcript and reaches ready', async ({ api, page }, testInfo) => {
  const { project } = await setupWorkspace(api, page, testInfo, 'youtube-source');
  const dialog = await openAddSourceDialog(page);
  await dialog.getByRole('button', { name: 'YouTube', exact: true }).click();
  await dialog.getByPlaceholder('Enter YouTube URL...').fill(
    'https://www.youtube.com/watch?v=e2eOrbit7319',
  );
  const importResponse = page.waitForResponse(
    (response) => response.url().endsWith(`/api/projects/${project.id}/upload-youtube`)
      && response.request().method() === 'POST',
  );
  await dialog.getByRole('button', { name: 'Add', exact: true }).click();
  const imported = await importResponse;
  expect(imported.status()).toBe(200);
  const { doc_id: documentId } = await imported.json() as { doc_id: string };

  await api.waitForDocumentReady(documentId);
  const row = sourceRow(page, 'YouTube: e2eOrbit7319');
  await expect(row.getByText('Ready', { exact: true })).toBeVisible({ timeout: 10_000 });
  const persisted = (await api.listProjectDocuments(project.id)).find(
    (document) => document.id === documentId,
  );
  expect(persisted).toMatchObject({
    source_type: 'youtube',
    title: 'YouTube: e2eOrbit7319',
    status: 'ready',
  });
});
```

Do not assert exact transcript segment timestamps: the current document service stores only the segment count and chunks the resulting text.

Run:

```bash
npm test -- tests/sources.spec.ts --grep "YouTube transcript"
```

Expected: the fixed adapter is used, the source is indexed, and no YouTube network request occurs.

- [ ] **Step 7: Run source regressions and commit**

```bash
npm run typecheck
npm test -- tests/pdf-fixture.spec.ts tests/sources.spec.ts
git add e2e/support/pdf.ts e2e/support/ui.ts e2e/tests/pdf-fixture.spec.ts e2e/tests/sources.spec.ts
git commit -m "test: cover source ingestion e2e flows"
```

Expected: four tests pass without fixed sleeps, external iframe loads, or artifacts outside the isolated run root.

---

### Task 6: Cover cited chat persistence and conversation CRUD

**Files:**

- Modify: `e2e/support/api.ts`
- Create: `e2e/tests/chat.spec.ts`

**Interfaces:**

- Consumes: Task 4's setup client and Task 5's `setupReadyUrlWorkspace`; the query response must expose `model_used`, `sources[].text_preview`, and `conversation_id`.
- Produces: `E2EApi.renameConversation(id, title)`, `E2EApi.deleteConversation(id)`, and browser coverage for conversation/message/citation persistence.
- Reload does not restore Zustand's `currentConversation`; the persistence test must wait for the conversation list and explicitly click the known conversation after reload.

- [ ] **Step 1: Write a failing API CRUD extension test**

Append to `e2e/tests/api-helper.spec.ts`:

```typescript
test('renames and deletes a conversation through authenticated APIs', async ({ api }, testInfo) => {
  const account = accountFor(testInfo, 'conversation-api');
  await api.register(account);
  await api.login(account);
  const project = await api.createProject('Conversation API Project');
  const conversation = await api.createConversation(project.id, 'Initial title');

  const renamed = await api.renameConversation(conversation.id, 'Renamed title');
  expect(renamed.title).toBe('Renamed title');
  await api.deleteConversation(conversation.id);
  expect((await api.listConversations(project.id)).map((item) => item.id)).not.toContain(conversation.id);
});
```

Run:

```bash
npm run typecheck
```

Expected: TypeScript fails because the two `E2EApi` methods do not exist.

- [ ] **Step 2: Implement authenticated conversation update/delete helpers**

Add to `E2EApi` in `e2e/support/api.ts`:

```typescript
async renameConversation(conversationId: string, title: string): Promise<Conversation> {
  return this.json(await this.request.put(`${runtime.apiUrl}/conversations/${conversationId}`, {
    headers: this.authorization(),
    data: { title },
  }));
}

async deleteConversation(conversationId: string): Promise<void> {
  await this.json(await this.request.delete(`${runtime.apiUrl}/conversations/${conversationId}`, {
    headers: this.authorization(),
  }));
}
```

Run:

```bash
npm test -- tests/api-helper.spec.ts --grep "renames and deletes"
```

Expected: the API CRUD extension test passes and leaves no conversation row in the project listing.

- [ ] **Step 3: Write the chat, citation, and reload-persistence workflow**

Create `e2e/tests/chat.spec.ts`:

```typescript
import { test, expect } from '../support/fixtures.js';
import { setupReadyUrlWorkspace, setupWorkspace } from '../support/ui.js';

test('answers from a ready source and persists messages and citation after reload', async ({
  api,
  page,
}, testInfo) => {
  const { project, documentId } = await setupReadyUrlWorkspace(
    api,
    page,
    testInfo,
    'cited-chat',
  );

  const question = 'What is the observatory access code?';
  await page.getByPlaceholder('Ask anything about your sources...').fill(question);
  const queryResponse = page.waitForResponse(
    (response) => response.url().endsWith('/api/query') && response.request().method() === 'POST',
  );
  await page.getByRole('button', { name: 'Send message' }).click();
  const rawResponse = await queryResponse;
  expect(rawResponse.status()).toBe(200);
  const result = await rawResponse.json() as {
    answer: string;
    model_used: string;
    conversation_id: string;
    sources: Array<{ document_id: string; document_title: string; text_preview: string }>;
  };

  expect(result.model_used).toBe('fallback');
  expect(result.answer).toContain('ORBIT-7319');
  expect(result.sources).toEqual(expect.arrayContaining([
    expect.objectContaining({
      document_id: documentId,
      document_title: 'E2E Observatory Field Notes',
      text_preview: expect.stringContaining('ORBIT-7319'),
    }),
  ]));
  await expect(page.getByText(question, { exact: true })).toBeVisible();
  await expect(page.getByText('ORBIT-7319', { exact: false }).first()).toBeVisible();
  const sourcesLabel = page.getByText('Sources:', { exact: true }).last();
  await expect(sourcesLabel.locator('..')).toContainText('E2E Observatory Field Notes');

  const conversationTitle = `${question.substring(0, 50)}...`;
  const listReloaded = page.waitForResponse(
    (response) => response.url().endsWith(`/api/projects/${project.id}/conversations`)
      && response.request().method() === 'GET',
  );
  await page.reload();
  expect((await listReloaded).status()).toBe(200);
  const conversationItem = page
    .getByRole('region', { name: 'Conversations panel content' })
    .getByText(conversationTitle, { exact: true });
  await expect(conversationItem).toBeVisible();
  const detailReloaded = page.waitForResponse(
    (response) => response.url().endsWith(`/api/conversations/${result.conversation_id}`)
      && response.request().method() === 'GET',
  );
  await conversationItem.click();
  expect((await detailReloaded).status()).toBe(200);

  await expect(page.getByText(question, { exact: true })).toBeVisible();
  await expect(page.getByText('ORBIT-7319', { exact: false }).first()).toBeVisible();
  await expect(page.getByText('Sources:', { exact: true }).last().locator('..'))
    .toContainText('E2E Observatory Field Notes');

  const persisted = await api.conversation(result.conversation_id);
  expect(persisted.messages.map((message) => message.role)).toEqual(
    expect.arrayContaining(['user', 'assistant']),
  );
  expect(persisted.messages).toHaveLength(2);
  const userMessage = persisted.messages.find((message) => message.role === 'user');
  const assistantMessage = persisted.messages.find((message) => message.role === 'assistant');
  expect(userMessage?.text).toBe(question);
  expect(assistantMessage?.text).toContain('ORBIT-7319');
  expect(assistantMessage?.citations).toEqual(expect.arrayContaining([
    expect.objectContaining({
      document_id: documentId,
      document_title: 'E2E Observatory Field Notes',
    }),
  ]));
});
```

Run:

```bash
npm test -- tests/chat.spec.ts --grep "persists messages"
```

Expected: the fallback answer contains the retrieved unique fact, the source citation is visible, and both messages plus citation are identical after explicit conversation reselection.

- [ ] **Step 4: Add the independent browser conversation CRUD workflow**

Append to `e2e/tests/chat.spec.ts`:

```typescript
test('creates, renames, selects, and deletes conversations', async ({ api, page }, testInfo) => {
  const { project } = await setupWorkspace(api, page, testInfo, 'conversation-crud');
  const fullTextNewButton = page
    .getByRole('button', { name: 'New Conversation' })
    .filter({ hasText: 'New Conversation' })
    .first();
  const createdResponse = page.waitForResponse(
    (response) => response.url().endsWith(`/api/projects/${project.id}/conversations`)
      && response.request().method() === 'POST',
  );
  await fullTextNewButton.click();
  const created = await createdResponse;
  expect(created.status()).toBe(200);
  const first = await created.json() as { id: string };

  const panel = page.getByRole('region', { name: 'Conversations panel content' });
  const initialTitle = panel.getByText('New Conversation', { exact: true });
  const initialRow = initialTitle.locator('..').locator('..').locator('..');
  await initialRow.hover();
  await initialRow.getByRole('button', { name: 'Rename conversation' }).click();
  const editingInput = panel.locator('input[type="text"]');
  const editingRow = editingInput.locator('..');
  const renamedResponse = page.waitForResponse(
    (response) => response.url().endsWith(`/api/conversations/${first.id}`)
      && response.request().method() === 'PUT',
  );
  await editingInput.fill('Renamed E2E Conversation');
  await editingRow.getByRole('button', { name: 'Save conversation name' }).click();
  expect((await renamedResponse).status()).toBe(200);
  await expect(panel.getByText('Renamed E2E Conversation', { exact: true })).toBeVisible();

  const secondResponse = page.waitForResponse(
    (response) => response.url().endsWith(`/api/projects/${project.id}/conversations`)
      && response.request().method() === 'POST',
  );
  await fullTextNewButton.click();
  expect((await secondResponse).status()).toBe(200);
  const selectedResponse = page.waitForResponse(
    (response) => response.url().endsWith(`/api/conversations/${first.id}`)
      && response.request().method() === 'GET',
  );
  const renamedTitle = panel.getByText('Renamed E2E Conversation', { exact: true });
  await renamedTitle.click();
  expect((await selectedResponse).status()).toBe(200);

  const renamedRow = renamedTitle.locator('..').locator('..').locator('..');
  page.once('dialog', async (confirmation) => {
    expect(confirmation.message()).toBe('Are you sure you want to delete this conversation?');
    await confirmation.accept();
  });
  const deletedResponse = page.waitForResponse(
    (response) => response.url().endsWith(`/api/conversations/${first.id}`)
      && response.request().method() === 'DELETE',
  );
  await renamedRow.hover();
  await renamedRow.getByRole('button', { name: 'Delete conversation' }).click();
  expect((await deletedResponse).status()).toBe(200);
  await expect(panel.getByText('Renamed E2E Conversation', { exact: true })).toHaveCount(0);
  expect((await api.listConversations(project.id)).map((conversation) => conversation.id))
    .not.toContain(first.id);
});
```

Run:

```bash
npm test -- tests/chat.spec.ts --grep "creates, renames"
```

Expected: all four operations produce the matching API response, and the deleted id is absent from persisted project conversations.

- [ ] **Step 5: Run chat/conversation regressions and commit**

```bash
npm run typecheck
npm test -- tests/api-helper.spec.ts tests/chat.spec.ts
git add e2e/support/api.ts e2e/tests/api-helper.spec.ts e2e/tests/chat.spec.ts
git commit -m "test: cover chat and conversation e2e flows"
```

Expected: helper, cited-chat, and conversation CRUD tests pass with no sleep and with full reload persistence evidence.

---

### Task 7: Cover Studio outputs, exports, and theme persistence

**Files:**

- Create: `e2e/tests/studio-and-settings.spec.ts`

**Interfaces:**

- Consumes: Task 5's `setupReadyUrlWorkspace` and Task 6's conversation/query APIs.
- Produces: seven independent browser tests: mind map, report download, project export, conversation export, video fallback, audio unsupported fallback, and dark-theme persistence.
- Every download listener and native dialog listener must be registered before the click that emits it.

- [ ] **Step 1: Write the mind-map rendering test**

Create `e2e/tests/studio-and-settings.spec.ts` with shared imports and the first test:

```typescript
import { readFile } from 'node:fs/promises';

import { test, expect } from '../support/fixtures.js';
import { setupReadyUrlWorkspace, setupWorkspace } from '../support/ui.js';

test('renders a fallback mind map from ready source structure', async ({ api, page }, testInfo) => {
  const { project } = await setupReadyUrlWorkspace(api, page, testInfo, 'mind-map');
  const responsePromise = page.waitForResponse(
    (response) => response.url().endsWith(`/api/projects/${project.id}/mindmap`)
      && response.request().method() === 'GET',
  );
  await page
    .getByRole('complementary', { name: 'Studio' })
    .getByRole('button', { name: 'Mind map', exact: true })
    .click();
  const response = await responsePromise;
  expect(response.status()).toBe(200);
  expect(await response.json()).toMatchObject({
    project_id: project.id,
    project_name: project.name,
    model_used: 'fallback',
  });

  const dialog = page.getByRole('dialog', { name: `${project.name} mind map` });
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText(
    'Topics taken from document structure rather than from a language model.',
  );
  await expect(dialog).toContainText('Observatory Operations');
  await dialog.getByRole('button', { name: 'Close mind map dialog', exact: true }).click();
});
```

Run:

```bash
npm test -- tests/studio-and-settings.spec.ts --grep "mind map"
```

Expected: the real mind-map endpoint returns fallback provenance and the dialog renders a node derived from the controlled source heading.

- [ ] **Step 2: Add the report download test**

Append:

```typescript
test('downloads a Markdown project report', async ({ api, page }, testInfo) => {
  const { project } = await setupReadyUrlWorkspace(api, page, testInfo, 'report');
  const reportResponse = page.waitForResponse(
    (response) => response.url().endsWith(`/api/export/project/${project.id}/summary`),
  );
  const downloadPromise = page.waitForEvent('download');
  await page
    .getByRole('complementary', { name: 'Studio' })
    .getByRole('button', { name: 'Report', exact: true })
    .click();
  expect((await reportResponse).status()).toBe(200);
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe(`${project.name} report.md`);
  const savedPath = await download.path();
  expect(savedPath).not.toBeNull();
  expect(await readFile(savedPath as string, 'utf8')).toContain(`# Project Summary: ${project.name}`);
});
```

Run:

```bash
npm test -- tests/studio-and-settings.spec.ts --grep "project report"
```

Expected: the named HTTP response and browser download both complete, and the downloaded Markdown identifies the project.

- [ ] **Step 3: Add independent project and conversation export tests**

Append the project export test:

```typescript
test('exports the current project as Markdown', async ({ api, page }, testInfo) => {
  const { project } = await setupReadyUrlWorkspace(api, page, testInfo, 'project-export');
  await page.getByRole('banner').getByRole('button', { name: 'Export', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'Export Project' });
  await dialog.getByRole('radio', { name: /MARKDOWN/ }).check();
  const responsePromise = page.waitForResponse(
    (response) => response.url().includes(`/api/export/project/${project.id}?format=markdown`),
  );
  const downloadPromise = page.waitForEvent('download');
  await dialog.getByRole('button', { name: 'Export', exact: true }).click();
  expect((await responsePromise).status()).toBe(200);
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe(`${project.name.replace(/[^a-z0-9]/gi, '_')}.markdown`);
  const savedPath = await download.path();
  expect(savedPath).not.toBeNull();
  expect(await readFile(savedPath as string, 'utf8')).toContain(project.name);
});
```

Append the conversation export test:

```typescript
test('exports the selected conversation as Markdown', async ({ api, page }, testInfo) => {
  const { project } = await setupReadyUrlWorkspace(api, page, testInfo, 'conversation-export');
  const conversation = await api.createConversation(project.id, 'Exportable Conversation');
  await api.query(project.id, conversation.id, 'What is the observatory access code?');
  const conversationsLoaded = page.waitForResponse(
    (response) => response.url().endsWith(`/api/projects/${project.id}/conversations`)
      && response.request().method() === 'GET',
  );
  await page.reload();
  await conversationsLoaded;
  const detailLoaded = page.waitForResponse(
    (response) => response.url().endsWith(`/api/conversations/${conversation.id}`),
  );
  await page
    .getByRole('region', { name: 'Conversations panel content' })
    .getByText(conversation.title, { exact: true })
    .click();
  await detailLoaded;

  await page.getByRole('banner').getByRole('button', { name: 'Export', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'Export Conversation' });
  await dialog.getByRole('radio', { name: /MARKDOWN/ }).check();
  const responsePromise = page.waitForResponse(
    (response) => response.url().includes(`/api/export/conversation/${conversation.id}?format=markdown`),
  );
  const downloadPromise = page.waitForEvent('download');
  await dialog.getByRole('button', { name: 'Export', exact: true }).click();
  expect((await responsePromise).status()).toBe(200);
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe('Exportable_Conversation.markdown');
  const savedPath = await download.path();
  expect(savedPath).not.toBeNull();
  const markdown = await readFile(savedPath as string, 'utf8');
  expect(markdown).toContain('What is the observatory access code?');
  expect(markdown).toContain('ORBIT-7319');
});
```

Run:

```bash
npm test -- tests/studio-and-settings.spec.ts --grep "exports"
```

Expected: each independent test opens the correct dialog type, hits the correct ownership-scoped route, and validates both the browser filename and downloaded contents.

- [ ] **Step 4: Add deterministic video and audio fallback tests**

Append:

```typescript
test('renders the silent fallback video summary', async ({ api, page }, testInfo) => {
  await page.addInitScript(() => {
    Object.defineProperty(window, 'speechSynthesis', { configurable: true, value: undefined });
  });
  const { project } = await setupReadyUrlWorkspace(api, page, testInfo, 'video-summary');
  const responsePromise = page.waitForResponse(
    (response) => response.url().endsWith(`/api/projects/${project.id}/video-summary`),
  );
  await page
    .getByRole('complementary', { name: 'Studio' })
    .getByRole('button', { name: 'Video summary', exact: true })
    .click();
  const response = await responsePromise;
  expect(response.status()).toBe(200);
  expect(await response.json()).toMatchObject({ model_used: 'fallback' });

  const dialog = page.getByRole('dialog', { name: `${project.name} video summary` });
  await expect(dialog).toContainText(
    'Narration taken from document structure rather than from a language model.',
  );
  await expect(dialog).toContainText(/Scene 1 of \d+/);
  await expect(dialog).toContainText(
    'This browser cannot read the narration out, so the slides play silently.',
  );
  await dialog.getByRole('button', { name: 'Close video summary dialog' }).click();
});

test('shows the unsupported audio fallback without host speech hardware', async ({ api, page }, testInfo) => {
  await page.addInitScript(() => {
    Object.defineProperty(window, 'speechSynthesis', { configurable: true, value: undefined });
  });
  await setupReadyUrlWorkspace(api, page, testInfo, 'audio-summary');
  const studio = page.getByRole('complementary', { name: 'Studio' });
  await expect(studio.getByRole('button', { name: 'Audio summary', exact: true })).toBeDisabled();
  await expect(studio.getByText('Not supported in this browser', { exact: true })).toBeVisible();
});
```

The init script is installed before the first navigation performed by `setupReadyUrlWorkspace`; neither test depends on host speech synthesis or audio hardware.

Run:

```bash
npm test -- tests/studio-and-settings.spec.ts --grep "fallback|unsupported audio"
```

Expected: both tests pass without playing audio; video displays its silent-mode disclosure and audio stays disabled with the exact explanation.

- [ ] **Step 5: Add dark-theme persistence**

Append:

```typescript
test('persists the dark theme across reload', async ({ api, page }, testInfo) => {
  await setupWorkspace(api, page, testInfo, 'dark-theme');
  await page.getByRole('banner').getByRole('button', { name: 'Settings' }).click();
  const dialog = page.getByRole('dialog', { name: 'Settings' });
  await dialog.getByRole('button', { name: 'Dark', exact: true }).click();
  await expect(dialog.getByRole('button', { name: 'Dark', exact: true })).toHaveAttribute(
    'aria-pressed',
    'true',
  );
  await dialog.getByRole('button', { name: 'Save Changes', exact: true }).click();

  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
  expect(await page.evaluate(() => localStorage.getItem('open-notebook-theme'))).toBe('dark');
  await page.reload();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
  expect(await page.evaluate(() => localStorage.getItem('open-notebook-theme'))).toBe('dark');
});
```

Run:

```bash
npm test -- tests/studio-and-settings.spec.ts --grep "dark theme"
```

Expected: both DOM state and the exact `open-notebook-theme` key remain `dark` after reload.

- [ ] **Step 6: Run the Task 7 suite and commit**

```bash
npm run typecheck
npm test -- tests/studio-and-settings.spec.ts
git add e2e/tests/studio-and-settings.spec.ts
git commit -m "test: cover studio export and settings e2e flows"
```

Expected: seven independent tests pass; failure of one output cannot prevent the remaining output tests from executing.

---

### Task 8: Add the opt-in production-embedding full-RAG workflow

**Files:**

- Modify: `backend/requirements-e2e-rag.txt`
- Create: `e2e/tests/full-rag.spec.ts`

**Interfaces:**

- Consumes: Task 2's full mode with no dependency overrides, Task 3's conditional `chromium-full-rag` project, Task 4's authenticated API, and Task 5's generated valid PDF.
- Produces: one model-aware browser test that proves production embedding ingestion, retrieval, citation, and persisted conversation state without an external LLM.
- The project exists only when `FULL_RAG_E2E=1`; the test must not call `test.skip` and accidentally turn a misconfigured nightly job green.

- [ ] **Step 1: Pin a CPU-compatible embedding stack**

Replace `backend/requirements-e2e-rag.txt` with:

```text
-r requirements-e2e.txt
torch==2.5.1
torchvision==0.20.1
huggingface-hub==0.25.2
sentence-transformers==2.2.2
transformers==4.44.2
```

Install CPU wheels first, then the complete requirements, from `backend/`:

```bash
python -m pip install --index-url https://download.pytorch.org/whl/cpu torch==2.5.1 torchvision==0.20.1
python -m pip install -r requirements-e2e-rag.txt
python -c "from app.services.embeddings import EmbeddingService; print(type(EmbeddingService()).__name__)"
```

Expected: installation avoids CUDA packages, the compatibility-pinned sentence-transformers stack imports, and the command prints `EmbeddingService` after the production model is available or downloaded.

- [ ] **Step 2: Write the full-RAG browser workflow**

Create `e2e/tests/full-rag.spec.ts`:

```typescript
import { test, expect } from '../support/fixtures.js';
import { generatePdf } from '../support/pdf.js';
import { openAddSourceDialog, setupWorkspace, sourceRow } from '../support/ui.js';

test('indexes and retrieves a generated PDF with production embeddings', async ({
  api,
  page,
}, testInfo) => {
  test.setTimeout(10 * 60_000);
  const { project } = await setupWorkspace(api, page, testInfo, 'full-rag');
  const filename = 'full-rag-observatory.pdf';
  const filePath = testInfo.outputPath(filename);
  const identifier = 'ORBIT-FULL-7319';
  await generatePdf(
    filePath,
    'Full RAG Observatory Manual',
    `The emergency observatory access identifier is ${identifier}.`,
  );

  const dialog = await openAddSourceDialog(page);
  await dialog.locator('input[type="file"]').setInputFiles(filePath);
  const uploadResponse = page.waitForResponse(
    (response) => response.url().endsWith(`/api/projects/${project.id}/upload`)
      && response.request().method() === 'POST',
  );
  await dialog.getByRole('button', { name: 'Upload 1 file(s)', exact: true }).click();
  const uploaded = await uploadResponse;
  expect(uploaded.status()).toBe(200);
  const { doc_id: documentId } = await uploaded.json() as { doc_id: string };

  await api.waitForDocumentReady(documentId, 8 * 60_000);
  await expect(sourceRow(page, filename).getByText('Ready', { exact: true }))
    .toBeVisible({ timeout: 15_000 });

  const question = 'What is the emergency observatory access identifier?';
  await page.getByPlaceholder('Ask anything about your sources...').fill(question);
  const queryResponse = page.waitForResponse(
    (response) => response.url().endsWith('/api/query') && response.request().method() === 'POST',
  );
  await page.getByRole('button', { name: 'Send message' }).click();
  const raw = await queryResponse;
  expect(raw.status()).toBe(200);
  const result = await raw.json() as {
    answer: string;
    model_used: string;
    conversation_id: string;
    sources: Array<{ document_id: string; document_title: string; text_preview: string }>;
  };

  expect(result.model_used).toBe('fallback');
  expect(result.answer).toContain(identifier);
  expect(result.sources).toEqual(expect.arrayContaining([
    expect.objectContaining({
      document_id: documentId,
      document_title: filename,
      text_preview: expect.stringContaining(identifier),
    }),
  ]));

  const conversationTitle = `${question.substring(0, 50)}...`;
  const conversationsLoaded = page.waitForResponse(
    (response) => response.url().endsWith(`/api/projects/${project.id}/conversations`)
      && response.request().method() === 'GET',
  );
  await page.reload();
  await conversationsLoaded;
  const detailLoaded = page.waitForResponse(
    (response) => response.url().endsWith(`/api/conversations/${result.conversation_id}`),
  );
  await page
    .getByRole('region', { name: 'Conversations panel content' })
    .getByText(conversationTitle, { exact: true })
    .click();
  await detailLoaded;
  await expect(page.getByText(question, { exact: true })).toBeVisible();
  const reloadedAssistant = page.getByText('Sources:', { exact: true }).last().locator('..');
  await expect(reloadedAssistant).toContainText(identifier);
  await expect(reloadedAssistant).toContainText(filename);

  const persisted = await api.conversation(result.conversation_id);
  expect(persisted.messages.map((message) => message.role)).toEqual(
    expect.arrayContaining(['user', 'assistant']),
  );
  expect(persisted.messages).toHaveLength(2);
  const assistantMessage = persisted.messages.find((message) => message.role === 'assistant');
  expect(assistantMessage?.text).toContain(identifier);
  expect(assistantMessage?.citations).toEqual(expect.arrayContaining([
    expect.objectContaining({ document_id: documentId, document_title: filename }),
  ]));
});
```

The question deliberately omits the unique identifier: only successful production embedding, storage, and retrieval can put it in the fallback answer and citation. The test does not assert an exact free-form sentence, and `LLM_MODE=none` keeps answer generation extractive.

- [ ] **Step 3: Run the full-RAG project explicitly**

From `e2e/`, with the model cache available:

```bash
npm run typecheck
npm run test:full-rag
```

Expected: Playwright starts the backend in full mode, readiness waits through model initialization, exactly one `chromium-full-rag` test passes, the query reports `model_used: fallback`, and its citation/text preview contain `ORBIT-FULL-7319`.

- [ ] **Step 4: Prove the default project excludes the full-RAG test**

Run:

```bash
npx playwright test --list
npm test -- --list
```

Expected: without `FULL_RAG_E2E=1`, the first command defines/lists only `chromium-fast`, neither listing contains `full-rag.spec.ts`, and no green skip masks a missing model setup.

- [ ] **Step 5: Commit the full-RAG tier**

```bash
git add backend/requirements-e2e-rag.txt e2e/tests/full-rag.spec.ts
git commit -m "test: add production embedding e2e coverage"
```

---

### Task 9: Wire CI, document commands, and collect completion evidence

**Files:**

- Create: `.github/workflows/e2e.yml`
- Modify: `README.md:616-633`
- Modify: `e2e/README.md:1-5, Verification requirements`

**Interfaces:**

- Consumes: all prior task commands and artifact paths.
- Produces: a fast every-push/PR gate, a nightly/manual full-RAG gate, seven-day failure artifacts, documented developer commands, and a final verified clean tree.
- This task must invoke `superpowers:requesting-code-review` after the first complete verification pass and `superpowers:verification-before-completion` before any completion claim.

- [ ] **Step 1: Add the fast and full-RAG GitHub Actions jobs**

Create `.github/workflows/e2e.yml`:

```yaml
name: End-to-end tests

on:
  push:
  pull_request:
  schedule:
    - cron: '0 18 * * *'
  workflow_dispatch:

permissions:
  contents: read

jobs:
  fast-e2e:
    if: github.event_name == 'push' || github.event_name == 'pull_request'
    runs-on: ubuntu-latest
    timeout-minutes: 30
    steps:
      - name: Check out repository
        uses: actions/checkout@v7
        with:
          persist-credentials: false

      - name: Set up Python
        uses: actions/setup-python@v7
        with:
          python-version: '3.10'
          cache: pip
          cache-dependency-path: backend/requirements-e2e.txt

      - name: Set up Node.js
        uses: actions/setup-node@v7
        with:
          node-version: '22'
          cache: npm
          cache-dependency-path: |
            frontend/package-lock.json
            e2e/package-lock.json

      - name: Install deterministic backend dependencies
        run: python -m pip install -r backend/requirements-e2e.txt

      - name: Install frontend dependencies
        run: npm ci
        working-directory: frontend

      - name: Install E2E dependencies
        run: npm ci
        working-directory: e2e

      - name: Install Chromium system dependencies
        run: npx playwright install --with-deps chromium
        working-directory: e2e

      - name: Run deterministic Chromium E2E
        run: npm test
        working-directory: e2e

      - name: Upload failed fast-E2E diagnostics
        if: failure()
        uses: actions/upload-artifact@v7
        with:
          name: e2e-fast-${{ github.run_id }}-${{ github.run_attempt }}
          path: output/e2e
          if-no-files-found: warn
          retention-days: 7

  full-rag-e2e:
    if: github.event_name == 'schedule' || github.event_name == 'workflow_dispatch'
    runs-on: ubuntu-latest
    timeout-minutes: 60
    env:
      HF_HOME: ${{ github.workspace }}/.cache/huggingface
    steps:
      - name: Check out repository
        uses: actions/checkout@v7
        with:
          persist-credentials: false

      - name: Set up Python
        uses: actions/setup-python@v7
        with:
          python-version: '3.10'
          cache: pip
          cache-dependency-path: |
            backend/requirements-e2e.txt
            backend/requirements-e2e-rag.txt

      - name: Set up Node.js
        uses: actions/setup-node@v7
        with:
          node-version: '22'
          cache: npm
          cache-dependency-path: |
            frontend/package-lock.json
            e2e/package-lock.json

      - name: Restore Hugging Face model cache
        uses: actions/cache@v6
        with:
          path: .cache/huggingface
          key: hf-${{ runner.os }}-${{ hashFiles('backend/requirements-e2e-rag.txt', 'backend/app/config.py') }}
          restore-keys: |
            hf-${{ runner.os }}-

      - name: Install CPU PyTorch
        run: >-
          python -m pip install
          --index-url https://download.pytorch.org/whl/cpu
          torch==2.5.1 torchvision==0.20.1

      - name: Install full-RAG backend dependencies
        run: python -m pip install -r backend/requirements-e2e-rag.txt

      - name: Install frontend dependencies
        run: npm ci
        working-directory: frontend

      - name: Install E2E dependencies
        run: npm ci
        working-directory: e2e

      - name: Install Chromium system dependencies
        run: npx playwright install --with-deps chromium
        working-directory: e2e

      - name: Run production-embedding Chromium E2E
        run: npm run test:full-rag
        working-directory: e2e

      - name: Upload failed full-RAG diagnostics
        if: failure()
        uses: actions/upload-artifact@v7
        with:
          name: e2e-full-rag-${{ github.run_id }}-${{ github.run_attempt }}
          path: output/e2e
          if-no-files-found: warn
          retention-days: 7
```

The cron is 18:00 UTC, which is 02:00 the next day in Asia/Taipei. Do not cache Playwright browser binaries; the official install command handles the matching Chromium build and OS libraries. The Hugging Face cache is outside `output/e2e`, so failure artifacts cannot include model files.

- [ ] **Step 2: Document local deterministic and full-RAG commands**

Extend `README.md` immediately after the existing frontend test commands under `## 🧪 Testing`:

~~~~markdown

### Browser E2E

The default Chromium suite runs isolated Next.js and FastAPI servers on ports
3100 and 8100. It uses a run-specific SQLite database under `output/e2e` and
does not need an API key, public network, torch, or sentence-transformers.

```bash
cd backend
python -m pip install -r requirements-e2e.txt

cd ../frontend
npm ci

cd ../e2e
npm ci
npx playwright install chromium
npm test
```

Use `npm run test:headed` or `npm run test:debug` for local investigation.
Failed runs retain their HTML report, trace, video, screenshot, server logs, and
isolated database under `output/e2e/<run-id>`; successful runs clean up unless
`E2E_KEEP_RUNTIME=1` is set.

The production-embedding test is an explicit, slower opt-in:

```bash
cd backend
python -m pip install --index-url https://download.pytorch.org/whl/cpu torch==2.5.1 torchvision==0.20.1
python -m pip install -r requirements-e2e-rag.txt

cd ../e2e
npm run test:full-rag
```
~~~~

Keep the existing explanation that the complete backend pytest suite needs ML dependencies; the reduced requirements are only for the deterministic E2E server.

- [ ] **Step 3: Run static and focused backend verification**

From the repository root/worktree:

```bash
git diff --check
cd backend
python -m pytest tests/unit/test_service_dependencies.py tests/unit/test_e2e_services.py tests/unit/test_rag_retrieval_query.py tests/unit/test_retrieval_scope.py -q
```

Expected: `git diff --check` prints nothing and all new/affected backend unit tests pass. If the host lacks the documented ML environment, run these commands inside the backend container instead of weakening or skipping the test imports.

- [ ] **Step 4: Run existing backend, frontend, lint, and deterministic E2E gates**

Build the ML-capable backend image, then mount this worktree at `/repo` so `tests/unit/test_config.py` can see the root `.env.example` files. Do not start the Compose service: its fixed container name, persistent data mounts, and ports could collide with a developer stack.

```bash
docker build --tag opennotebooklm-e2e-test-backend ./backend
docker run --rm \
  --mount "type=bind,source=${PWD},target=/repo" \
  --workdir /repo/backend \
  --env APP_ENV=test \
  --env LLM_MODE=none \
  --env OPENAI_API_KEY= \
  --env CLAUDE_API_KEY= \
  opennotebooklm-e2e-test-backend \
  python -m pytest tests -q
```

Then run frontend and E2E gates:

```bash
cd frontend
npm test
npm run lint

cd ../e2e
npm run typecheck
npm test
```

Expected:

- Backend pytest completes with no failures in its ML-capable container.
- Frontend Vitest reports at least the existing baseline of 35 files and 338 passing tests.
- Frontend lint exits 0. If the repository's existing `next lint` script is incompatible with the installed Next.js CLI, record the exact pre-existing command/output separately; do not describe E2E as the cause.
- The entire `chromium-fast` project passes with one worker and no skipped full-RAG test.

- [ ] **Step 5: Run full RAG or record the concrete environment blocker**

When the production model is installed/cached:

```bash
cd e2e
npm run test:full-rag
```

Expected: exactly one full-RAG test passes and retrieves `ORBIT-FULL-7319`. If local hardware/network cannot install or warm the model, record the exact failed command and error, verify that the scheduled workflow contains the CPU/model-cache setup, and leave full-RAG validation explicitly outstanding rather than claiming it passed.

- [ ] **Step 6: Request code review and resolve findings**

Invoke `superpowers:requesting-code-review` with the approved design (`e2e/README.md`), this implementation plan, the complete diff, and validation output. Apply every correctness finding using `superpowers:receiving-code-review`, rerun the smallest affected test first, then rerun the full fast E2E project.

Expected: no unresolved correctness, isolation, cleanup, ownership, or flakiness findings remain.

- [ ] **Step 7: Perform verification-before-completion and artifact audit**

Invoke `superpowers:verification-before-completion`, then run fresh commands rather than relying on earlier output:

```bash
git diff --check
git status --short
git ls-files output/e2e
git ls-files | grep -E '(opennotebook\.db|playwright-report|test-results|trace\.zip|\.webm$)' || true
```

On PowerShell, replace the last pipeline with:

```powershell
git ls-files | Select-String -Pattern 'opennotebook\.db|playwright-report|test-results|trace\.zip|\.webm$'
```

Expected: diff check is empty; status shows only intended source/docs changes; both artifact searches are empty; `.cache/huggingface` and all runtime output remain untracked.

- [ ] **Step 8: Mark the approved design implemented and commit CI/docs**

Only after Steps 3-7 have evidence, change the top of `e2e/README.md` to:

```markdown
Status: implemented and verified.
```

Under its verification section, append the exact commands, pass counts, date, and any explicitly outstanding full-RAG environment validation. Then commit:

```bash
git add .github/workflows/e2e.yml README.md e2e/README.md
git commit -m "ci: run deterministic and full-rag e2e tests"
```

- [ ] **Step 9: Prepare branch integration options**

Invoke `superpowers:finishing-a-development-branch` only after every required local gate has passed or its allowed full-RAG environment limitation is reported. Present the user with the verified branch name `feat/e2e-test-suite`, commit list, test evidence, configuration/dependency effects, and integration choices; do not merge, push, or delete a branch without the user's direction.

---

## Final Coverage Checklist

- [ ] Anonymous access redirects to `/login`.
- [ ] Registration establishes and reload restores browser session state.
- [ ] Wrong password produces a visible 401 error and no session state.
- [ ] Logout clears cookie/storage and protects back navigation.
- [ ] Project creation/selection persists through reload.
- [ ] Account B cannot list Account A's project or source, and receives 404 for A's id.
- [ ] PDF upload reaches ready, previews protected bytes, and unlinks from the project.
- [ ] Fixed URL import reaches ready, is searchable, and unlinks without external navigation.
- [ ] Fixed YouTube transcript reaches ready without contacting YouTube.
- [ ] Query returns fallback answer, unique fact, citation, and two persisted messages after reload/reselection.
- [ ] Conversation create, rename, selection, and deletion persist.
- [ ] Mind map renders fallback structure.
- [ ] Report downloads valid project Markdown.
- [ ] Project and selected conversation export independently with correct content/filename.
- [ ] Video shows structural/silent fallback and scene count.
- [ ] Audio unsupported state is deterministic before application code loads.
- [ ] Dark theme persists in DOM and localStorage after reload.
- [ ] Full-RAG production embeddings retrieve/cite a locally generated unique PDF fact.
- [ ] Fast E2E runs on every push and pull request; full-RAG runs nightly/manual.
- [ ] Failed runs retain evidence; successful runs clean only a validated marked runtime.
- [ ] Existing backend and frontend suites remain green and no runtime/model artifacts are tracked.

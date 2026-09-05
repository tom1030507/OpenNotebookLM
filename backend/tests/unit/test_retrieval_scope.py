"""Retrieval cannot reach a document the caller does not own.

The route-level checks stop someone opening another account's project. They do
not, on their own, stop a *question* from reaching another account's chunks:
`/query` with no project selected used to search every embedding in the database.
So the scope is enforced one level down as well, where the search actually
happens, and applied after the project scope rather than instead of it.
"""
from __future__ import annotations

import importlib
import sys
import types
import uuid
from unittest import mock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import (
    Base,
    Chunk,
    Document,
    Project,
    ProjectDocument,
    User,
)

ALICE_DOC = "document-alice"
BOB_DOC = "document-bob"
PROJECT = "project-shared"


def real_rag_module():
    """Return the real module when a route test left its no-file stub behind.

    The route-contract tests replace `sys.modules["app.services.rag"]` with a stub
    so importing the query router does not load the embedding model, and that
    replacement outlives their module.

    Args:
        None.

    Returns:
        The genuine module.
    """
    module = sys.modules.get("app.services.rag")
    if module is None or getattr(module, "__file__", None) is None:
        sys.modules.pop("app.services.rag", None)
        module = importlib.import_module("app.services.rag")
    return module


class RecordingEmbeddingService:
    """Returns a deterministic vector without loading the model."""

    def __init__(self):
        self.calls = []

    def generate_embedding(self, query, **_kwargs):
        """Record the query and return a two-dimensional vector.

        Args:
            query: Search text under test.
            _kwargs: Embedding options unused by this double.

        Returns:
            A deterministic query vector.
        """
        self.calls.append(query)
        return [1.0, 0.0]


class RecordingRetrievalIndex:
    """Apply and record document scope at the indexed-search boundary."""

    def __init__(self):
        self.dense_calls = []
        self.lexical_calls = []

    def dense_search(self, _db, _vector, document_ids=None, **_kwargs):
        """Record dense scope and return no candidates.

        Args:
            _db: Unused request session.
            _vector: Unused deterministic query vector.
            document_ids: Document scope under test.
            _kwargs: Ranking options unused by this double.

        Returns:
            No dense candidates.
        """
        self.dense_calls.append(document_ids)
        return []

    def lexical_search(self, db, _query, document_ids=None, top_k=5):
        """Record lexical scope and return matching canonical chunk ids.

        Args:
            db: Request session containing the fixture chunks.
            _query: Unused lexical query.
            document_ids: Document scope under test.
            top_k: Maximum candidate count.

        Returns:
            Scoped lexical candidates.
        """
        self.lexical_calls.append(document_ids)
        rows = db.query(Chunk).order_by(Chunk.id)
        if document_ids is not None:
            rows = rows.filter(Chunk.document_id.in_(document_ids))
        return [
            types.SimpleNamespace(
                chunk_id=chunk.id,
                document_id=chunk.document_id,
                score=1.0,
            )
            for chunk in rows.limit(top_k).all()
        ]

    def hydrate(self, db, chunk_ids):
        """Hydrate the bounded candidate ids in their requested order.

        Args:
            db: Request session containing the fixture chunks.
            chunk_ids: Bounded candidate ids.

        Returns:
            Hydrated payloads in candidate order.
        """
        rows = db.query(Chunk, Document.title).join(
            Document,
            Document.id == Chunk.document_id,
        ).filter(Chunk.id.in_(chunk_ids)).all()
        payloads = {
            chunk.id: {
                "chunk_id": chunk.id,
                "document_id": chunk.document_id,
                "document_title": title,
                "text": chunk.text,
                "metadata": {
                    "page_num": chunk.page_num,
                    "timestamp": chunk.ts_start,
                    "section": None,
                    "heading_path": chunk.heading_path,
                },
            }
            for chunk, title in rows
        }
        return [payloads[chunk_id] for chunk_id in chunk_ids]

    def status(self):
        """Report the deterministic test backend.

        Returns:
            Dataclass-like status payload.
        """
        return types.SimpleNamespace(
            as_dict=lambda: {"active_backend": "test-index"}
        )


class RecordingLLMService:
    """Stand-in so constructing the service needs no provider."""

    def generate(self, prompt, temperature=0.7, max_tokens=512, system_prompt=None):
        """Return a fixed answer.

        Args:
            prompt: Unused.
            temperature: Unused.
            max_tokens: Unused.
            system_prompt: Unused.

        Returns:
            A fixed generation result.
        """
        return {"text": "An answer.", "model": "test-model", "usage": {}}


@pytest.fixture
def db():
    """A database with one project holding one document from each account."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(autocommit=False, autoflush=False, bind=engine)()

    alice = User(id="user-alice", username="alice", email="alice@example.com",
                 hashed_password="x", is_active=True)
    bob = User(id="user-bob", username="bob", email="bob@example.com",
               hashed_password="x", is_active=True)
    session.add_all([alice, bob])

    session.add(Project(id=PROJECT, user_id=alice.id, name="Shared", meta_json={}))
    for doc_id, owner, text in (
        (ALICE_DOC, alice.id, "Alice writes about positional encoding at length."),
        (BOB_DOC, bob.id, "Bob writes about positional encoding at length too."),
    ):
        session.add(Document(id=doc_id, user_id=owner, title=doc_id,
                             source_type="url", status="ready", meta_json={}))
        session.add(Chunk(id=str(uuid.uuid4()), document_id=doc_id, text=text,
                          start_offset=0, end_offset=len(text), meta_json={}))
        session.add(ProjectDocument(project_id=PROJECT, document_id=doc_id))
    session.commit()

    yield session
    session.close()
    engine.dispose()


@pytest.fixture
def service():
    """A RAGService with both heavy dependencies replaced."""
    module = real_rag_module()
    embeddings = RecordingEmbeddingService()
    retrieval_index = RecordingRetrievalIndex()
    with mock.patch.object(
        module,
        "get_retrieval_index",
        lambda: retrieval_index,
    ):
        instance = module.RAGService(
            embedding_service=embeddings,
            llm_service=RecordingLLMService(),
        )
        yield instance, retrieval_index


class TestScopeReachesTheSearch:
    """The allowed set is what the dense search is told to look at."""

    def test_scope_is_passed_through(self, db, service):
        instance, retrieval_index = service

        instance._retrieve_chunks(db=db, query="positional encoding",
                                  allowed_document_ids=[ALICE_DOC])

        assert retrieval_index.dense_calls == [[ALICE_DOC]]

    def test_no_scope_means_no_filter(self, db, service):
        # Only callers outside the request path, such as the eval harness, pass
        # None. The API always supplies a list.
        instance, retrieval_index = service

        instance._retrieve_chunks(db=db, query="positional encoding")

        assert retrieval_index.dense_calls == [None]

    def test_an_empty_scope_searches_nothing(self, db, service):
        instance, retrieval_index = service

        result = instance._retrieve_chunks(db=db, query="positional encoding",
                                           allowed_document_ids=[])

        assert result == []
        assert retrieval_index.dense_calls == [], (
            "the search should not have been reached"
        )


class TestScopeNarrowsTheProject:
    """A project scope cannot widen what the caller may see."""

    def test_project_and_scope_are_intersected(self, db, service):
        # The project holds both documents; only Alice's is allowed.
        instance, retrieval_index = service

        instance._retrieve_chunks(db=db, query="positional encoding",
                                  project_id=PROJECT,
                                  allowed_document_ids=[ALICE_DOC])

        assert retrieval_index.dense_calls == [[ALICE_DOC]]

    def test_a_project_of_someone_elses_documents_yields_nothing(self, db, service):
        instance, retrieval_index = service

        result = instance._retrieve_chunks(db=db, query="positional encoding",
                                           project_id=PROJECT,
                                           allowed_document_ids=["document-nobody"])

        assert result == []
        assert retrieval_index.dense_calls == []


class TestLexicalHalfIsScopedToo:
    """BM25 runs its own query, so it needs the same limit."""

    def test_only_allowed_chunks_are_candidates(self, db, service):
        instance, retrieval_index = service

        candidates = instance._retrieve_chunks(
            db=db,
            query="positional encoding",
            allowed_document_ids=[ALICE_DOC],
        )

        assert [c["document_id"] for c in candidates] == [ALICE_DOC]
        assert retrieval_index.lexical_calls == [[ALICE_DOC]]

    def test_without_the_limit_both_are_candidates(self, db, service):
        instance, retrieval_index = service

        candidates = instance._retrieve_chunks(
            db=db,
            query="positional encoding",
        )

        assert {c["document_id"] for c in candidates} == {ALICE_DOC, BOB_DOC}
        assert retrieval_index.lexical_calls == [None]

    def test_fused_results_stay_inside_the_scope(self, db, service):
        instance, _ = service

        results = instance._retrieve_chunks(
            db=db, query="positional encoding", allowed_document_ids=[ALICE_DOC])

        assert results, "the lexical half should still find Alice's chunk"
        assert {r["document_id"] for r in results} == {ALICE_DOC}


class TestCacheKeyKnowsTheScope:
    """Two accounts asking the same question must not share a cache entry."""

    def test_different_scopes_give_different_keys(self, db, service):
        instance, _ = service

        alice_key = instance._generate_cache_key(
            query="what is this?", allowed_document_ids=[ALICE_DOC])
        bob_key = instance._generate_cache_key(
            query="what is this?", allowed_document_ids=[BOB_DOC])

        assert alice_key != bob_key

    def test_the_same_scope_gives_the_same_key(self, db, service):
        instance, _ = service

        first = instance._generate_cache_key(
            query="what is this?", allowed_document_ids=[ALICE_DOC, BOB_DOC])
        second = instance._generate_cache_key(
            query="what is this?", allowed_document_ids=[BOB_DOC, ALICE_DOC])

        assert first == second, "order must not matter"

    def test_no_scope_is_its_own_key(self, db, service):
        instance, _ = service

        unscoped = instance._generate_cache_key(query="what is this?")
        scoped = instance._generate_cache_key(
            query="what is this?", allowed_document_ids=[ALICE_DOC])

        assert unscoped != scoped


@pytest.fixture
def overview_document(db):
    """Seed split overview sections and misleading bibliography text.

    Args:
        db: Isolated database with Alice's and Bob's documents.

    Returns:
        Alice's document id.
    """
    db.query(Chunk).filter(Chunk.document_id == ALICE_DOC).delete()
    for offset, chunk_id, text in [
        (0, "00-front", "Paper title and author affiliations."),
        (100, "10-abstract", "Abstract\nWe introduce Aurora, an attention architecture."),
        (200, "11-abstract-result", "It permits parallel training and improves translation."),
        (300, "20-intro", "1 Introduction\nRecurrent models train sequentially."),
        (400, "30-method", "2 Method\nThe architecture compares queries against keys."),
        (500, "70-conclusion", "7 Conclusion\nAurora reduces training cost."),
        (600, "71-conclusion-result", "The method improves translation quality."),
        (700, "80-references", "References\n[1] Other people's research."),
        (800, "81-reference-title", "Abstract\nA bibliography entry about another method."),
    ]:
        db.add(Chunk(
            id=chunk_id, document_id=ALICE_DOC, text=text,
            start_offset=offset, end_offset=offset + len(text), meta_json={},
        ))
    db.commit()
    return ALICE_DOC


@pytest.mark.parametrize("question", [
    "What is this paper about?",
    "Summarize this paper.",
    "Give me an overview of this document.",
    "What are the main contributions of this paper?",
    "這篇論文在講什麼？",
    "請總結這篇文章",
])
def test_document_overviews_select_complete_scoped_sections(
    db, service, overview_document, question,
):
    instance, _ = service
    chunks = instance._retrieve_chunks(
        db=db, query=question, project_id=PROJECT,
        allowed_document_ids=[overview_document], top_k=5,
    )
    assert [chunk["chunk_id"] for chunk in chunks] == [
        "10-abstract", "11-abstract-result", "70-conclusion",
        "71-conclusion-result", "20-intro",
    ]
    assert {chunk["document_id"] for chunk in chunks} == {ALICE_DOC}


@pytest.mark.parametrize("question", [
    "What vocabulary did this paper use?",
    "Summarize the vocabulary settings.",
    "這篇論文用了多少訓練資料？",
])
def test_specific_questions_keep_the_existing_search_ranking(
    db, service, overview_document, question,
):
    instance, _ = service
    chunks = instance._retrieve_chunks(
        db=db, query=question, allowed_document_ids=[overview_document], top_k=2,
    )
    assert [chunk["chunk_id"] for chunk in chunks] == ["00-front", "10-abstract"]


def test_an_overview_cannot_reach_a_project_document_outside_the_allowed_set(
    db, service, overview_document,
):
    instance, _ = service
    chunks = instance._retrieve_chunks(
        db=db, query="What is this paper about?", project_id=PROJECT,
        allowed_document_ids=[BOB_DOC], top_k=5,
    )
    assert {chunk["document_id"] for chunk in chunks} == {BOB_DOC}


def test_overview_selection_honors_a_small_top_k(db, service, overview_document):
    instance, _ = service
    chunks = instance._retrieve_chunks(
        db=db, query="What is this paper about?",
        allowed_document_ids=[overview_document], top_k=1,
    )
    assert [chunk["chunk_id"] for chunk in chunks] == ["10-abstract"]


def test_overview_passages_start_at_the_section_instead_of_author_metadata(
    db, service, overview_document,
):
    abstract = db.get(Chunk, "10-abstract")
    abstract.text = "Alice Researcher\nalice@example.com\n" + abstract.text
    db.commit()
    instance, _ = service
    chunks = instance._retrieve_chunks(
        db=db, query="What is this paper about?",
        allowed_document_ids=[overview_document], top_k=1,
    )
    assert chunks[0]["text"].startswith("Abstract\nWe introduce Aurora")
    assert "alice@example.com" not in chunks[0]["text"]

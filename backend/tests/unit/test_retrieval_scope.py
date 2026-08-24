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
import uuid

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
    """Records the document scope the dense search was asked for."""

    def __init__(self):
        self.calls = []

    def search_similar_chunks(self, db, query, document_ids=None, top_k=5, threshold=0.0):
        """Record the scope and return nothing.

        Returning nothing keeps the assertions about *scope* rather than about
        ranking; the lexical half still runs against the real rows.

        Args:
            db: Unused.
            query: Unused.
            document_ids: The scope under test.
            top_k: Unused.
            threshold: Unused.

        Returns:
            An empty candidate list.
        """
        self.calls.append(document_ids)
        return []


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
    instance = module.RAGService(
        embedding_service=embeddings,
        llm_service=RecordingLLMService(),
    )
    return instance, embeddings


class TestScopeReachesTheSearch:
    """The allowed set is what the dense search is told to look at."""

    def test_scope_is_passed_through(self, db, service):
        instance, embeddings = service

        instance._retrieve_chunks(db=db, query="positional encoding",
                                  allowed_document_ids=[ALICE_DOC])

        assert embeddings.calls == [[ALICE_DOC]]

    def test_no_scope_means_no_filter(self, db, service):
        # Only callers outside the request path, such as the eval harness, pass
        # None. The API always supplies a list.
        instance, embeddings = service

        instance._retrieve_chunks(db=db, query="positional encoding")

        assert embeddings.calls == [None]

    def test_an_empty_scope_searches_nothing(self, db, service):
        instance, embeddings = service

        result = instance._retrieve_chunks(db=db, query="positional encoding",
                                           allowed_document_ids=[])

        assert result == []
        assert embeddings.calls == [], "the search should not have been reached"


class TestScopeNarrowsTheProject:
    """A project scope cannot widen what the caller may see."""

    def test_project_and_scope_are_intersected(self, db, service):
        # The project holds both documents; only Alice's is allowed.
        instance, embeddings = service

        instance._retrieve_chunks(db=db, query="positional encoding",
                                  project_id=PROJECT,
                                  allowed_document_ids=[ALICE_DOC])

        assert embeddings.calls == [[ALICE_DOC]]

    def test_a_project_of_someone_elses_documents_yields_nothing(self, db, service):
        instance, embeddings = service

        result = instance._retrieve_chunks(db=db, query="positional encoding",
                                           project_id=PROJECT,
                                           allowed_document_ids=["document-nobody"])

        assert result == []
        assert embeddings.calls == []


class TestLexicalHalfIsScopedToo:
    """BM25 runs its own query, so it needs the same limit."""

    def test_only_allowed_chunks_are_candidates(self, db, service):
        instance, _ = service

        candidates = instance._lexical_candidates(
            db, "positional encoding", [ALICE_DOC], 10)

        assert [c["document_id"] for c in candidates] == [ALICE_DOC]

    def test_without_the_limit_both_are_candidates(self, db, service):
        instance, _ = service

        candidates = instance._lexical_candidates(
            db, "positional encoding", None, 10)

        assert {c["document_id"] for c in candidates} == {ALICE_DOC, BOB_DOC}

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

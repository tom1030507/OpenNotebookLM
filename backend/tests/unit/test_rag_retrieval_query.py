"""What a conversation turn actually searches with.

The frontend always sends a conversation_id, so this path is every real question
asked of the app. It used to concatenate the whole transcript and embed that: the
query vector was dominated by old turns, and because the encoder truncates at its
sequence limit the current question — which sits at the end — was the first thing
to be cut.
"""
import importlib
import sys
import uuid
from unittest import mock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import Base, Conversation, Message, Project

PROJECT_ID = "project-1"
CONVERSATION_ID = "conversation-1"


def real_rag_module():
    """Return the real `app.services.rag`, even if a stub is registered.

    The route-contract tests replace `sys.modules["app.services.rag"]` with a
    stub so that importing the query router does not load the embedding model.
    That replacement outlives their module, so this test has to ask for the real
    thing explicitly rather than trusting the import.

    Returns:
        The genuine module.
    """
    module = sys.modules.get("app.services.rag")
    if module is None or not hasattr(module, "EmbeddingService"):
        sys.modules.pop("app.services.rag", None)
        module = importlib.import_module("app.services.rag")
    return module


class RecordingEmbeddingService:
    """Captures the string retrieval was asked to search for."""

    def __init__(self):
        self.queries = []

    def search_similar_chunks(self, db, query, document_ids=None, top_k=5, threshold=0.0):
        """Record the query and return one usable chunk.

        Args:
            db: Unused.
            query: The search string under test.
            document_ids: Unused.
            top_k: Unused.
            threshold: Unused.

        Returns:
            A single result shaped like the real dense search.
        """
        self.queries.append(query)
        return [{
            "chunk_id": "chunk-1",
            "document_id": "document-1",
            "document_title": "Transformer",
            "text": "Scaled dot-product attention compares queries against keys.",
            "score": 0.71,
            "metadata": {"page_num": None, "timestamp": None,
                         "section": "Attention", "heading_path": "Transformer > Attention"},
        }]


class RecordingLLMService:
    """Captures the prompt and system prompt the model was given."""

    def __init__(self):
        self.calls = []

    def generate(self, prompt, temperature=0.7, max_tokens=512, system_prompt=None):
        """Record the call and return a fixed answer.

        Args:
            prompt: User turn.
            temperature: Unused.
            max_tokens: Unused.
            system_prompt: System turn.

        Returns:
            A fixed generation result.
        """
        self.calls.append({"prompt": prompt, "system_prompt": system_prompt})
        return {"text": "An answer.", "model": "test-model", "usage": {"total_tokens": 10}}


@pytest.fixture
def db():
    """An isolated database holding one conversation with history."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(autocommit=False, autoflush=False, bind=engine)()

    session.add(Project(id=PROJECT_ID, name="Research notes", meta_json={}))
    session.add(Conversation(id=CONVERSATION_ID, project_id=PROJECT_ID, title="Chat"))
    for role, text in [
        ("user", "What is a transformer and where did it come from?"),
        ("assistant", "It is a neural architecture introduced in 2017."),
        ("user", "How does its attention work over long sequences?"),
        ("assistant", "It compares every token against every other token."),
    ]:
        session.add(Message(id=str(uuid.uuid4()), conversation_id=CONVERSATION_ID,
                            role=role, text=text, citations_json=[]))
    session.commit()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture
def service():
    """A RAGService with both heavy dependencies replaced."""
    module = real_rag_module()
    embeddings = RecordingEmbeddingService()
    llm = RecordingLLMService()
    with mock.patch.object(module, "EmbeddingService", lambda: embeddings), \
         mock.patch.object(module, "LLMService", lambda: llm):
        instance = module.RAGService()
    return instance, embeddings, llm


class TestConversationRetrievalQuery:
    """Retrieval searches the question; the model still sees the transcript."""

    def test_retrieval_uses_the_current_question(self, db, service):
        instance, embeddings, _ = service
        question = "And what does the feed-forward layer contribute?"

        instance.query_with_conversation(
            db=db, query=question, conversation_id=CONVERSATION_ID,
            project_id=None, use_cache=False,
        )

        assert embeddings.queries == [question]

    def test_retrieval_query_excludes_the_transcript(self, db, service):
        instance, embeddings, _ = service

        instance.query_with_conversation(
            db=db, query="And what does the feed-forward layer contribute?",
            conversation_id=CONVERSATION_ID, project_id=None, use_cache=False,
        )

        searched = embeddings.queries[0]
        assert "Previous conversation" not in searched
        assert "introduced in 2017" not in searched

    def test_the_prompt_still_carries_the_history(self, db, service):
        instance, _, llm = service

        instance.query_with_conversation(
            db=db, query="And what does the feed-forward layer contribute?",
            conversation_id=CONVERSATION_ID, project_id=None, use_cache=False,
        )

        prompt = llm.calls[0]["prompt"]
        assert "Previous conversation" in prompt
        assert "introduced in 2017" in prompt

    def test_a_short_follow_up_borrows_the_previous_question(self, db, service):
        # "第二點呢？" on its own has nothing to search for, so the previous
        # question is folded in for coreference.
        instance, embeddings, _ = service

        instance.query_with_conversation(
            db=db, query="第二點呢？", conversation_id=CONVERSATION_ID,
            project_id=None, use_cache=False,
        )

        searched = embeddings.queries[0]
        assert "第二點呢？" in searched
        assert "attention work over long sequences" in searched

    def test_instructions_are_sent_as_a_system_prompt(self, db, service):
        instance, _, llm = service

        instance.query_with_conversation(
            db=db, query="And what does the feed-forward layer contribute?",
            conversation_id=CONVERSATION_ID, project_id=None, use_cache=False,
        )

        call = llm.calls[0]
        assert call["system_prompt"]
        assert "only the context provided" in call["system_prompt"]
        # The instructions no longer ride inside the user turn.
        assert "only the context provided" not in call["prompt"]

    def test_both_messages_are_persisted(self, db, service):
        instance, _, _ = service

        instance.query_with_conversation(
            db=db, query="And what does the feed-forward layer contribute?",
            conversation_id=CONVERSATION_ID, project_id=None, use_cache=False,
        )

        roles = [m.role for m in db.query(Message).filter(
            Message.conversation_id == CONVERSATION_ID).all()]
        assert roles.count("user") == 3
        assert roles.count("assistant") == 3


class TestOneOffQuery:
    """A query with no conversation searches exactly what was asked."""

    def test_retrieval_query_defaults_to_the_question(self, db, service):
        instance, embeddings, _ = service
        instance.query(db=db, query="What is positional encoding?", use_cache=False)
        assert embeddings.queries == ["What is positional encoding?"]

    def test_include_sources_false_returns_no_sources(self, db, service):
        instance, _, _ = service
        result = instance.query(db=db, query="What is positional encoding?",
                                include_sources=False, use_cache=False)
        assert result["sources"] == []

    def test_include_sources_is_honoured_in_a_conversation(self, db, service):
        # It used to be dropped on both conversation branches, so turning it off
        # only worked for a query with no project at all.
        instance, _, _ = service
        result = instance.query_with_conversation(
            db=db, query="And what does the feed-forward layer contribute?",
            conversation_id=CONVERSATION_ID, project_id=None,
            include_sources=False, use_cache=False,
        )
        assert result["sources"] == []

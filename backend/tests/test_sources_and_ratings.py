"""Pasted-text sources, source renames and answer ratings, over HTTP."""
import json
import uuid

import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import get_db
from app.db.models import (
    Base,
    Chunk,
    Conversation,
    Document,
    Embedding,
    IngestionJob,
    Message,
    Project,
    ProjectDocument,
)
from app.routers import export, ingest, query
from app.routers.rate_limit import get_concurrency_limiter, get_rate_limiter
from app.services.chunking import ChunkingService
from app.services import documents as document_service_module
from app.services.documents import DocumentService
from app.services.ingestion_jobs import release_all_operation_leases
from app.services.rate_limit import ConcurrencyLimiter, SlidingWindowRateLimiter
from conftest import authenticated_client, owner_id


class FakeEmbeddings:
    """Persist one embedding per chunk without loading a model."""

    def embed_chunks(self, db, document_id):
        """Embed every chunk of a document.

        Args:
            db: Worker-owned session.
            document_id: Document whose chunks are embedded.

        Returns:
            The persisted embedding rows.
        """
        records = [
            Embedding(
                id=str(uuid.uuid4()),
                chunk_id=chunk.id,
                vector=b"vector",
                vector_json=[0.0],
                model_name="test-model",
            )
            for chunk in db.query(Chunk).filter(Chunk.document_id == document_id)
        ]
        db.add_all(records)
        db.commit()
        return records


@pytest.fixture
def env():
    """A signed-in client over the ingest, query and export routes.

    Yields:
        (client, session, document service)
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(
        bind=engine, autocommit=False, autoflush=False, expire_on_commit=False,
    )()
    service = DocumentService(
        chunking_service=ChunkingService(),
        embedding_service=FakeEmbeddings(),
    )

    app = FastAPI()
    for router in (ingest.router, query.router, export.router):
        app.include_router(router, prefix="/api")
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_rate_limiter] = (
        lambda: SlidingWindowRateLimiter(enabled=False)
    )
    app.dependency_overrides[get_concurrency_limiter] = (
        lambda: ConcurrencyLimiter(max_concurrent=2)
    )
    app.dependency_overrides[ingest.get_document_service] = lambda: service
    client = authenticated_client(app, session)
    session.add(Project(id="project-1", user_id=owner_id(session), name="Notes"))
    session.commit()

    yield client, session, service

    release_all_operation_leases()
    service.executor.shutdown(wait=True)
    session.close()
    engine.dispose()


def add_answer(session, citations=None, role="assistant"):
    """Insert a conversation in project-1 holding one message.

    Args:
        session: Database session.
        citations: Citations stored on the message.
        role: Message role.

    Returns:
        (conversation id, message id)
    """
    conversation = Conversation(id=str(uuid.uuid4()), project_id="project-1")
    message = Message(
        id=str(uuid.uuid4()),
        conversation_id=conversation.id,
        role=role,
        text="An answer",
        citations_json=citations or [],
    )
    session.add_all([conversation, message])
    session.commit()
    return conversation.id, message.id


class TestPastedText:
    """Pasted text becomes a source through the ordinary indexing job."""

    def test_pasted_text_is_chunked_and_embedded(self, env):
        client, session, service = env

        response = client.post(
            "/api/projects/project-1/upload-text",
            json={"title": " Meeting notes ", "text": "Alpha beta gamma.\nDelta."},
        )

        assert response.status_code == 200, response.text
        doc_id = response.json()["doc_id"]
        job = session.query(IngestionJob).one()
        assert (job.document_id, job.job_type) == (doc_id, "text")

        status = service.process_ingestion_job(
            session, doc_id, job.job_type, job.payload_json)
        session.commit()

        document = session.get(Document, doc_id)
        assert status == document.status == "ready"
        assert document.title == "Meeting notes"
        assert document.source_type == "text"
        chunks = session.query(Chunk).filter(Chunk.document_id == doc_id).all()
        assert chunks and "Alpha beta gamma." in chunks[0].text
        assert session.query(Embedding).count() == len(chunks)

    def test_blank_text_is_refused(self, env):
        client, _, _ = env

        response = client.post(
            "/api/projects/project-1/upload-text",
            json={"title": "Empty", "text": "   "},
        )

        assert response.status_code == 422

    def test_text_over_the_size_limit_is_refused(self, env, monkeypatch):
        client, session, service = env
        monkeypatch.setattr(service.settings, "max_file_size_mb", 0)

        response = client.post(
            "/api/projects/project-1/upload-text",
            json={"title": "Too long", "text": "x"},
        )

        assert response.status_code == 413
        assert session.query(Document).count() == 0


class TestRename:
    """A rename reaches the source and the answers that cite it."""

    def test_rename_updates_the_title_and_stored_citations(
        self,
        env,
        monkeypatch,
    ):
        client, session, _ = env
        session.add(Document(
            id="doc-1", user_id=owner_id(session), title="Old name",
            source_type="text", status="ready",
            meta_json={"keep": True, "guide": {"summary": "Old", "topics": ["Old"]}},
        ))
        session.add(ProjectDocument(project_id="project-1", document_id="doc-1"))
        session.commit()
        conversation_id, _ = add_answer(session, [
            {"document_id": "doc-1", "document_title": "Old name"},
            {"document_id": "doc-2", "document_title": "Untouched"},
        ])
        notified = []
        atomic_commits = []

        def verify_title_and_job_commit_together(db):
            assert db.get(Document, "doc-1").title == "New name"
            job = db.query(IngestionJob).filter_by(
                document_id="doc-1",
                job_type="reindex",
            ).one()
            atomic_commits.append(job.id)

        event.listen(session, "before_commit", verify_title_and_job_commit_together)

        def check_committed_reindex():
            assert session.get(Document, "doc-1").title == "New name"
            job = session.query(IngestionJob).filter_by(
                document_id="doc-1",
                job_type="reindex",
            ).one()
            assert job.status == "queued"
            notified.append(job.id)

        monkeypatch.setattr(
            document_service_module,
            "notify_ingestion_worker",
            check_committed_reindex,
        )

        response = client.put("/api/docs/doc-1", json={"title": "  New name "})

        assert response.status_code == 200, response.text
        assert response.json()["title"] == "New name"
        assert session.get(Document, "doc-1").meta_json == {
            "keep": True,
            "source_guide_revision": 1,
        }
        job = session.query(IngestionJob).one()
        assert (job.document_id, job.job_type, job.payload_json) == (
            "doc-1", "reindex", {"requested_title": "New name"},
        )
        assert session.get(Document, "doc-1").status == "ready"
        assert notified == [job.id]
        assert atomic_commits and set(atomic_commits) == {job.id}
        citations = client.get(
            "/api/conversations/%s" % conversation_id).json()["messages"][0]["citations"]
        assert [c["document_title"] for c in citations] == ["New name", "Untouched"]

    def test_blank_title_is_refused(self, env):
        client, session, _ = env
        session.add(Document(
            id="doc-1", user_id=owner_id(session), title="Keep",
            source_type="text", status="ready",
        ))
        session.commit()

        assert client.put("/api/docs/doc-1", json={"title": " "}).status_code == 422
        assert session.get(Document, "doc-1").title == "Keep"

    def test_renaming_to_the_current_title_does_not_queue_refresh(self, env):
        client, session, _ = env
        session.add(Document(
            id="doc-1", user_id=owner_id(session), title="Already named",
            source_type="text", status="ready",
        ))
        session.commit()

        response = client.put(
            "/api/docs/doc-1",
            json={"title": "Already named"},
        )

        assert response.status_code == 200
        assert session.query(IngestionJob).count() == 0


class TestRating:
    """Ratings persist, change, clear and travel with exports."""

    def test_rating_can_be_set_changed_and_cleared(self, env):
        client, session, _ = env
        conversation_id, message_id = add_answer(session)
        url = "/api/conversations/%s/messages/%s/rating" % (conversation_id, message_id)

        def stored():
            return client.get(
                "/api/conversations/%s" % conversation_id).json()["messages"][0]["rating"]

        assert client.put(url, json={"rating": "up"}).json()["rating"] == "up"
        assert stored() == "up"
        client.put(url, json={"rating": "down"})
        assert stored() == "down"
        exported = client.get(
            "/api/export/conversation/%s?format=json" % conversation_id)
        assert json.loads(exported.text)["messages"][0]["rating"] == "down"
        client.put(url, json={"rating": None})
        assert stored() is None

    def test_an_unknown_rating_is_refused(self, env):
        client, session, _ = env
        conversation_id, message_id = add_answer(session)

        response = client.put(
            "/api/conversations/%s/messages/%s/rating" % (conversation_id, message_id),
            json={"rating": "meh"},
        )

        assert response.status_code == 422

    def test_a_question_cannot_be_rated(self, env):
        client, session, _ = env
        conversation_id, message_id = add_answer(session, role="user")

        response = client.put(
            "/api/conversations/%s/messages/%s/rating" % (conversation_id, message_id),
            json={"rating": "up"},
        )

        assert response.status_code == 404

"""One account cannot reach another account's data.

Authentication landed first: every route demands a bearer token. That closed the
door to strangers but not between neighbours — `Project` had no owner column and
`User` had no relationship to anything, so any signed-in caller could list, read,
edit, delete, download and export every other caller's work.

These tests pin the second half from the outside, over HTTP, with two real
accounts. They also pin the *shape* of the refusal: a resource that belongs to
someone else answers exactly like one that does not exist, because a 403 would
confirm the id is real and turn id enumeration into a membership oracle.
"""
from __future__ import annotations

import sys
import uuid
from types import ModuleType

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import get_db
from app.db.models import Base, Document, Project, User

# Retrieval and model inference are not what these tests exercise. Replacing the
# RAG service before the app is imported keeps them in the minimal environment;
# the ownership check on /query runs before any retrieval, so it stays covered.
rag_module = ModuleType("app.services.rag")


class StubRAGService:
    """Stand-in for the unused RAG dependency during route contract tests."""


rag_module.RAGService = StubRAGService
sys.modules["app.services.rag"] = rag_module

from app.main import app as production_app  # noqa: E402
from app.routers.mindmap import get_mindmap_service  # noqa: E402
from app.routers.video import get_video_summary_service  # noqa: E402
from app.services.mindmap import MindMapService  # noqa: E402
from app.services.video_summary import VideoSummaryService  # noqa: E402
from conftest import OfflineLLM, authenticated_client  # noqa: E402

MISSING_ID = str(uuid.uuid4())

ALICE_PROJECT = "Alice research"
BOB_PROJECT = "Bob notes"


class Env:
    """Handles for the two accounts and the database they share."""

    def __init__(self, session, alice, bob, alice_user, bob_user):
        """Store the handles.

        Args:
            session: Database session the app is wired to.
            alice: Client authenticated as alice.
            bob: Client authenticated as bob.
            alice_user: Alice's user row.
            bob_user: Bob's user row.
        """
        self.session = session
        self.alice = alice
        self.bob = bob
        self.alice_user = alice_user
        self.bob_user = bob_user


@pytest.fixture
def env():
    """Two signed-in accounts sharing one database.

    Yields:
        An Env holding a client per account.
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(autocommit=False, autoflush=False, bind=engine)()

    def override_get_db():
        yield session

    production_app.dependency_overrides[get_db] = override_get_db
    # The mind map asks the configured LLM to name topics, and LLM_MODE
    # defaults to a local provider. Injecting an offline one keeps these
    # tests from opening a socket to a model server that is not there.
    production_app.dependency_overrides[get_mindmap_service] = (
        lambda: MindMapService(llm_service=OfflineLLM())
    )
    # The video summary asks the same configured LLM to write its narration.
    production_app.dependency_overrides[get_video_summary_service] = (
        lambda: VideoSummaryService(llm_service=OfflineLLM())
    )

    alice = authenticated_client(production_app, session, "alice")
    bob = authenticated_client(production_app, session, "bob")

    yield Env(
        session=session,
        alice=alice,
        bob=bob,
        alice_user=session.query(User).filter(User.username == "alice").first(),
        bob_user=session.query(User).filter(User.username == "bob").first(),
    )

    production_app.dependency_overrides.clear()
    session.close()
    engine.dispose()


def make_project(client, name=ALICE_PROJECT):
    """Create a project through the API and return its id.

    Args:
        client: The account's client.
        name: Project name.

    Returns:
        The new project's id.
    """
    response = client.post("/api/projects", json={"name": name})
    assert response.status_code in (200, 201), response.text
    return response.json()["id"]


def make_document(session, user, title="An upload"):
    """Insert a document owned by the given account.

    Inserted directly rather than uploaded, so the test needs neither the network
    nor the embedding model.

    Args:
        session: Database session.
        user: Owning account.
        title: Document title.

    Returns:
        The document's id.
    """
    document = Document(
        id=str(uuid.uuid4()),
        user_id=user.id,
        title=title,
        source_type="pdf",
        source_url="uploads/%s.pdf" % uuid.uuid4(),
        status="ready",
        meta_json={"filename": title},
    )
    session.add(document)
    session.commit()
    return document.id


def make_conversation(client, project_id, title="Notes"):
    """Create a conversation in a project and return its id.

    Args:
        client: The account's client.
        project_id: Project to create it in.
        title: Conversation title.

    Returns:
        The new conversation's id.
    """
    response = client.post(
        "/api/projects/%s/conversations" % project_id, json={"title": title})
    assert response.status_code in (200, 201), response.text
    return response.json()["id"]


class TestProjectIsolation:
    """A project belongs to the account that created it."""

    def test_listing_shows_only_your_own(self, env):
        make_project(env.alice)
        make_project(env.bob, BOB_PROJECT)

        alice_names = [p["name"] for p in env.alice.get("/api/projects").json()["projects"]]
        bob_names = [p["name"] for p in env.bob.get("/api/projects").json()["projects"]]

        assert alice_names == [ALICE_PROJECT]
        assert bob_names == [BOB_PROJECT]

    def test_listing_total_counts_only_your_own(self, env):
        make_project(env.alice)
        make_project(env.alice, "Alice second")
        make_project(env.bob, BOB_PROJECT)

        assert env.alice.get("/api/projects").json()["total"] == 2
        assert env.bob.get("/api/projects").json()["total"] == 1

    def test_reading_someone_elses_project_is_not_found(self, env):
        project_id = make_project(env.alice)
        assert env.bob.get("/api/projects/%s" % project_id).status_code == 404

    def test_updating_someone_elses_project_is_not_found(self, env):
        project_id = make_project(env.alice)

        response = env.bob.put("/api/projects/%s" % project_id, json={"name": "taken"})

        assert response.status_code == 404
        assert env.alice.get("/api/projects/%s" % project_id).json()["name"] == ALICE_PROJECT

    def test_deleting_someone_elses_project_is_not_found(self, env):
        project_id = make_project(env.alice)

        assert env.bob.delete("/api/projects/%s" % project_id).status_code == 404
        assert env.alice.get("/api/projects/%s" % project_id).status_code == 200

    def test_listing_someone_elses_project_documents_is_not_found(self, env):
        project_id = make_project(env.alice)
        assert env.bob.get("/api/projects/%s/documents" % project_id).status_code == 404

    def test_your_own_project_is_reachable(self, env):
        project_id = make_project(env.alice)
        assert env.alice.get("/api/projects/%s" % project_id).status_code == 200
        assert env.alice.get("/api/projects/%s/documents" % project_id).status_code == 200


class TestRefusalLeaksNothing:
    """Not yours and not found have to be the same answer."""

    def test_projects_answer_identically(self, env):
        project_id = make_project(env.alice)

        theirs = env.bob.get("/api/projects/%s" % project_id)
        missing = env.bob.get("/api/projects/%s" % MISSING_ID)

        assert theirs.status_code == missing.status_code == 404
        assert theirs.json() == missing.json()

    def test_documents_answer_identically(self, env):
        document_id = make_document(env.session, env.alice_user)

        theirs = env.bob.get("/api/docs/%s" % document_id)
        missing = env.bob.get("/api/docs/%s" % MISSING_ID)

        assert theirs.status_code == missing.status_code == 404
        assert theirs.json() == missing.json()


class TestDocumentIsolation:
    """Documents carry their own owner, including the ones in no project."""

    def test_reading_someone_elses_document_is_not_found(self, env):
        document_id = make_document(env.session, env.alice_user)
        assert env.bob.get("/api/docs/%s" % document_id).status_code == 404

    def test_status_of_someone_elses_document_is_not_found(self, env):
        document_id = make_document(env.session, env.alice_user)
        assert env.bob.get("/api/docs/%s/status" % document_id).status_code == 404

    def test_downloading_someone_elses_file_is_not_found(self, env):
        # This is the route that returns raw bytes, so it is the one that would
        # have handed over an entire upload.
        document_id = make_document(env.session, env.alice_user)
        assert env.bob.get("/api/docs/%s/file" % document_id).status_code == 404

    def test_deleting_someone_elses_document_is_not_found(self, env):
        document_id = make_document(env.session, env.alice_user)

        assert env.bob.delete("/api/docs/%s" % document_id).status_code == 404
        assert env.alice.get("/api/docs/%s" % document_id).status_code == 200

    def test_cannot_attach_someone_elses_document_to_your_project(self, env):
        # Authorising only the project would let Bob adopt Alice's document and
        # then read it through his own project's document list.
        alice_document = make_document(env.session, env.alice_user)
        bob_project = make_project(env.bob, BOB_PROJECT)

        response = env.bob.post(
            "/api/projects/%s/documents/%s" % (bob_project, alice_document))

        assert response.status_code == 404
        assert env.bob.get("/api/projects/%s/documents" % bob_project).json() == []

    def test_can_attach_your_own_document(self, env):
        document_id = make_document(env.session, env.bob_user, "Bob upload")
        project_id = make_project(env.bob, BOB_PROJECT)

        response = env.bob.post(
            "/api/projects/%s/documents/%s" % (project_id, document_id))

        assert response.status_code == 200
        titles = [d["title"] for d in env.bob.get(
            "/api/projects/%s/documents" % project_id).json()]
        assert titles == ["Bob upload"]


class TestIngestIsolation:
    """You cannot add sources to a project that is not yours."""

    def test_uploading_a_url_into_someone_elses_project_is_not_found(self, env):
        project_id = make_project(env.alice)

        response = env.bob.post(
            "/api/projects/%s/upload-url" % project_id,
            json={"url": "https://example.com"})

        assert response.status_code == 404

    def test_uploading_a_video_into_someone_elses_project_is_not_found(self, env):
        project_id = make_project(env.alice)

        response = env.bob.post(
            "/api/projects/%s/upload-youtube" % project_id,
            json={"youtube_url": "https://www.youtube.com/watch?v=x"})

        assert response.status_code == 404


class TestConversationIsolation:
    """Conversations follow the project that holds them."""

    def test_creating_one_in_someone_elses_project_is_not_found(self, env):
        project_id = make_project(env.alice)

        response = env.bob.post(
            "/api/projects/%s/conversations" % project_id, json={"title": "mine now"})

        assert response.status_code == 404

    def test_listing_someone_elses_is_not_found(self, env):
        project_id = make_project(env.alice)
        make_conversation(env.alice, project_id)

        assert env.bob.get("/api/projects/%s/conversations" % project_id).status_code == 404

    def test_reading_someone_elses_is_not_found(self, env):
        conversation_id = make_conversation(env.alice, make_project(env.alice))
        assert env.bob.get("/api/conversations/%s" % conversation_id).status_code == 404

    def test_renaming_someone_elses_is_not_found(self, env):
        conversation_id = make_conversation(env.alice, make_project(env.alice))

        response = env.bob.put(
            "/api/conversations/%s" % conversation_id, json={"title": "taken"})

        assert response.status_code == 404

    def test_deleting_someone_elses_is_not_found(self, env):
        conversation_id = make_conversation(env.alice, make_project(env.alice))

        assert env.bob.delete("/api/conversations/%s" % conversation_id).status_code == 404
        assert env.alice.get("/api/conversations/%s" % conversation_id).status_code == 200

    def test_your_own_is_reachable(self, env):
        project_id = make_project(env.alice)
        conversation_id = make_conversation(env.alice, project_id)

        assert env.alice.get("/api/conversations/%s" % conversation_id).status_code == 200
        assert env.alice.get("/api/projects/%s/conversations" % project_id).status_code == 200


class TestQueryIsolation:
    """Asking a question about someone else's project is not found."""

    def test_query_against_someone_elses_project(self, env):
        # The ownership check runs before any retrieval, which is why this holds
        # with the RAG service stubbed out.
        project_id = make_project(env.alice)

        response = env.bob.post("/api/query", json={
            "query": "what is in here?", "project_id": project_id})

        assert response.status_code == 404


class TestExportIsolation:
    """Export reads everything at once, so it needs the same check."""

    def test_exporting_someone_elses_project_is_not_found(self, env):
        project_id = make_project(env.alice)
        assert env.bob.get("/api/export/project/%s" % project_id).status_code == 404

    def test_exporting_someone_elses_summary_is_not_found(self, env):
        project_id = make_project(env.alice)
        assert env.bob.get("/api/export/project/%s/summary" % project_id).status_code == 404

    def test_exporting_someone_elses_conversation_is_not_found(self, env):
        conversation_id = make_conversation(env.alice, make_project(env.alice))
        assert env.bob.get(
            "/api/export/conversation/%s" % conversation_id).status_code == 404

    def test_a_batch_cannot_smuggle_one_in(self, env):
        alice_conversation = make_conversation(env.alice, make_project(env.alice))
        bob_project = make_project(env.bob, BOB_PROJECT)
        bob_conversation = make_conversation(env.bob, bob_project, "Mine")

        response = env.bob.post(
            "/api/export/batch", json=[bob_conversation, alice_conversation])

        assert response.status_code == 404


class TestMindMapIsolation:
    """A mind map reads every source in a project, so it is scoped too."""

    def test_mapping_someone_elses_project_is_not_found(self, env):
        project_id = make_project(env.alice)
        assert env.bob.get("/api/projects/%s/mindmap" % project_id).status_code == 404

    def test_your_own_project_can_be_mapped(self, env):
        """Pins that the route exists: an unmounted route also answers 404."""
        project_id = make_project(env.alice)

        response = env.alice.get("/api/projects/%s/mindmap" % project_id)

        assert response.status_code == 200
        assert response.json()["root"]["label"] == ALICE_PROJECT


class TestVideoSummaryIsolation:
    """A video summary narrates every source in a project, so it is scoped too."""

    def test_summarising_someone_elses_project_is_not_found(self, env):
        project_id = make_project(env.alice)
        assert env.bob.get(
            "/api/projects/%s/video-summary" % project_id).status_code == 404

    def test_your_own_project_can_be_summarised(self, env):
        """Pins that the route exists: an unmounted route also answers 404."""
        project_id = make_project(env.alice)

        response = env.alice.get("/api/projects/%s/video-summary" % project_id)

        assert response.status_code == 200
        assert response.json()["scenes"][0]["headline"] == ALICE_PROJECT


class TestCacheIsolation:
    """Cache invalidation reports on activity, so it is scoped too."""

    def test_invalidating_someone_elses_project_is_not_found(self, env):
        project_id = make_project(env.alice)
        assert env.bob.delete(
            "/api/cache/invalidate/project/%s" % project_id).status_code == 404

    def test_invalidating_someone_elses_document_is_not_found(self, env):
        document_id = make_document(env.session, env.alice_user)
        assert env.bob.delete(
            "/api/cache/invalidate/document/%s" % document_id).status_code == 404

    def test_your_own_project_can_be_invalidated(self, env):
        project_id = make_project(env.bob, BOB_PROJECT)
        assert env.bob.delete(
            "/api/cache/invalidate/project/%s" % project_id).status_code == 200

    def test_your_own_document_can_be_invalidated(self, env):
        document_id = make_document(env.session, env.bob_user)
        assert env.bob.delete(
            "/api/cache/invalidate/document/%s" % document_id).status_code == 200


class TestOwnerlessRowsBelongToNobody:
    """A row written before ownership existed is not everybody's."""

    def test_an_ownerless_project_is_invisible(self, env):
        env.session.add(Project(id=str(uuid.uuid4()), name="Legacy", meta_json={}))
        env.session.commit()

        assert env.alice.get("/api/projects").json()["projects"] == []
        assert env.bob.get("/api/projects").json()["projects"] == []

    def test_an_ownerless_document_is_unreachable(self, env):
        document = Document(
            id=str(uuid.uuid4()),
            title="Legacy upload",
            source_type="pdf",
            source_url="uploads/legacy.pdf",
            status="ready",
            meta_json={},
        )
        env.session.add(document)
        env.session.commit()

        assert env.alice.get("/api/docs/%s" % document.id).status_code == 404

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
from app.db.models import AudioOverview, Base, Document, Project, ProjectMember, User

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
from app.routers.project_overview import get_project_overview_service  # noqa: E402
from app.routers.audio_overview import get_audio_overview_worker  # noqa: E402
from app.services.project_overview import ProjectOverviewService  # noqa: E402
from app.services.mindmap import MindMapService  # noqa: E402
from app.services.video_summary import VideoSummaryService  # noqa: E402
from conftest import OfflineLLM, authenticated_client  # noqa: E402

MISSING_ID = str(uuid.uuid4())

ALICE_PROJECT = "Alice research"
BOB_PROJECT = "Bob notes"


class NoopAudioOverviewWorker:
    def notify(self):
        pass


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
    production_app.dependency_overrides[get_project_overview_service] = (
        lambda: ProjectOverviewService(llm_service=OfflineLLM())
    )
    production_app.dependency_overrides[get_audio_overview_worker] = (
        lambda: NoopAudioOverviewWorker()
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


def make_document(session, user, title="An upload", source_type="pdf", content=None):
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
        source_type=source_type,
        source_url="uploads/%s.pdf" % uuid.uuid4(),
        content=content,
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


def grant_project_role(env, project_id, role):
    """Give Bob a project role for an authorization test.

    Args:
        env: Two-account route-test environment.
        project_id: Project Alice owns.
        role: Viewer or editor role to grant.

    Returns:
        The stored membership.
    """
    membership = ProjectMember(
        project_id=project_id,
        user_id=env.bob_user.id,
        role=role,
    )
    env.session.add(membership)
    env.session.commit()
    return membership


class FakeDocumentService:
    """No-op ingestion/deletion service for role checks."""

    async def process_url(self, **kwargs):
        """Return a queued record without network or extraction work."""
        class QueuedDocument:
            id = "queued-shared-document"
            status = "queued"

        return QueuedDocument()

    def delete_document(self, db, document_id):
        """Report success if a route reaches the deletion service."""
        return True


class TestSharedProjectSourceRoles:
    """Shared roles govern project sources and related mutations."""

    def test_viewer_can_read_project_source_and_file(self, env, tmp_path, monkeypatch):
        project_id = make_project(env.alice)
        document_id = make_document(
            env.session, env.alice_user, source_type="pdf", content="Shared source text"
        )
        assert env.alice.post(
            "/api/projects/%s/documents/%s" % (project_id, document_id)
        ).status_code == 200
        grant_project_role(env, project_id, "viewer")
        source_file = tmp_path / "shared.pdf"
        source_file.write_bytes(b"shared pdf bytes")
        monkeypatch.setattr(
            "app.routers.files.resolve_stored_file", lambda _source_url: source_file
        )

        project = env.bob.get("/api/projects/%s" % project_id)
        documents = env.bob.get("/api/projects/%s/documents" % project_id)

        assert project.status_code == 200
        assert project.json()["role"] == "viewer"
        assert documents.status_code == 200
        assert documents.json()[0]["id"] == document_id
        assert env.bob.get(
            "/api/projects/%s/chat-settings" % project_id
        ).status_code == 200
        assert env.bob.put(
            "/api/projects/%s/chat-settings" % project_id,
            json={"role": "learning_guide"},
        ).status_code == 404
        assert env.bob.get("/api/docs/%s" % document_id).status_code == 200
        assert env.bob.get("/api/docs/%s/status" % document_id).status_code == 200
        assert env.bob.get("/api/docs/%s/content" % document_id).json() == {
            "content": "Shared source text"
        }
        file_response = env.bob.get("/api/docs/%s/file" % document_id)
        assert file_response.status_code == 200
        assert file_response.content == b"shared pdf bytes"

    def test_editor_can_add_remove_own_source_and_ingest_but_viewer_cannot(
        self, env, monkeypatch
    ):
        from app.routers.ingest import get_document_service

        project_id = make_project(env.alice)
        bob_document = make_document(env.session, env.bob_user, "Bob source")
        alice_document = make_document(env.session, env.alice_user, "Alice source")
        membership = grant_project_role(env, project_id, "viewer")
        production_app.dependency_overrides[get_document_service] = lambda: FakeDocumentService()
        upload_url = "/api/projects/%s/upload-url" % project_id
        add_url = "/api/projects/%s/documents/%s"

        assert env.bob.post(upload_url, json={"url": "https://example.com"}).status_code == 404
        assert env.bob.post(add_url % (project_id, bob_document)).status_code == 404

        membership.role = "editor"
        env.session.commit()
        upload = env.bob.post(upload_url, json={"url": "https://example.com"})
        foreign_source = env.bob.post(add_url % (project_id, alice_document))
        attached = env.bob.post(add_url % (project_id, bob_document))
        removed = env.bob.delete(add_url % (project_id, bob_document))

        assert upload.status_code == 200, upload.text
        assert foreign_source.status_code == 404
        assert attached.status_code == 200
        assert removed.status_code == 200
        assert env.bob.put(
            "/api/projects/%s/chat-settings" % project_id,
            json={"role": "learning_guide"},
        ).status_code == 200

    def test_editor_can_invalidate_shared_project_cache_but_viewer_cannot(
        self, env, monkeypatch
    ):
        from app.services.cache import cache_service

        project_id = make_project(env.alice)
        document_id = make_document(env.session, env.alice_user)
        assert env.alice.post(
            "/api/projects/%s/documents/%s" % (project_id, document_id)
        ).status_code == 200
        membership = grant_project_role(env, project_id, "viewer")
        monkeypatch.setattr(cache_service, "invalidate_project_cache", lambda _id: 1)
        monkeypatch.setattr(cache_service, "invalidate_document_cache", lambda _id: 1)
        project_cache = "/api/cache/invalidate/project/%s" % project_id
        document_cache = "/api/cache/invalidate/document/%s" % document_id

        assert env.bob.delete(project_cache).status_code == 404
        assert env.bob.delete(document_cache).status_code == 404

        membership.role = "editor"
        env.session.commit()
        assert env.bob.delete(project_cache).status_code == 200
        assert env.bob.delete(document_cache).status_code == 200

    def test_shared_editor_cannot_administer_project_or_mutate_owner_document(self, env):
        from app.routers.ingest import get_document_service

        project_id = make_project(env.alice)
        document_id = make_document(env.session, env.alice_user)
        assert env.alice.post(
            "/api/projects/%s/documents/%s" % (project_id, document_id)
        ).status_code == 200
        grant_project_role(env, project_id, "editor")
        production_app.dependency_overrides[get_document_service] = lambda: FakeDocumentService()

        assert env.bob.put(
            "/api/projects/%s" % project_id, json={"name": "Changed"}
        ).status_code == 404
        assert env.bob.post("/api/projects/%s/duplicate" % project_id).status_code == 404
        assert env.bob.delete("/api/projects/%s" % project_id).status_code == 404
        assert env.bob.put(
            "/api/docs/%s" % document_id, json={"title": "Changed"}
        ).status_code == 404
        assert env.bob.delete("/api/docs/%s" % document_id).status_code == 404
        assert env.alice.get("/api/docs/%s" % document_id).status_code == 200

    def test_removing_membership_revokes_project_and_direct_source_access(self, env):
        project_id = make_project(env.alice)
        document_id = make_document(env.session, env.alice_user)
        assert env.alice.post(
            "/api/projects/%s/documents/%s" % (project_id, document_id)
        ).status_code == 200
        grant_project_role(env, project_id, "viewer")
        assert env.bob.get("/api/projects/%s" % project_id).status_code == 200
        assert env.bob.get("/api/docs/%s/content" % document_id).status_code == 200

        env.session.query(ProjectMember).filter_by(
            project_id=project_id,
            user_id=env.bob_user.id,
        ).delete()
        env.session.commit()

        assert env.bob.get("/api/projects/%s" % project_id).status_code == 404
        assert env.bob.get("/api/docs/%s/content" % document_id).status_code == 404


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

    def test_someone_elses_chat_settings_are_not_found(self, env):
        project_id = make_project(env.alice)
        url = "/api/projects/%s/chat-settings" % project_id

        assert env.bob.get(url).status_code == 404
        assert env.bob.put(url, json={"role": "learning_guide"}).status_code == 404
        assert env.alice.get(url).json()["role"] == "default"

    def test_your_own_project_is_reachable(self, env):
        project_id = make_project(env.alice)
        assert env.alice.get("/api/projects/%s" % project_id).status_code == 200
        assert env.alice.get("/api/projects/%s/documents" % project_id).status_code == 200


class TestAudioOverviewIsolation:
    """An overview is only visible through the project that owns it."""

    def test_another_users_audio_overview_routes_are_not_found(self, env):
        project_id = make_project(env.alice)
        overview_id = str(uuid.uuid4())
        env.session.add(AudioOverview(
            id=overview_id,
            project_id=project_id,
            options_json={},
            script_json=[],
            file_path="uploads/audio_overviews/%s.mp3" % overview_id,
        ))
        env.session.commit()

        paths = [
            "/api/projects/%s/audio-overviews" % project_id,
            "/api/projects/%s/audio-overviews/%s" % (project_id, overview_id),
            "/api/projects/%s/audio-overviews/%s/file" % (project_id, overview_id),
        ]
        assert [env.bob.get(path).status_code for path in paths] == [404, 404, 404]
        assert env.bob.delete(paths[1]).status_code == 404


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

    def test_document_content_answers_identically_and_returns_owners_text(self, env):
        document_id = make_document(
            env.session,
            env.alice_user,
            source_type="docx",
            content="# Chapter One\n\nPrivate text",
        )

        theirs = env.bob.get("/api/docs/%s/content" % document_id)
        missing = env.bob.get("/api/docs/%s/content" % MISSING_ID)
        own = env.alice.get("/api/docs/%s/content" % document_id)

        assert theirs.status_code == missing.status_code == 404
        assert theirs.json() == missing.json()
        assert own.status_code == 200
        assert own.json() == {"content": "# Chapter One\n\nPrivate text"}


class TestDocumentIsolation:
    """Documents carry their own owner, including the ones in no project."""

    def test_reading_someone_elses_document_is_not_found(self, env):
        document_id = make_document(env.session, env.alice_user)
        assert env.bob.get("/api/docs/%s" % document_id).status_code == 404

    def test_status_of_someone_elses_document_is_not_found(self, env):
        document_id = make_document(env.session, env.alice_user)
        assert env.bob.get("/api/docs/%s/status" % document_id).status_code == 404

    def test_project_document_list_does_not_include_extracted_content(self, env):
        project_id = make_project(env.alice)
        document_id = make_document(
            env.session,
            env.alice_user,
            source_type="docx",
            content="Large extracted content stays on demand.",
        )

        attached = env.alice.post(
            "/api/projects/%s/documents/%s" % (project_id, document_id)
        )
        listed = env.alice.get(
            "/api/projects/%s/documents" % project_id
        )

        assert attached.status_code == 200
        assert listed.status_code == 200
        assert "content" not in listed.json()[0]

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
        assert env.bob.post("/api/export/project/%s/summary" % project_id).status_code == 404

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
        assert env.bob.post("/api/projects/%s/mindmap" % project_id).status_code == 404

    def test_your_own_project_can_be_mapped(self, env):
        """Pins that the route exists: an unmounted route also answers 404."""
        project_id = make_project(env.alice)

        response = env.alice.post("/api/projects/%s/mindmap" % project_id)

        assert response.status_code == 200
        assert response.json()["root"]["label"] == ALICE_PROJECT


class TestVideoSummaryIsolation:
    """A video summary narrates every source in a project, so it is scoped too."""

    def test_summarising_someone_elses_project_is_not_found(self, env):
        project_id = make_project(env.alice)
        assert env.bob.post(
            "/api/projects/%s/video-summary" % project_id).status_code == 404

    def test_your_own_project_can_be_summarised(self, env):
        """Pins that the route exists: an unmounted route also answers 404."""
        project_id = make_project(env.alice)

        response = env.alice.post("/api/projects/%s/video-summary" % project_id)

        assert response.status_code == 200
        assert response.json()["scenes"][0]["headline"] == ALICE_PROJECT

    def test_exporting_someone_elses_video_summary_is_not_found(self, env):
        project_id = make_project(env.alice)
        scenes = [
            {
                "id": "title", "kind": "title", "headline": "Title",
                "bullets": [], "narration": "Narration.",
            },
            {
                "id": "closing", "kind": "closing", "headline": "Close",
                "bullets": [], "narration": "Closing.",
            },
        ]

        response = env.bob.post(
            "/api/projects/%s/video-summary/pptx" % project_id,
            json={"scenes": scenes},
        )

        assert response.status_code == 404

    def test_your_own_video_summary_can_be_exported(self, env):
        project_id = make_project(env.alice)
        scenes = [
            {
                "id": "title", "kind": "title", "headline": "Title",
                "bullets": [], "narration": "Narration.",
            },
            {
                "id": "closing", "kind": "closing", "headline": "Close",
                "bullets": [], "narration": "Closing.",
            },
        ]

        response = env.alice.post(
            "/api/projects/%s/video-summary/pptx" % project_id,
            json={"scenes": scenes},
        )

        assert response.status_code == 200
        assert response.headers["content-type"].startswith(
            "application/vnd.openxmlformats-officedocument.presentationml.presentation"
        )

    def test_exporting_a_foreign_source_scene_is_not_found(self, env):
        project_id = make_project(env.alice)
        document_id = make_document(env.session, env.bob_user, title="Bob's source")
        scenes = [
            {
                "id": "title", "kind": "title", "headline": "Title",
                "bullets": [], "narration": "Narration.",
            },
            {
                "id": "doc-1", "kind": "source", "headline": "Source",
                "bullets": [], "narration": "Source narration.",
                "document_id": document_id,
            },
            {
                "id": "closing", "kind": "closing", "headline": "Close",
                "bullets": [], "narration": "Closing.",
            },
        ]

        response = env.alice.post(
            "/api/projects/%s/video-summary/pptx" % project_id,
            json={"scenes": scenes},
        )

        assert response.status_code == 404


class TestNoteIsolation:
    """Notes follow the project that holds them."""

    def test_listing_someone_elses_is_not_found(self, env):
        project_id = make_project(env.alice)
        assert env.bob.get("/api/projects/%s/notes" % project_id).status_code == 404

    def test_creating_one_in_someone_elses_project_is_not_found(self, env):
        project_id = make_project(env.alice)

        response = env.bob.post(
            "/api/projects/%s/notes" % project_id, json={"title": "mine now"})

        assert response.status_code == 404

    def test_editing_someone_elses_is_not_found(self, env):
        project_id = make_project(env.alice)
        note_id = env.alice.post(
            "/api/projects/%s/notes" % project_id, json={"title": "Alice"}).json()["id"]

        response = env.bob.put(
            "/api/projects/%s/notes/%s" % (project_id, note_id), json={"title": "taken"})

        assert response.status_code == 404

    def test_deleting_someone_elses_is_not_found(self, env):
        project_id = make_project(env.alice)
        note_id = env.alice.post(
            "/api/projects/%s/notes" % project_id, json={"title": "Alice"}).json()["id"]

        assert env.bob.delete(
            "/api/projects/%s/notes/%s" % (project_id, note_id)).status_code == 404
        assert [n["title"] for n in env.alice.get(
            "/api/projects/%s/notes" % project_id).json()] == ["Alice"]

    def test_your_own_are_reachable(self, env):
        """Pins that the routes exist: an unmounted route also answers 404."""
        project_id = make_project(env.alice)
        base = "/api/projects/%s/notes" % project_id
        note_id = env.alice.post(base, json={"title": "Alice"}).json()["id"]

        assert env.alice.get(base).status_code == 200
        assert env.alice.put(
            "%s/%s" % (base, note_id), json={"content": "edited"}).status_code == 200
        assert env.alice.delete("%s/%s" % (base, note_id)).status_code == 200


SELECTION_ROUTES = [
    "/api/projects/%s/mindmap",
    "/api/projects/%s/video-summary",
    "/api/export/project/%s/summary",
]


class TestSourceSelectionIsolation:
    """A source selection names document ids, so every one is checked."""

    def _own_project_with_two_sources(self, env):
        project_id = make_project(env.alice)
        kept = make_document(env.session, env.alice_user, "Kept source")
        dropped = make_document(env.session, env.alice_user, "Dropped source")
        for document_id in (kept, dropped):
            assert env.alice.post(
                "/api/projects/%s/documents/%s" % (project_id, document_id)
            ).status_code == 200
        return project_id, kept

    @pytest.mark.parametrize("route", SELECTION_ROUTES)
    def test_selecting_someone_elses_source_is_not_found(self, env, route):
        project_id = make_project(env.bob, BOB_PROJECT)
        alice_document = make_document(env.session, env.alice_user)

        foreign = env.bob.post(
            route % project_id, json={"document_ids": [alice_document]})
        missing = env.bob.post(route % project_id, json={"document_ids": [MISSING_ID]})

        assert foreign.status_code == 404
        assert foreign.json() == missing.json()

    def test_query_selecting_someone_elses_source_is_not_found(self, env):
        alice_document = make_document(env.session, env.alice_user)

        foreign = env.bob.post("/api/query", json={
            "query": "what is in here?", "document_ids": [alice_document]})
        missing = env.bob.post("/api/query", json={
            "query": "what is in here?", "document_ids": [MISSING_ID]})

        assert foreign.status_code == 404
        assert foreign.json() == missing.json()

    @pytest.mark.parametrize("route", SELECTION_ROUTES + ["/api/query"])
    def test_an_empty_selection_is_refused(self, env, route):
        project_id = make_project(env.alice)

        response = env.alice.post(
            route % project_id if "%s" in route else route,
            json={"query": "anything", "document_ids": []},
        )

        assert response.status_code == 422

    def test_the_mind_map_covers_only_the_selection(self, env):
        project_id, kept = self._own_project_with_two_sources(env)

        response = env.alice.post(
            "/api/projects/%s/mindmap" % project_id, json={"document_ids": [kept]})

        assert response.status_code == 200
        assert "Dropped source" not in response.text
        assert "Kept source" in response.text

    def test_the_video_summary_covers_only_the_selection(self, env):
        project_id, kept = self._own_project_with_two_sources(env)

        response = env.alice.post(
            "/api/projects/%s/video-summary" % project_id,
            json={"document_ids": [kept]},
        )

        sources = [s["document_id"] for s in response.json()["scenes"] if s["kind"] == "source"]
        assert sources == [kept]

    def test_the_report_covers_only_the_selection(self, env):
        project_id, kept = self._own_project_with_two_sources(env)

        response = env.alice.post(
            "/api/export/project/%s/summary" % project_id,
            json={"document_ids": [kept]},
        )

        assert response.status_code == 200
        assert "Kept source" in response.text
        assert "Dropped source" not in response.text

    def test_omitting_the_selection_keeps_every_source(self, env):
        project_id, _ = self._own_project_with_two_sources(env)

        response = env.alice.post("/api/export/project/%s/summary" % project_id)

        assert "Kept source" in response.text
        assert "Dropped source" in response.text


class TestProjectOverviewIsolation:
    """The overview reads a project's sources and follow-ups read its answers."""

    def test_reading_someone_elses_overview_is_not_found(self, env):
        project_id = make_project(env.alice)
        assert env.bob.get("/api/projects/%s/overview" % project_id).status_code == 404

    def test_follow_ups_for_someone_elses_conversation_are_not_found(self, env):
        conversation_id = make_conversation(env.alice, make_project(env.alice))
        assert env.bob.post(
            "/api/conversations/%s/follow-ups" % conversation_id).status_code == 404

    def test_your_own_overview_and_follow_ups_are_reachable(self, env):
        """Pins that the routes exist: an unmounted route also answers 404."""
        project_id = make_project(env.alice)
        conversation_id = make_conversation(env.alice, project_id)

        assert env.alice.get("/api/projects/%s/overview" % project_id).status_code == 200
        assert env.alice.post(
            "/api/conversations/%s/follow-ups" % conversation_id).status_code == 200


class TestProjectDuplicateIsolation:
    """Duplication cannot be used to inspect or copy another account's project."""

    def test_duplicating_someone_elses_project_is_not_found(self, env):
        project_id = make_project(env.alice)

        assert env.bob.post(
            "/api/projects/%s/duplicate" % project_id).status_code == 404
        assert env.bob.get("/api/projects").json()["projects"] == []


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


class TestTextRenameAndRatingIsolation:
    """Pasting text, renaming a source and rating an answer check ownership."""

    def test_pasting_text_into_someone_elses_project_is_not_found(self, env):
        project_id = make_project(env.alice)

        response = env.bob.post(
            "/api/projects/%s/upload-text" % project_id,
            json={"title": "Mine now", "text": "Some text"})

        assert response.status_code == 404

    def test_renaming_someone_elses_document_is_not_found(self, env):
        document_id = make_document(env.session, env.alice_user, "Alice upload")

        response = env.bob.put(
            "/api/docs/%s" % document_id, json={"title": "taken"})

        assert response.status_code == 404
        assert env.alice.get(
            "/api/docs/%s" % document_id).json()["title"] == "Alice upload"

    def test_rating_an_answer_in_someone_elses_conversation_is_not_found(self, env):
        from app.db.models import Message

        conversation_id = make_conversation(env.alice, make_project(env.alice))
        message = Message(
            id=str(uuid.uuid4()),
            conversation_id=conversation_id,
            role="assistant",
            text="An answer",
        )
        env.session.add(message)
        env.session.commit()
        url = "/api/conversations/%s/messages/%s/rating" % (
            conversation_id, message.id)

        assert env.bob.put(url, json={"rating": "down"}).status_code == 404
        assert env.alice.put(url, json={"rating": "up"}).status_code == 200
        env.session.refresh(message)
        assert message.rating == "up"

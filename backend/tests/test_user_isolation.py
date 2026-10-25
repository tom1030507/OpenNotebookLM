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
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import Settings, get_settings
from app.db.database import get_db
from app.db.models import (
    AudioOverview,
    Base,
    Conversation,
    Document,
    Message,
    Project,
    ProjectDocument,
    ProjectMember,
    User,
)

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
from app.routers.study import get_study_service  # noqa: E402
from app.routers.report import get_report_service  # noqa: E402
from app.routers.table import get_table_service  # noqa: E402
from app.routers.project_overview import get_project_overview_service  # noqa: E402
from app.routers.audio_overview import get_audio_overview_worker  # noqa: E402
from app.services.project_overview import ProjectOverviewService  # noqa: E402
from app.services.mindmap import MindMapService  # noqa: E402
from app.services.video_summary import VideoSummaryService  # noqa: E402
from app.services.study import StudyService  # noqa: E402
from app.services.llm import FALLBACK_MODEL, LLMService  # noqa: E402
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
    production_app.dependency_overrides[get_study_service] = (
        lambda: StudyService(llm_service=OfflineLLM())
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

    class QueuedDocument:
        id = "queued-shared-document"
        status = "queued"

    async def _queued(self, **kwargs):
        kwargs["operation_lease"].release()
        return self.QueuedDocument()

    async def process_pdf_upload(self, **kwargs):
        return await self._queued(**kwargs)

    async def process_text(self, **kwargs):
        return await self._queued(**kwargs)

    async def process_youtube(self, **kwargs):
        return await self._queued(**kwargs)

    async def process_url(self, **kwargs):
        """Return a queued record without network or extraction work."""
        return await self._queued(**kwargs)

    def enqueue_resync(self, db, project_id, document, operation_lease):
        """Complete the route boundary without starting an ingestion worker."""
        operation_lease.release()
        document.status = "processing"
        db.commit()
        return document

    def delete_document(self, db, document_id):
        """Report success if a route reaches the deletion service."""
        return True


class TestSharedProjectSourceRoles:
    """Shared roles govern project sources and related mutations."""

    def test_resync_requires_project_editor_and_existing_url_source(self, env):
        from app.routers.ingest import get_document_service

        project_id = make_project(env.alice)
        document_id = make_document(
            env.session,
            env.alice_user,
            title="Article",
            source_type="url",
        )
        assert env.alice.post(
            "/api/projects/%s/documents/%s" % (project_id, document_id)
        ).status_code == 200
        membership = grant_project_role(env, project_id, "viewer")
        production_app.dependency_overrides[get_document_service] = (
            lambda: FakeDocumentService()
        )

        route = "/api/projects/%s/documents/%s/resync" % (project_id, document_id)
        assert env.bob.post(route).status_code == 404

        membership.role = "editor"
        env.session.commit()
        response = env.bob.post(route)
        assert response.status_code == 200, response.text
        assert response.json()["doc_id"] == document_id
        assert response.json()["status"] == "processing"

        pdf_id = make_document(env.session, env.alice_user, source_type="pdf")
        assert env.alice.post(
            "/api/projects/%s/documents/%s" % (project_id, pdf_id)
        ).status_code == 200
        assert env.alice.post(
            "/api/projects/%s/documents/%s/resync" % (project_id, pdf_id)
        ).status_code == 400

    def test_watched_folder_is_owner_only_and_confined_to_server_root(
        self, env, tmp_path, monkeypatch
    ):
        project_id = make_project(env.alice)
        root = tmp_path / "watch-root"
        allowed = root / "project"
        outside = tmp_path / "outside"
        allowed.mkdir(parents=True)
        outside.mkdir()
        monkeypatch.setattr(
            "app.routers.projects.get_settings",
            lambda: Settings(watched_folder_root=str(root)),
        )
        grant_project_role(env, project_id, "viewer")
        route = "/api/projects/%s/watched-folder" % project_id

        assert env.bob.get(route).status_code == 404
        assert env.bob.put(route, json={"path": str(allowed)}).status_code == 404
        invalid = env.alice.put(route, json={"path": str(outside)})
        assert invalid.status_code == 422

        saved = env.alice.put(route, json={"path": str(allowed)})
        assert saved.status_code == 200, saved.text
        assert saved.json() == {"enabled": True, "path": str(allowed.resolve())}
        assert env.alice.get(route).json() == saved.json()
        cleared = env.alice.put(route, json={"path": None})
        assert cleared.status_code == 200
        assert cleared.json()["path"] is None

    def test_invalid_foreign_source_link_is_hidden_from_project_reads(self, env):
        project_id = make_project(env.alice)
        document_id = make_document(
            env.session, env.bob_user, title="Bob private source", content="Private text"
        )
        env.session.add(ProjectDocument(project_id=project_id, document_id=document_id))
        env.session.commit()

        listed = env.alice.get("/api/projects/%s/documents" % project_id)
        direct = env.alice.get("/api/docs/%s" % document_id)
        query = env.alice.post("/api/query", json={
            "query": "Read Bob's source",
            "project_id": project_id,
            "document_ids": [document_id],
        })
        exported = env.alice.get("/api/export/project/%s?format=json" % project_id)

        assert listed.status_code == 200
        assert all(row["id"] != document_id for row in listed.json())
        assert direct.status_code == 404
        assert query.status_code == 404
        assert exported.status_code == 200
        assert all(row["id"] != document_id for row in exported.json()["documents"])

    def test_removing_source_owner_keeps_linked_source_in_project(self, env):
        project_id = make_project(env.alice)
        document_id = make_document(
            env.session, env.bob_user, title="Bob source", content="Shared text"
        )
        grant_project_role(env, project_id, "editor")
        attached = env.bob.post(
            "/api/projects/%s/documents/%s" % (project_id, document_id)
        )
        assert attached.status_code == 200

        removed = env.alice.delete(
            "/api/projects/%s/members/%s" % (project_id, env.bob_user.id)
        )

        assert removed.status_code == 200
        assert env.alice.get("/api/docs/%s/content" % document_id).json() == {
            "content": "Shared text"
        }
        listed = env.alice.get("/api/projects/%s/documents" % project_id)
        assert [row["id"] for row in listed.json()] == [document_id]
        exported = env.alice.get("/api/export/project/%s?format=json" % project_id)
        assert [row["id"] for row in exported.json()["documents"]] == [document_id]

    def test_private_and_missing_answer_ids_have_the_same_note_error(self, env):
        project_id = make_project(env.alice)
        conversation_id = make_conversation(env.alice, project_id)
        message = Message(
            id=str(uuid.uuid4()), conversation_id=conversation_id,
            role="assistant", text="Private answer",
        )
        env.session.add(message)
        env.session.commit()
        grant_project_role(env, project_id, "editor")
        base = "/api/projects/%s/notes" % project_id

        private = env.bob.post(base, json={
            "title": "Private", "source_message_id": message.id,
        })
        missing = env.bob.post(base, json={
            "title": "Missing", "source_message_id": "not-a-message",
        })

        assert private.status_code == missing.status_code == 404
        assert private.json() == missing.json()

    def test_every_ingest_route_requires_editor_access(self, env, monkeypatch):
        from app.routers.ingest import get_document_service

        project_id = make_project(env.alice)
        production_app.dependency_overrides[get_document_service] = lambda: FakeDocumentService()
        monkeypatch.setattr("app.routers.ingest.settings.enable_yt_transcription", True)
        monkeypatch.setattr(
            "app.services.batch_ingestion.validate_public_http_url",
            lambda url: url,
        )

        def upload_statuses(client):
            base = "/api/projects/%s" % project_id
            return [
                client.post(
                    "%s/upload" % base,
                    files={"file": ("shared.pdf", b"shared source", "application/pdf")},
                ).status_code,
                client.post(
                    "%s/upload-url" % base,
                    json={"url": "https://example.com"},
                ).status_code,
                client.post(
                    "%s/upload-youtube" % base,
                    json={"youtube_url": "https://www.youtube.com/watch?v=video"},
                ).status_code,
                client.post(
                    "%s/upload-batch" % base,
                    json={"urls": ["https://example.com"]},
                ).status_code,
                client.post(
                    "%s/upload-text" % base,
                    json={"title": "Shared notes", "text": "Source text"},
                ).status_code,
            ]

        assert upload_statuses(env.bob) == [404, 404, 404, 404, 404]
        membership = grant_project_role(env, project_id, "viewer")
        assert upload_statuses(env.bob) == [404, 404, 404, 404, 404]

        membership.role = "editor"
        env.session.commit()
        assert upload_statuses(env.bob) == [200, 200, 200, 200, 200]
        assert upload_statuses(env.alice) == [200, 200, 200, 200, 200]

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

    def test_members_can_create_and_read_but_only_editors_can_delete(
        self, env, monkeypatch, tmp_path
    ):
        from app.routers import audio_overview

        project_id = make_project(env.alice)
        document_id = make_document(
            env.session, env.alice_user, title="Shared audio source", content="Climate evidence."
        )
        unlinked = make_document(env.session, env.bob_user, title="Unlinked source")
        assert env.alice.post(
            "/api/projects/%s/documents/%s" % (project_id, document_id)
        ).status_code == 200
        grant_project_role(env, project_id, "viewer")
        production_app.dependency_overrides[get_settings] = lambda: Settings(
            audio_overview_tts_enabled=True
        )
        audio_file = tmp_path / "shared.mp3"
        audio_file.write_bytes(b"ID3 shared audio")
        monkeypatch.setattr(audio_overview, "resolve_audio_file", lambda _key: audio_file)

        created = env.bob.post(
            "/api/projects/%s/audio-overviews" % project_id,
            json={"document_ids": [document_id]},
        )
        assert created.status_code == 202, created.text
        rejected = env.bob.post(
            "/api/projects/%s/audio-overviews" % project_id,
            json={"document_ids": [unlinked]},
        )
        assert rejected.status_code == 404
        overview_id = created.json()["id"]
        overview = env.session.query(AudioOverview).filter_by(id=overview_id).first()
        overview.status = "ready"
        overview.file_path = "uploads/audio_overviews/shared.mp3"
        overview.script_json = [{"speaker": "A", "text": "Shared transcript."}]
        env.session.commit()

        assert env.bob.get(
            "/api/projects/%s/audio-overviews" % project_id
        ).status_code == 200
        assert env.bob.get(
            "/api/projects/%s/audio-overviews/%s" % (project_id, overview_id)
        ).status_code == 200
        assert env.bob.get(
            "/api/projects/%s/audio-overviews/%s/file" % (project_id, overview_id)
        ).content == b"ID3 shared audio"
        assert env.bob.delete(
            "/api/projects/%s/audio-overviews/%s" % (project_id, overview_id)
        ).status_code == 404

        env.session.query(ProjectMember).filter_by(
            project_id=project_id, user_id=env.bob_user.id
        ).update({"role": "editor"})
        env.session.commit()
        assert env.bob.delete(
            "/api/projects/%s/audio-overviews/%s" % (project_id, overview_id)
        ).status_code == 204


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

    def test_source_guide_answers_identically_for_another_user_and_missing_id(
        self, env, monkeypatch,
    ):
        monkeypatch.setattr(
            LLMService,
            "generate",
            lambda self, prompt, **kwargs: {
                "text": "No provider is configured.",
                "model": FALLBACK_MODEL,
                "usage": {},
            },
        )
        document_id = make_document(
            env.session,
            env.alice_user,
            title="Observatory notes",
            source_type="text",
            content=(
                "The observatory checks equipment every night. "
                "Operators record weather conditions. "
                "The archive stores every image."
            ),
        )

        theirs = env.bob.get("/api/docs/%s/guide" % document_id)
        missing = env.bob.get("/api/docs/%s/guide" % MISSING_ID)
        own = env.alice.get("/api/docs/%s/guide" % document_id)

        assert theirs.status_code == missing.status_code == 404
        assert theirs.json() == missing.json()
        assert own.status_code == 200
        assert len(own.json()["topics"]) >= 3

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

    def test_web_discovery_requires_editor_access(self, env):
        from app.routers.ingest import get_web_search_service

        project_id = make_project(env.alice)
        calls = []

        class SearchService:
            enabled = True

            def search(self, query, count):
                calls.append((query, count))
                return [{
                    "title": "Result",
                    "url": "https://example.com/result",
                    "snippet": "Snippet",
                }]

        production_app.dependency_overrides[get_web_search_service] = SearchService

        assert env.bob.post(
            "/api/projects/%s/discover" % project_id,
            json={"query": "topic"},
        ).status_code == 404
        membership = grant_project_role(env, project_id, "viewer")
        assert env.bob.post(
            "/api/projects/%s/discover" % project_id,
            json={"query": "topic"},
        ).status_code == 404
        assert calls == []

        membership.role = "editor"
        env.session.commit()
        response = env.bob.post(
            "/api/projects/%s/discover" % project_id,
            json={"query": "topic"},
        )

        assert response.status_code == 200, response.text
        assert calls == [("topic", 10)]

    def test_uploading_a_url_into_someone_elses_project_is_not_found(self, env):
        project_id = make_project(env.alice)

        response = env.bob.post(
            "/api/projects/%s/upload-url" % project_id,
            json={"url": "https://example.com"})

        assert response.status_code == 404

        batch_response = env.bob.post(
            "/api/projects/%s/upload-batch" % project_id,
            json={"urls": ["https://example.com"]},
        )

        assert batch_response.status_code == 404

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

    def test_shared_project_conversations_belong_to_the_creator(self, env):
        project_id = make_project(env.alice)
        alice_conversation = make_conversation(env.alice, project_id, "Alice private")
        grant_project_role(env, project_id, "viewer")

        bob_created = env.bob.post(
            "/api/projects/%s/conversations" % project_id,
            json={"title": "Bob private"},
        )
        assert bob_created.status_code == 200, bob_created.text
        bob_conversation = bob_created.json()["id"]
        stored = env.session.query(Conversation).filter_by(id=bob_conversation).first()
        assert stored.user_id == env.bob_user.id

        message = Message(
            id=str(uuid.uuid4()),
            conversation_id=bob_conversation,
            role="assistant",
            text="Bob's answer",
        )
        env.session.add(message)
        env.session.commit()

        assert env.bob.get("/api/conversations/%s" % bob_conversation).status_code == 200
        assert env.alice.get("/api/conversations/%s" % bob_conversation).status_code == 404
        assert env.bob.get("/api/conversations/%s" % alice_conversation).status_code == 404
        bob_list = env.bob.get("/api/projects/%s/conversations" % project_id)
        alice_list = env.alice.get("/api/projects/%s/conversations" % project_id)
        assert [row["id"] for row in bob_list.json()] == [bob_conversation]
        assert [row["id"] for row in alice_list.json()] == [alice_conversation]
        assert env.alice.put(
            "/api/conversations/%s/messages/%s/rating" % (bob_conversation, message.id),
            json={"rating": "up"},
        ).status_code == 404
        assert env.bob.put(
            "/api/conversations/%s/messages/%s/rating" % (bob_conversation, message.id),
            json={"rating": "up"},
        ).status_code == 200
        assert env.alice.get(
            "/api/export/conversation/%s" % bob_conversation
        ).status_code == 404
        assert env.bob.get(
            "/api/export/conversation/%s" % bob_conversation
        ).status_code == 200

        env.session.query(ProjectMember).filter_by(
            project_id=project_id, user_id=env.bob_user.id
        ).delete()
        env.session.commit()
        assert env.bob.get("/api/conversations/%s" % bob_conversation).status_code == 200
        assert env.bob.get(
            "/api/projects/%s/conversations" % project_id
        ).status_code == 404
        assert env.bob.post("/api/query", json={
            "query": "Try the revoked project again",
            "conversation_id": bob_conversation,
        }).status_code == 404

    def test_legacy_conversations_are_listed_only_for_the_project_owner(self, env):
        project_id = make_project(env.alice)
        conversation = Conversation(
            id=str(uuid.uuid4()), project_id=project_id,
            user_id=None, title="Legacy owner chat",
        )
        env.session.add(conversation)
        env.session.commit()
        grant_project_role(env, project_id, "viewer")

        owner_list = env.alice.get("/api/projects/%s/conversations" % project_id)
        member_list = env.bob.get("/api/projects/%s/conversations" % project_id)

        assert [row["id"] for row in owner_list.json()] == [conversation.id]
        assert member_list.json() == []
        assert env.alice.get(
            "/api/conversations/%s" % conversation.id
        ).status_code == 200
        assert env.bob.get(
            "/api/conversations/%s" % conversation.id
        ).status_code == 404


class TestQueryIsolation:
    """Asking a question about someone else's project is not found."""

    def test_query_against_someone_elses_project(self, env):
        # The ownership check runs before any retrieval, which is why this holds
        # with the RAG service stubbed out.
        project_id = make_project(env.alice)

        response = env.bob.post("/api/query", json={
            "query": "what is in here?", "project_id": project_id})

        assert response.status_code == 404

    def test_stream_query_cannot_read_someone_elses_conversation(self, env):
        project_id = make_project(env.alice)
        conversation_id = make_conversation(env.alice, project_id)

        response = env.bob.post("/api/query/stream", json={
            "query": "what is in here?", "conversation_id": conversation_id,
        })

        assert response.status_code == 404
        assert response.json()["detail"] == "Conversation not found"

    def test_shared_query_uses_only_project_sources_and_keeps_no_project_scope_owned(
        self, env
    ):
        from app.routers.query import get_rag_service

        class RecordingRAG:
            def __init__(self):
                self.project_documents = None
                self.owned_documents = None

            def query_with_conversation(self, **kwargs):
                self.project_documents = kwargs["allowed_document_ids"]
                return {
                    "answer": "shared answer", "sources": [], "chunks_used": 0,
                    "model_used": "test", "usage": {},
                }

            def query(self, **kwargs):
                self.owned_documents = kwargs["allowed_document_ids"]
                return {
                    "answer": "private answer", "sources": [], "chunks_used": 0,
                    "model_used": "test", "usage": {},
                }

        project_id = make_project(env.alice)
        linked = make_document(env.session, env.alice_user, "Linked source")
        unlinked = make_document(env.session, env.alice_user, "Unlinked source")
        bob_owned = make_document(env.session, env.bob_user, "Bob private source")
        assert env.alice.post(
            "/api/projects/%s/documents/%s" % (project_id, linked)
        ).status_code == 200
        grant_project_role(env, project_id, "viewer")
        rag = RecordingRAG()
        production_app.dependency_overrides[get_rag_service] = lambda: rag

        response = env.bob.post(
            "/api/query",
            json={
                "query": "Ask about the shared source",
                "project_id": project_id,
                "document_ids": [linked],
            },
        )
        rejected = env.bob.post(
            "/api/query",
            json={
                "query": "Try an unlinked source",
                "project_id": project_id,
                "document_ids": [unlinked],
            },
        )
        private = env.bob.post("/api/query", json={"query": "My own source"})

        assert response.status_code == 200, response.text
        assert rag.project_documents == [linked]
        assert rejected.status_code == 404
        assert private.status_code == 200, private.text
        assert rag.owned_documents == [bob_owned]


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

    def test_shared_project_exports_sources_and_only_the_callers_chats(self, env):
        project_id = make_project(env.alice)
        linked = make_document(env.session, env.alice_user, "Shared export source")
        unlinked = make_document(env.session, env.alice_user, "Unlinked export source")
        assert env.alice.post(
            "/api/projects/%s/documents/%s" % (project_id, linked)
        ).status_code == 200
        alice_conversation = make_conversation(env.alice, project_id, "Alice private")
        env.session.add(Conversation(
            id=str(uuid.uuid4()),
            project_id=project_id,
            title="Legacy owner conversation",
        ))
        env.session.commit()
        grant_project_role(env, project_id, "viewer")
        bob_created = env.bob.post(
            "/api/projects/%s/conversations" % project_id,
            json={"title": "Bob private"},
        )
        assert bob_created.status_code == 200, bob_created.text
        bob_conversation = bob_created.json()["id"]
        project = env.session.get(Project, project_id)
        project.overview_json = {
            "overview": "A summary of the shared source.",
            "questions": [],
            "source_ids": [linked],
        }
        env.session.commit()

        bob_export = env.bob.get(
            "/api/export/project/%s?format=json" % project_id
        )
        bob_summary = env.bob.post("/api/export/project/%s/summary" % project_id)
        bob_selected_summary = env.bob.post(
            "/api/export/project/%s/summary" % project_id,
            json={"document_ids": [linked]},
        )
        rejected_selection = env.bob.post(
            "/api/export/project/%s/summary" % project_id,
            json={"document_ids": [unlinked]},
        )
        alice_export = env.alice.get(
            "/api/export/project/%s?format=json" % project_id
        )

        assert bob_export.status_code == 200, bob_export.text
        bob_data = bob_export.json()
        assert [doc["id"] for doc in bob_data["documents"]] == [linked]
        assert [row["id"] for row in bob_data["conversations"]] == [bob_conversation]
        assert bob_summary.status_code == 200
        assert "A summary of the shared source." in bob_summary.text
        assert "**Conversations**" not in bob_summary.text
        assert "Bob private" not in bob_summary.text
        assert "Alice private" not in bob_summary.text
        assert bob_selected_summary.status_code == 200
        assert "A summary of the shared source." in bob_selected_summary.text
        assert rejected_selection.status_code == 404

        assert alice_export.status_code == 200
        alice_data = alice_export.json()
        assert {row["title"] for row in alice_data["conversations"]} == {
            "Alice private",
            "Legacy owner conversation",
        }
        assert any(
            row["id"] == alice_conversation for row in alice_data["conversations"]
        )
        assert env.alice.get(
            "/api/projects/%s" % project_id
        ).json()["conversation_count"] == 2
        assert env.bob.get(
            "/api/projects/%s" % project_id
        ).json()["conversation_count"] == 1


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

    def test_members_can_map_linked_sources_and_cannot_select_unlinked_sources(self, env):
        project_id = make_project(env.alice)
        linked = make_document(
            env.session, env.bob_user, "Member source", "txt", "Exclusive study material."
        )
        unlinked = make_document(env.session, env.bob_user, "Private source")
        grant_project_role(env, project_id, "editor")
        assert env.bob.post(
            "/api/projects/%s/documents/%s" % (project_id, linked)
        ).status_code == 200
        env.session.query(ProjectMember).filter_by(
            project_id=project_id, user_id=env.bob_user.id
        ).update({"role": "viewer"})
        env.session.commit()

        response = env.bob.post(
            "/api/projects/%s/mindmap" % project_id,
            json={"document_ids": [linked]},
        )
        rejected = env.bob.post(
            "/api/projects/%s/mindmap" % project_id,
            json={"document_ids": [unlinked]},
        )

        assert response.status_code == 200, response.text
        assert response.json()["total_source_count"] == 1
        assert rejected.status_code == 404


class TestSharedStudioIsolation:
    """Studio readers can use linked sources and keep selections project-bound."""

    def test_video_summary_and_pptx_are_available_to_viewers(self, env):
        project_id = make_project(env.alice)
        linked = make_document(
            env.session, env.bob_user, "Member source", "txt", "Shared material is useful."
        )
        unlinked = make_document(env.session, env.bob_user, "Private source")
        grant_project_role(env, project_id, "editor")
        assert env.bob.post(
            "/api/projects/%s/documents/%s" % (project_id, linked)
        ).status_code == 200
        env.session.query(ProjectMember).filter_by(
            project_id=project_id, user_id=env.bob_user.id
        ).update({"role": "viewer"})
        env.session.commit()

        summary = env.bob.post(
            "/api/projects/%s/video-summary" % project_id,
            json={"document_ids": [linked]},
        )
        rejected_summary = env.bob.post(
            "/api/projects/%s/video-summary" % project_id,
            json={"document_ids": [unlinked]},
        )
        assert summary.status_code == 200, summary.text
        assert rejected_summary.status_code == 404
        assert [scene["document_id"] for scene in summary.json()["scenes"]
                if scene["kind"] == "source"] == [linked]
        exported = env.bob.post(
            "/api/projects/%s/video-summary/pptx" % project_id,
            json={"scenes": summary.json()["scenes"]},
        )
        assert exported.status_code == 200, exported.text

        private_scenes = [dict(scene) for scene in summary.json()["scenes"]]
        next(scene for scene in private_scenes if scene["kind"] == "source")[
            "document_id"
        ] = unlinked
        rejected = env.bob.post(
            "/api/projects/%s/video-summary/pptx" % project_id,
            json={"scenes": private_scenes},
        )
        assert rejected.status_code == 404


class TestStudyIsolation:
    """Study generation can read only a visible project and its linked sources."""

    def test_flashcards_and_quiz_require_project_visibility(self, env):
        project_id = make_project(env.alice)

        for mode in ("flashcards", "quiz"):
            path = "/api/projects/%s/%s" % (project_id, mode)
            assert env.bob.post(path, json={"count": 5}).status_code == 404
            assert TestClient(production_app).post(path, json={"count": 5}).status_code == 401

    def test_flashcards_and_quiz_reject_documents_outside_project(self, env):
        project_id = make_project(env.alice)
        unlinked = make_document(env.session, env.alice_user, "Unlinked source")
        foreign = make_document(env.session, env.bob_user, "Private source")

        for mode in ("flashcards", "quiz"):
            path = "/api/projects/%s/%s" % (project_id, mode)
            for document_id in (unlinked, foreign):
                response = env.alice.post(
                    path, json={"document_ids": [document_id], "count": 5},
                )
                assert response.status_code == 404


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

    def test_converting_someone_elses_note_to_a_source_is_not_found(self, env):
        project_id = make_project(env.alice)
        base = "/api/projects/%s/notes" % project_id
        note_id = env.alice.post(
            base, json={"title": "Alice", "content": "Private note"}
        ).json()["id"]

        response = env.bob.post("%s/%s/source" % (base, note_id))

        assert response.status_code == 404
        assert env.bob.post("%s/sources" % base).status_code == 404

    def test_viewers_cannot_convert_shared_notes_to_sources(self, env):
        project_id = make_project(env.alice)
        base = "/api/projects/%s/notes" % project_id
        note_id = env.alice.post(
            base, json={"title": "Owner note", "content": "Shared note"}
        ).json()["id"]
        grant_project_role(env, project_id, "viewer")

        response = env.bob.post("%s/%s/source" % (base, note_id))

        assert response.status_code == 404
        assert env.bob.post("%s/sources" % base).status_code == 404

    def test_your_own_are_reachable(self, env):
        """Pins that the routes exist: an unmounted route also answers 404."""
        project_id = make_project(env.alice)
        base = "/api/projects/%s/notes" % project_id
        note_id = env.alice.post(base, json={"title": "Alice"}).json()["id"]

        assert env.alice.get(base).status_code == 200
        assert env.alice.put(
            "%s/%s" % (base, note_id), json={"content": "edited"}).status_code == 200
        assert env.alice.delete("%s/%s" % (base, note_id)).status_code == 200

    def test_shared_notes_are_readable_but_writable_by_editors(self, env):
        project_id = make_project(env.alice)
        base = "/api/projects/%s/notes" % project_id
        note_id = env.alice.post(base, json={"title": "Owner note"}).json()["id"]
        conversation_id = make_conversation(env.alice, project_id)
        message = Message(
            id=str(uuid.uuid4()), conversation_id=conversation_id,
            role="assistant", text="Alice's private answer",
        )
        env.session.add(message)
        env.session.commit()
        grant_project_role(env, project_id, "viewer")

        readable = env.bob.get(base)
        assert readable.status_code == 200, readable.text
        assert [note["id"] for note in readable.json()] == [note_id]
        assert env.bob.post(base, json={"title": "Viewer note"}).status_code == 404
        assert env.bob.put(
            "%s/%s" % (base, note_id), json={"title": "Changed by viewer"}
        ).status_code == 404
        assert env.bob.delete("%s/%s" % (base, note_id)).status_code == 404

        env.session.query(ProjectMember).filter_by(
            project_id=project_id, user_id=env.bob_user.id
        ).update({"role": "editor"})
        env.session.commit()
        private_answer = env.bob.post(base, json={
            "title": "Copied private answer", "source_message_id": message.id,
        })
        assert private_answer.status_code == 404
        created = env.bob.post(base, json={"title": "Editor note", "content": "Shared."})
        assert created.status_code == 200, created.text
        assert env.bob.put(
            "%s/%s" % (base, note_id), json={"title": "Edited by editor"}
        ).status_code == 200
        assert env.bob.delete("%s/%s" % (base, note_id)).status_code == 200


class TestReportIsolation:
    """Generated reports only receive sources authorized for the project."""

    def _install_report_stub(self, monkeypatch):
        class StubReportService:
            def __init__(self):
                self.calls = []

            def generate(
                self, db, project_id, report_format, instruction, document_ids, options=None,
            ):
                self.calls.append((project_id, report_format, instruction, document_ids))
                return {"markdown": "Report [Source 1].", "citations": []}

        service = StubReportService()
        monkeypatch.setitem(
            production_app.dependency_overrides,
            get_report_service,
            lambda: service,
        )
        return service

    def test_generating_for_someone_elses_project_is_not_found(self, env, monkeypatch):
        service = self._install_report_stub(monkeypatch)
        project_id = make_project(env.alice)

        foreign = env.bob.post(
            "/api/projects/%s/report" % project_id,
            json={"format": "briefing"},
        )
        missing = env.bob.post(
            "/api/projects/%s/report" % MISSING_ID,
            json={"format": "briefing"},
        )

        assert foreign.status_code == 404
        assert foreign.json() == missing.json()
        assert service.calls == []

    def test_report_service_receives_only_the_selected_linked_sources(self, env, monkeypatch):
        service = self._install_report_stub(monkeypatch)
        project_id = make_project(env.alice)
        kept = make_document(env.session, env.alice_user, "Kept report source")
        dropped = make_document(env.session, env.alice_user, "Dropped report source")
        for document_id in (kept, dropped):
            assert env.alice.post(
                "/api/projects/%s/documents/%s" % (project_id, document_id)
            ).status_code == 200

        response = env.alice.post(
            "/api/projects/%s/report" % project_id,
            json={"format": "briefing", "document_ids": [kept]},
        )

        assert response.status_code == 200, response.text
        assert service.calls == [(project_id, "briefing", None, [kept])]


class TestTableIsolation:
    """Generated tables only receive sources authorized for their project."""

    def _install_table_stub(self, monkeypatch):
        class StubTableService:
            def __init__(self):
                self.calls = []

            def generate(self, db, project_id, instruction, columns, document_ids):
                self.calls.append((project_id, instruction, columns, document_ids))
                return {
                    "columns": columns or ["Paper"],
                    "rows": [[{
                        "value": "Paper A", "document_id": document_ids[0], "source_id": 1,
                    }]],
                    "sources": [{
                        "id": 1,
                        "document_id": document_ids[0],
                        "title": "Paper A",
                        "excerpt": "Evidence.",
                    }],
                }

        service = StubTableService()
        monkeypatch.setitem(
            production_app.dependency_overrides,
            get_table_service,
            lambda: service,
        )
        return service

    def test_generating_for_someone_elses_project_is_not_found(self, env, monkeypatch):
        service = self._install_table_stub(monkeypatch)
        project_id = make_project(env.alice)

        foreign = env.bob.post(
            "/api/projects/%s/table" % project_id,
            json={"instruction": "Compare the sources"},
        )
        missing = env.bob.post(
            "/api/projects/%s/table" % MISSING_ID,
            json={"instruction": "Compare the sources"},
        )

        assert foreign.status_code == 404
        assert foreign.json() == missing.json()
        assert service.calls == []

    def test_table_service_receives_only_selected_linked_sources(self, env, monkeypatch):
        service = self._install_table_stub(monkeypatch)
        project_id = make_project(env.alice)
        kept = make_document(env.session, env.alice_user, "Kept paper")
        dropped = make_document(env.session, env.alice_user, "Dropped paper")
        for document_id in (kept, dropped):
            assert env.alice.post(
                "/api/projects/%s/documents/%s" % (project_id, document_id)
            ).status_code == 200

        response = env.alice.post(
            "/api/projects/%s/table" % project_id,
            json={
                "instruction": "One row per paper",
                "columns": ["Paper", "Year"],
                "source_ids": [kept],
            },
        )

        assert response.status_code == 200, response.text
        assert service.calls == [(
            project_id, "One row per paper", ["Paper", "Year"], [kept],
        )]


def test_table_route_requires_authentication():
    response = TestClient(production_app).post(
        "/api/projects/%s/table" % MISSING_ID,
        json={"instruction": "Compare the sources"},
    )

    assert response.status_code == 401


SELECTION_ROUTES = [
    "/api/projects/%s/mindmap",
    "/api/projects/%s/video-summary",
    "/api/projects/%s/flashcards",
    "/api/projects/%s/quiz",
    "/api/projects/%s/report",
    "/api/projects/%s/table",
    "/api/export/project/%s/summary",
]


class TestSourceSelectionIsolation:
    """A source selection names document ids, so every one is checked."""

    def _install_summary_stub(self, monkeypatch):
        service = ProjectOverviewService(llm_service=OfflineLLM())
        generated_titles = []

        def generate(documents, _output_language="auto", options=None):
            titles = [document.title for document in documents]
            generated_titles.append(titles)
            return {
                "title": None,
                "overview": "Summary of " + ", ".join(titles),
                "questions": [],
            }

        monkeypatch.setattr(service, "_generate", generate)
        monkeypatch.setitem(
            production_app.dependency_overrides,
            get_project_overview_service,
            lambda: service,
        )
        return generated_titles

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

        if route.endswith("/report"):
            foreign_body = {"format": "briefing", "document_ids": [alice_document]}
            missing_body = {"format": "briefing", "document_ids": [MISSING_ID]}
        elif route.endswith("/table"):
            foreign_body = {
                "instruction": "Compare the sources", "source_ids": [alice_document],
            }
            missing_body = {
                "instruction": "Compare the sources", "source_ids": [MISSING_ID],
            }
        else:
            foreign_body = {"document_ids": [alice_document]}
            missing_body = {"document_ids": [MISSING_ID]}
        foreign = env.bob.post(route % project_id, json=foreign_body)
        missing = env.bob.post(route % project_id, json=missing_body)

        assert foreign.status_code == 404
        assert foreign.json() == missing.json()

    @pytest.mark.parametrize("route", ["/api/query", "/api/query/stream"])
    def test_query_selecting_someone_elses_source_is_not_found(self, env, route):
        alice_document = make_document(env.session, env.alice_user)

        foreign = env.bob.post(route, json={
            "query": "what is in here?", "document_ids": [alice_document]})
        missing = env.bob.post(route, json={
            "query": "what is in here?", "document_ids": [MISSING_ID]})

        assert foreign.status_code == 404
        assert foreign.json() == missing.json()

    @pytest.mark.parametrize(
        "route", SELECTION_ROUTES + ["/api/query", "/api/query/stream"]
    )
    def test_an_empty_selection_is_refused(self, env, route):
        project_id = make_project(env.alice)

        if route.endswith("/report"):
            payload = {"format": "briefing", "document_ids": []}
        elif route.endswith("/table"):
            payload = {"instruction": "Compare the sources", "source_ids": []}
        else:
            payload = {"query": "anything", "document_ids": []}
        response = env.alice.post(
            route % project_id if "%s" in route else route,
            json=payload,
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

    def test_the_report_summarizes_only_the_selection(self, env, monkeypatch):
        project_id, kept = self._own_project_with_two_sources(env)
        generated_titles = self._install_summary_stub(monkeypatch)

        response = env.alice.post(
            "/api/export/project/%s/summary" % project_id,
            json={"document_ids": [kept]},
        )

        assert response.status_code == 200
        assert "Summary of Kept source" in response.text
        assert "Dropped source" not in response.text
        assert generated_titles == [["Kept source"]]

    def test_omitting_the_selection_summarizes_every_source(self, env, monkeypatch):
        project_id, _ = self._own_project_with_two_sources(env)
        generated_titles = self._install_summary_stub(monkeypatch)

        response = env.alice.post("/api/export/project/%s/summary" % project_id)

        assert response.status_code == 200
        assert "Summary of " in response.text
        assert "Dropped source" in response.text
        assert "Kept source" in response.text
        assert set(generated_titles[0]) == {"Dropped source", "Kept source"}


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


class TestProjectAnalyticsIsolation:
    """Analytics are private to the account that owns the project."""

    def test_another_account_cannot_read_project_analytics(self, env):
        project_id = make_project(env.alice)

        assert env.bob.get(
            "/api/projects/%s/analytics" % project_id
        ).status_code == 404
        assert env.alice.get(
            "/api/projects/%s/analytics" % project_id
        ).status_code == 200

    def test_shared_overview_includes_sources_uploaded_by_an_editor(self, env):
        import json

        from app.routers.project_overview import get_project_overview_service
        from app.services.project_overview import ProjectOverviewService

        class RecordingLLM:
            prompts = []

            def generate(self, prompt, **kwargs):
                self.prompts.append(prompt)
                return {
                    "text": json.dumps({
                        "overview": "The shared source covers a unique subject.",
                        "questions": ["What does the source explain?"],
                    }),
                    "model": "test",
                    "usage": {},
                }

        project_id = make_project(env.alice)
        document_id = make_document(
            env.session,
            env.bob_user,
            title="Bob source",
            source_type="txt",
            content="Exclusive member source text",
        )
        grant_project_role(env, project_id, "editor")
        assert env.bob.post(
            "/api/projects/%s/documents/%s" % (project_id, document_id)
        ).status_code == 200
        llm = RecordingLLM()
        service = ProjectOverviewService(llm_service=llm)
        production_app.dependency_overrides[get_project_overview_service] = lambda: service

        response = env.bob.get("/api/projects/%s/overview" % project_id)

        assert response.status_code == 200, response.text
        assert response.json()["overview"] == "The shared source covers a unique subject."
        assert "Exclusive member source text" in llm.prompts[0]


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


def test_global_search_is_limited_to_owned_and_shared_projects(env):
    """Search may include shared sources but cannot reveal private projects."""
    from app.routers.query import get_rag_service

    owned_project_id = make_project(env.alice, "Alice project")
    shared_project_id = make_project(env.bob, "Shared project")
    private_project_id = make_project(env.bob, "Private project")
    owned_document_id = make_document(env.session, env.alice_user, "Owned source")
    shared_document_id = make_document(env.session, env.bob_user, "Shared source")
    private_document_id = make_document(env.session, env.bob_user, "Private source")
    env.session.add_all([
        ProjectDocument(
            project_id=owned_project_id,
            document_id=owned_document_id,
            shared_by_user_id=env.alice_user.id,
        ),
        ProjectDocument(
            project_id=shared_project_id,
            document_id=shared_document_id,
            shared_by_user_id=env.bob_user.id,
        ),
        ProjectDocument(
            project_id=private_project_id,
            document_id=private_document_id,
            shared_by_user_id=env.bob_user.id,
        ),
        ProjectMember(
            project_id=shared_project_id,
            user_id=env.alice_user.id,
            role="viewer",
        ),
    ])
    env.session.commit()

    class FakeRAGService:
        allowed_document_ids = None

        def retrieve_with_diagnostics(self, **kwargs):
            self.allowed_document_ids = kwargs["allowed_document_ids"]
            return ([
                {
                    "chunk_id": "owned-hit",
                    "document_id": owned_document_id,
                    "document_title": "Owned source",
                    "text": "Owned passage",
                    "metadata": {"page_num": 1, "section": "Owned section"},
                    "score": 0.9,
                },
                {
                    "chunk_id": "shared-hit",
                    "document_id": shared_document_id,
                    "document_title": "Shared source",
                    "text": "Shared passage",
                    "metadata": {"page_num": 2, "section": "Shared section"},
                    "score": 0.8,
                },
                {
                    "chunk_id": "private-hit",
                    "document_id": private_document_id,
                    "document_title": "Private source",
                    "text": "Private passage",
                    "metadata": {"page_num": 3, "section": "Private section"},
                    "score": 0.7,
                },
            ], {"latency_ms": 1.0})

    rag_service = FakeRAGService()
    production_app.dependency_overrides[get_rag_service] = lambda: rag_service

    response = env.alice.post("/api/search", json={"query": "important finding"})

    assert response.status_code == 200, response.text
    assert set(rag_service.allowed_document_ids) == {
        owned_document_id,
        shared_document_id,
    }
    projects = {
        project["project_id"]: project
        for project in response.json()["projects"]
    }
    assert set(projects) == {owned_project_id, shared_project_id}
    assert projects[owned_project_id]["documents"][0]["passages"][0]["text"] == (
        "Owned passage"
    )
    assert projects[shared_project_id]["documents"][0]["passages"][0]["text"] == (
        "Shared passage"
    )
    assert "Private passage" not in response.text


def test_personal_api_key_only_reaches_its_owners_data(env):
    """API-key auth uses the same account scope as a JWT."""
    alice_project_id = make_project(env.alice, "Alice key project")
    bob_project_id = make_project(env.bob, "Bob private project")
    created = env.alice.post(
        "/api/auth/api-keys",
        json={"name": "automation"},
    )
    assert created.status_code == 201, created.text
    api_key = created.json()["api_key"]
    key_id = created.json()["id"]

    assert env.bob.get("/api/auth/api-keys").json() == []
    assert env.bob.delete("/api/auth/api-keys/%s" % key_id).status_code == 404

    response = env.alice.get(
        "/api/projects",
        headers={"Authorization": f"Bearer {api_key}"},
    )

    assert response.status_code == 200, response.text
    assert {project["id"] for project in response.json()["projects"]} == {
        alice_project_id,
    }
    assert bob_project_id not in response.text


def test_personal_api_key_shares_the_account_query_rate_limit(env):
    """JWT and API-key requests consume the same per-account query budget."""
    from app.routers.query import get_concurrency_limiter, get_rate_limiter
    from app.services.rate_limit import ConcurrencyLimiter, SlidingWindowRateLimiter

    created = env.alice.post(
        "/api/auth/api-keys",
        json={"name": "rate-limited key"},
    )
    assert created.status_code == 201, created.text
    api_key = created.json()["api_key"]
    limiter = SlidingWindowRateLimiter()
    production_app.dependency_overrides[get_rate_limiter] = lambda: limiter
    production_app.dependency_overrides[get_concurrency_limiter] = (
        lambda: ConcurrencyLimiter(max_concurrent=1)
    )
    production_app.dependency_overrides[get_settings] = (
        lambda: Settings(rate_limit_enabled=True)
    )
    try:
        jwt_responses = [
            env.alice.post("/api/search", json={"query": "hello"})
            for _ in range(15)
        ]
        api_key_responses = [
            env.alice.post(
                "/api/search",
                json={"query": "hello"},
                headers={"Authorization": f"Bearer {api_key}"},
            )
            for _ in range(16)
        ]
    finally:
        production_app.dependency_overrides.pop(get_rate_limiter, None)
        production_app.dependency_overrides.pop(get_concurrency_limiter, None)
        production_app.dependency_overrides.pop(get_settings, None)

    assert all(response.status_code == 200 for response in jwt_responses)
    assert [response.status_code for response in api_key_responses[:15]] == [200] * 15
    assert api_key_responses[-1].status_code == 429


def test_project_tags_are_private_to_each_visible_member(env):
    project_id = make_project(env.alice, "Personal tags in a shared project")
    path = f"/api/projects/{project_id}/tags"

    saved = env.alice.put(path, json={"tags": ["research"]})
    hidden = env.bob.put(path, json={"tags": ["private-to-bob"]})

    assert saved.status_code == 200, saved.text
    assert hidden.status_code == 404

    env.session.add(ProjectMember(
        project_id=project_id,
        user_id=env.bob_user.id,
        role="viewer",
    ))
    env.session.commit()

    bob_saved = env.bob.put(path, json={"tags": ["private-to-bob"]})
    assert bob_saved.status_code == 200, bob_saved.text

    alice_project = next(
        project for project in env.alice.get("/api/projects").json()["projects"]
        if project["id"] == project_id
    )
    bob_project = next(
        project for project in env.bob.get("/api/projects").json()["projects"]
        if project["id"] == project_id
    )
    assert alice_project["tags"] == ["research"]
    assert bob_project["tags"] == ["private-to-bob"]


def test_source_group_routes_hide_other_projects_and_reject_cross_project_sources(env):
    first_project_id = make_project(env.alice, "First grouped project")
    second_project_id = make_project(env.alice, "Second grouped project")
    first_document_id = make_document(env.session, env.alice_user, "First source")
    second_document_id = make_document(env.session, env.alice_user, "Second source")
    env.session.add_all([
        ProjectDocument(project_id=first_project_id, document_id=first_document_id),
        ProjectDocument(project_id=second_project_id, document_id=second_document_id),
    ])
    env.session.commit()

    first_groups = "/api/projects/%s/source-groups" % first_project_id
    second_groups = "/api/projects/%s/source-groups" % second_project_id
    created = env.alice.post(first_groups, json={"name": "References"})
    assert created.status_code == 201, created.text
    group_id = created.json()["id"]

    assert env.bob.get(first_groups).status_code == 404
    assert env.bob.post(first_groups, json={"name": "Private"}).status_code == 404
    assert env.bob.patch(
        "%s/%s" % (first_groups, group_id),
        json={"name": "Private"},
    ).status_code == 404
    assert env.bob.delete("%s/%s" % (first_groups, group_id)).status_code == 404
    assert env.bob.put(
        "/api/projects/%s/documents/%s/group" % (
            first_project_id,
            first_document_id,
        ),
        json={"group_id": group_id},
    ).status_code == 404
    wrong_project = env.alice.put(
        "/api/projects/%s/documents/%s/group" % (
            first_project_id,
            second_document_id,
        ),
        json={"group_id": group_id},
    )
    foreign_group = env.alice.put(
        "/api/projects/%s/documents/%s/group" % (
            second_project_id,
            second_document_id,
        ),
        json={"group_id": group_id},
    )

    assert wrong_project.status_code == 404
    assert foreign_group.status_code == 404
    assert env.alice.patch(
        "%s/%s" % (second_groups, group_id),
        json={"name": "Wrong project"},
    ).status_code == 404
    assert env.alice.delete("%s/%s" % (second_groups, group_id)).status_code == 404

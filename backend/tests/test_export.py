"""Tests for the export API."""
import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import zipfile

import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.background import BackgroundTask

from app.db.database import get_db
from app.db.models import (
    Base,
    Conversation,
    Document,
    Message,
    Project,
    ProjectDocument,
)
from app.routers import export
from app.services import export as export_service_module
from app.services.export import ExportService
from conftest import authenticated_client, owner_id


app = FastAPI()
app.include_router(export.router, prefix="/api")

# Create test database
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    """Override database dependency for testing.

    Args:
        None.

    Returns:
        A database-session generator.
    """
    try:
        db = TestingSessionLocal()
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db

# Create tables
Base.metadata.create_all(bind=engine)

# Create test client. The router refuses anonymous callers, so the client
# presents a bearer token on every request.
with TestingSessionLocal() as setup_session:
    client = authenticated_client(app, setup_session)


@pytest.fixture
def two_projects_with_own_documents():
    """Seed two projects, each owning exactly one document.

    Args:
        None.

    Returns:
        None after yielding the seeded rows to a test.
    """
    with TestingSessionLocal() as db:
        owner = owner_id(db)
        db.add_all([
            Project(id="project-a", user_id=owner, name="Project A"),
            Project(id="project-b", user_id=owner, name="Project B"),
            Document(
                id="document-a",
                user_id=owner,
                title="Only In A",
                source_type="pdf",
                status="ready",
            ),
            Document(
                id="document-b",
                user_id=owner,
                title="Only In B",
                source_type="pdf",
                status="ready",
            ),
        ])
        db.flush()
        db.add_all([
            ProjectDocument(project_id="project-a", document_id="document-a"),
            ProjectDocument(project_id="project-b", document_id="document-b"),
        ])
        db.commit()

    yield

    with TestingSessionLocal() as db:
        db.query(ProjectDocument).delete()
        db.query(Document).delete()
        db.query(Project).delete()
        db.commit()


def test_json_export_only_includes_own_documents(two_projects_with_own_documents):
    """A JSON project export must not leak another project's sources.

    Args:
        two_projects_with_own_documents: Seeded project/document rows.

    Returns:
        None.
    """
    response = client.get("/api/export/project/project-a?format=json")

    assert response.status_code == 200
    document_ids = [doc["id"] for doc in response.json()["documents"]]
    assert document_ids == ["document-a"]


def test_markdown_export_only_includes_own_documents(two_projects_with_own_documents):
    """A Markdown project export must not leak another project's sources.

    Args:
        two_projects_with_own_documents: Seeded project/document rows.

    Returns:
        None.
    """
    response = client.get("/api/export/project/project-a?format=markdown")

    assert response.status_code == 200
    assert "Only In A" in response.text
    assert "Only In B" not in response.text


def test_project_summary_only_includes_own_documents(two_projects_with_own_documents):
    """A project summary report must not leak another project's sources.

    Args:
        two_projects_with_own_documents: Seeded project/document rows.

    Returns:
        None.
    """
    response = client.post("/api/export/project/project-a/summary")

    assert response.status_code == 200
    assert "**Documents**: 1" in response.text
    assert "Only In A" in response.text
    assert "Only In B" not in response.text


def test_get_cannot_generate_a_project_summary(two_projects_with_own_documents):
    """Reading a URL must not run the project generation command."""
    assert client.get("/api/export/project/project-a/summary").status_code == 405


@pytest.fixture
def batch_conversations():
    """Seed two conversations for service-level archive tests.

    Args:
        None.

    Returns:
        The seeded conversation IDs in deterministic order.
    """
    conversation_ids = ["batch-conversation-a", "batch-conversation-b"]
    with TestingSessionLocal() as db:
        owner = owner_id(db)
        db.add(Project(
            id="batch-project",
            user_id=owner,
            name="Batch project",
        ))
        db.add_all([
            Conversation(
                id=conversation_ids[0],
                project_id="batch-project",
                title="First export",
            ),
            Conversation(
                id=conversation_ids[1],
                project_id="batch-project",
                title="Second export",
            ),
        ])
        db.commit()

    yield conversation_ids

    with TestingSessionLocal() as db:
        db.query(Conversation).filter(
            Conversation.id.in_(conversation_ids)
        ).delete(synchronize_session=False)
        db.query(Project).filter(Project.id == "batch-project").delete()
        db.commit()


def test_batch_service_rejects_101_before_query_or_tempfile(monkeypatch):
    """The service limit is enforced before database or filesystem work.

    Args:
        monkeypatch: Pytest patch helper.

    Returns:
        None.
    """
    class QueryForbidden:
        def query(self, *_args, **_kwargs):
            raise AssertionError("database queried before batch limit")

    def tempfile_forbidden(*_args, **_kwargs):
        raise AssertionError("temporary file created before batch limit")

    monkeypatch.setattr(export_service_module.tempfile, "mkstemp", tempfile_forbidden)

    with pytest.raises(ValueError, match="at most 100"):
        ExportService().batch_export_conversations(
            QueryForbidden(),
            ["conversation"] * 101,
        )


def test_batch_service_uses_closed_unique_archive_and_preserves_order(
    batch_conversations,
    monkeypatch,
):
    """The service closes its unique fd and writes every requested item.

    Args:
        batch_conversations: Seeded conversation IDs.
        monkeypatch: Pytest patch helper.

    Returns:
        None.
    """
    events = []
    created_paths = []
    real_mkstemp = export_service_module.tempfile.mkstemp
    real_close = export_service_module.os.close

    def recording_mkstemp(*args, **kwargs):
        fd, path = real_mkstemp(*args, **kwargs)
        events.append(("mkstemp", fd))
        created_paths.append(path)
        return fd, path

    def recording_close(fd):
        events.append(("close", fd))
        return real_close(fd)

    service = ExportService()
    original_export = service.export_conversation

    def recording_export(*args, **kwargs):
        events.append(("export", None))
        return original_export(*args, **kwargs)

    monkeypatch.setattr(export_service_module.tempfile, "mkstemp", recording_mkstemp)
    monkeypatch.setattr(export_service_module.os, "close", recording_close)
    monkeypatch.setattr(service, "export_conversation", recording_export)

    requested_ids = [
        batch_conversations[0],
        batch_conversations[1],
        batch_conversations[0],
    ]
    with TestingSessionLocal() as db:
        archive_path = service.batch_export_conversations(db, requested_ids)

    try:
        assert created_paths == [archive_path]
        assert events[:2] == [
            ("mkstemp", events[0][1]),
            ("close", events[0][1]),
        ]
        with zipfile.ZipFile(archive_path) as archive:
            entries = archive.infolist()
            assert len(entries) == 3
            assert len({entry.filename for entry in entries}) == 3
            exported_ids = [
                json.loads(archive.read(entry))["id"]
                for entry in entries
            ]
        assert exported_ids == requested_ids
    finally:
        Path(archive_path).unlink(missing_ok=True)


def test_batch_service_allocates_a_new_valid_archive_per_call(
    batch_conversations,
):
    """Consecutive exports cannot race by sharing a guessed archive path.

    Args:
        batch_conversations: Seeded conversation IDs.

    Returns:
        None.
    """
    service = ExportService()
    archive_paths = []
    try:
        with TestingSessionLocal() as db:
            archive_paths.append(service.batch_export_conversations(
                db,
                [batch_conversations[0]],
            ))
            archive_paths.append(service.batch_export_conversations(
                db,
                [batch_conversations[0]],
            ))

        assert archive_paths[0] != archive_paths[1]
        assert all(zipfile.is_zipfile(path) for path in archive_paths)
    finally:
        for archive_path in archive_paths:
            Path(archive_path).unlink(missing_ok=True)


def test_batch_service_removes_exact_archive_when_export_raises(
    batch_conversations,
    monkeypatch,
):
    """A service exception unlinks only the archive allocated by this call.

    Args:
        batch_conversations: Seeded conversation IDs.
        monkeypatch: Pytest patch helper.

    Returns:
        None.
    """
    created_paths = []
    sibling_paths = []
    real_mkstemp = export_service_module.tempfile.mkstemp

    def recording_mkstemp(*args, **kwargs):
        fd, path = real_mkstemp(*args, **kwargs)
        created_paths.append(path)
        sibling = Path(path + ".keep")
        sibling.write_text("keep", encoding="utf-8")
        sibling_paths.append(sibling)
        return fd, path

    def fail_export(*_args, **_kwargs):
        raise RuntimeError("archive member failed")

    service = ExportService()
    monkeypatch.setattr(export_service_module.tempfile, "mkstemp", recording_mkstemp)
    monkeypatch.setattr(service, "export_conversation", fail_export)

    with TestingSessionLocal() as db:
        with pytest.raises(RuntimeError, match="archive member failed"):
            service.batch_export_conversations(db, [batch_conversations[0]])

    try:
        assert len(created_paths) == 1
        assert not Path(created_paths[0]).exists()
        assert sibling_paths[0].exists()
    finally:
        for sibling in sibling_paths:
            sibling.unlink(missing_ok=True)


def test_batch_route_rejects_101_before_ownership_or_archive(
    tmp_path,
    monkeypatch,
):
    """The HTTP limit rejects oversized input before scoped row lookup.

    Args:
        tmp_path: Per-test temporary directory.
        monkeypatch: Pytest patch helper.

    Returns:
        None.
    """
    calls = []
    unused_archive = tmp_path / "unused.zip"
    unused_archive.write_bytes(b"unused")

    def record_ownership(*_args, **_kwargs):
        calls.append("ownership")

    def record_archive(*_args, **_kwargs):
        calls.append("archive")
        return str(unused_archive)

    monkeypatch.setattr(export, "require_conversation", record_ownership)
    monkeypatch.setattr(
        export.export_service,
        "batch_export_conversations",
        record_archive,
    )

    response = client.post(
        "/api/export/batch?format=json",
        json=["conversation"] * 101,
    )

    assert response.status_code == 400
    assert "at most 100" in response.json()["detail"]
    assert calls == []


def test_batch_route_allows_100_and_cleans_exact_archive(tmp_path, monkeypatch):
    """A maximum-sized response is sent and its exact file is removed.

    Args:
        tmp_path: Per-test temporary directory.
        monkeypatch: Pytest patch helper.

    Returns:
        None.
    """
    archive_path = tmp_path / "batch.zip"
    sibling_path = tmp_path / "batch.zip.keep"
    archive_path.write_bytes(b"archive-content")
    sibling_path.write_text("keep", encoding="utf-8")
    checked_ids = []
    service_ids = []

    def record_ownership(_db, conversation_id, _current_user):
        checked_ids.append(conversation_id)

    def return_archive(*, db, conversation_ids, format):
        service_ids.extend(conversation_ids)
        return str(archive_path)

    monkeypatch.setattr(export, "require_conversation", record_ownership)
    monkeypatch.setattr(
        export.export_service,
        "batch_export_conversations",
        return_archive,
    )
    requested_ids = ["same-conversation"] * 100

    response = client.post(
        "/api/export/batch?format=json",
        json=requested_ids,
    )

    assert response.status_code == 200
    assert response.content == b"archive-content"
    assert checked_ids == requested_ids
    assert service_ids == requested_ids
    assert not archive_path.exists()
    assert sibling_path.exists()


def test_batch_range_416_still_cleans_exact_archive(tmp_path, monkeypatch):
    """An unsatisfiable range cannot bypass archive cleanup.

    Args:
        tmp_path: Per-test temporary directory.
        monkeypatch: Pytest patch helper.

    Returns:
        None.
    """
    archive_path = tmp_path / "range.zip"
    sibling_path = tmp_path / "range.zip.keep"
    archive_path.write_bytes(b"tiny")
    sibling_path.write_text("keep", encoding="utf-8")

    monkeypatch.setattr(export, "require_conversation", lambda *_args: None)
    monkeypatch.setattr(
        export.export_service,
        "batch_export_conversations",
        lambda **_kwargs: str(archive_path),
    )

    response = client.post(
        "/api/export/batch?format=json",
        json=["conversation"],
        headers={"Range": "bytes=999-1000"},
    )

    assert response.status_code == 416
    assert not archive_path.exists()
    assert sibling_path.exists()


def test_cleanup_response_removes_exact_archive_when_send_raises(tmp_path):
    """A client/send failure cannot strand the generated archive.

    Args:
        tmp_path: Per-test temporary directory.

    Returns:
        None.
    """
    archive_path = tmp_path / "send.zip"
    sibling_path = tmp_path / "send.zip.keep"
    archive_path.write_bytes(b"archive")
    sibling_path.write_text("keep", encoding="utf-8")

    async def exercise_response():
        response = export.CleanupFileResponse(str(archive_path))

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def fail_send(_message):
            raise RuntimeError("client disconnected")

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/api/export/batch",
            "query_string": b"",
            "headers": [],
            "http_version": "1.1",
            "scheme": "http",
            "server": ("testserver", 80),
            "client": ("testclient", 50000),
        }
        with pytest.raises(RuntimeError, match="client disconnected"):
            await response(scope, receive, fail_send)

    asyncio.run(exercise_response())

    assert not archive_path.exists()
    assert sibling_path.exists()


def test_batch_route_attaches_background_cleanup(tmp_path, monkeypatch):
    """The normal response path retains Starlette background cleanup.

    Args:
        tmp_path: Per-test temporary directory.
        monkeypatch: Pytest patch helper.

    Returns:
        None.
    """
    archive_path = tmp_path / "background.zip"
    archive_path.write_bytes(b"archive")
    monkeypatch.setattr(export, "require_conversation", lambda *_args: None)
    monkeypatch.setattr(
        export.export_service,
        "batch_export_conversations",
        lambda **_kwargs: str(archive_path),
    )

    response = asyncio.run(export.batch_export(
        conversation_ids=["conversation"],
        format="json",
        db=object(),
        current_user=object(),
    ))

    assert isinstance(response.background, BackgroundTask)
    asyncio.run(response.background())
    assert not archive_path.exists()


def test_json_conversation_export_orders_persisted_messages_by_time_and_legacy_id():
    """Conversation export must give legacy timestamp ties a stable order."""
    conversation_id = "export-ordered-conversation"
    tied_timestamp = datetime(2026, 8, 24, 8, 0, tzinfo=timezone.utc)
    with TestingSessionLocal() as db:
        owner = owner_id(db)
        db.add_all([
            Project(
                id="export-ordered-project",
                user_id=owner,
                name="Ordered export project",
            ),
            Conversation(
                id=conversation_id,
                project_id="export-ordered-project",
                title="Ordered export",
            ),
            # Insert in the opposite of the required order, including a legacy tie.
            Message(
                id="export-later-message",
                conversation_id=conversation_id,
                role="assistant",
                text="Later",
                created_at=tied_timestamp + timedelta(seconds=1),
            ),
            Message(
                id="export-legacy-z-message",
                conversation_id=conversation_id,
                role="assistant",
                text="Legacy Z",
                created_at=tied_timestamp,
            ),
            Message(
                id="export-earlier-message",
                conversation_id=conversation_id,
                role="user",
                text="Earlier",
                created_at=tied_timestamp - timedelta(seconds=1),
            ),
            Message(
                id="export-legacy-a-message",
                conversation_id=conversation_id,
                role="user",
                text="Legacy A",
                created_at=tied_timestamp,
            ),
        ])
        db.commit()

    try:
        response = client.get(f"/api/export/conversation/{conversation_id}?format=json")

        assert response.status_code == 200
        assert [message["id"] for message in json.loads(response.text)["messages"]] == [
            "export-earlier-message",
            "export-legacy-a-message",
            "export-legacy-z-message",
            "export-later-message",
        ]
    finally:
        with TestingSessionLocal() as db:
            db.query(Message).filter(Message.conversation_id == conversation_id).delete()
            db.query(Conversation).filter(Conversation.id == conversation_id).delete()
            db.query(Project).filter(Project.id == "export-ordered-project").delete()
            db.commit()

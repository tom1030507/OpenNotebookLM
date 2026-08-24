"""Tests for the export API."""
import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import get_db
from app.db.models import Base, Conversation, Document, Message, Project, ProjectDocument
from app.routers import export
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
    """Override database dependency for testing."""
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
    """Seed two projects, each owning exactly one document."""
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
    """A JSON project export must not leak another project's sources."""
    response = client.get("/api/export/project/project-a?format=json")

    assert response.status_code == 200
    document_ids = [doc["id"] for doc in response.json()["documents"]]
    assert document_ids == ["document-a"]


def test_markdown_export_only_includes_own_documents(two_projects_with_own_documents):
    """A Markdown project export must not leak another project's sources."""
    response = client.get("/api/export/project/project-a?format=markdown")

    assert response.status_code == 200
    assert "Only In A" in response.text
    assert "Only In B" not in response.text


def test_project_summary_only_includes_own_documents(two_projects_with_own_documents):
    """A project summary report must not leak another project's sources."""
    response = client.get("/api/export/project/project-a/summary")

    assert response.status_code == 200
    assert "**Documents**: 1" in response.text
    assert "Only In A" in response.text
    assert "Only In B" not in response.text


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

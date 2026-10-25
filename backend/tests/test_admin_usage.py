"""Contracts for the server-wide usage endpoint."""
from types import SimpleNamespace

import pytest
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import get_db
from app.db.models import (
    AudioOverview,
    Base,
    Conversation,
    Document,
    Message,
    Project,
    StudioGeneration,
    User,
)
from app.main import app
from app.routers.auth import get_current_user
from app.services.admin_usage import (
    get_admin_usage,
    record_llm_usage,
    sync_admin_users,
    track_studio_generation,
)
from app.services.project_analytics import get_project_analytics


@pytest.fixture
def admin_client():
    """Build the production routes over an isolated database."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False)

    def override_get_db():
        with session_factory() as db:
            yield db

    admin = SimpleNamespace(id="admin-1", username="admin", is_admin=True)
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: admin
    with session_factory() as db:
        db.add(User(
            id=admin.id,
            username=admin.username,
            email="admin@example.com",
            hashed_password="unused",
        ))
        db.commit()

    try:
        yield TestClient(app), session_factory
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_admin_can_read_server_wide_usage(admin_client):
    """The admin usage route is mounted and returns totals plus user rows."""
    client, _ = admin_client

    response = client.get("/api/admin/usage?days=7")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["days"] == 7
    assert body["totals"]["queries"] == 0
    assert body["users"][0]["user_id"] == "admin-1"


def test_non_admin_gets_not_found(admin_client):
    """The route hides even its existence from signed-in non-admins."""
    client, _ = admin_client
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id="ordinary-user", username="ordinary", is_admin=False,
    )

    response = client.get("/api/admin/usage?days=7")

    assert response.status_code == 404
    assert response.json() == {"detail": "Not found"}


def test_admin_totals_match_project_questions_and_include_user_metrics(admin_client):
    """Counts include message usage, successful Studio outputs, and unique storage."""
    client, session_factory = admin_client
    now = datetime.now(timezone.utc)
    recent = now - timedelta(days=1)
    with session_factory() as db:
        admin = db.get(User, "admin-1")
        member = User(
            id="member-1",
            username="member",
            email="member@example.com",
            hashed_password="unused",
        )
        project_a = Project(id="project-a", user_id=admin.id, name="A")
        project_b = Project(id="project-b", user_id=member.id, name="B")
        db.add_all([member, project_a, project_b])
        db.flush()
        conversation_a = Conversation(
            id="conversation-a", project_id=project_a.id, user_id=admin.id,
        )
        conversation_b = Conversation(
            id="conversation-b", project_id=project_b.id, user_id=admin.id,
        )
        db.add_all([conversation_a, conversation_b])
        db.add_all([
            Message(
                id="question-a", conversation_id=conversation_a.id,
                role="user", text="Question A", created_at=recent,
            ),
            Message(
                id="answer-a", conversation_id=conversation_a.id,
                role="assistant", text="Answer A", token_count=100,
                cost=None, created_at=recent + timedelta(seconds=1),
            ),
            Message(
                id="question-b", conversation_id=conversation_b.id,
                role="user", text="Question B", created_at=recent,
            ),
            Message(
                id="answer-b", conversation_id=conversation_b.id,
                role="assistant", text="Answer B", token_count=300,
                cost=0.001, created_at=recent + timedelta(seconds=1),
            ),
            Message(
                id="old-question", conversation_id=conversation_a.id,
                role="user", text="Old question", created_at=now - timedelta(days=8),
            ),
            Message(
                id="old-answer", conversation_id=conversation_a.id,
                role="assistant", text="Old answer", token_count=900,
                created_at=now - timedelta(days=8),
            ),
        ])
        db.add_all([
            StudioGeneration(
                id="studio-1", user_id=admin.id, token_count=50,
                created_at=recent,
            ),
            StudioGeneration(
                id="studio-old", user_id=admin.id, token_count=900,
                created_at=now - timedelta(days=8),
            ),
            AudioOverview(
                id="audio-1", project_id=project_b.id, user_id=member.id,
                token_count=20, status="ready", created_at=recent,
            ),
            AudioOverview(
                id="audio-queued", project_id=project_b.id, user_id=member.id,
                status="queued", created_at=recent,
            ),
            AudioOverview(
                id="audio-failed-after-script", project_id=project_b.id,
                user_id=member.id, token_count=10, status="failed", created_at=recent,
            ),
            Document(
                id="document-a", user_id=admin.id, title="A", source_type="pdf",
                meta_json={"file_size": 512},
            ),
            Document(
                id="document-b", user_id=member.id, title="B", source_type="pdf",
                meta_json={"file_size": 1024},
            ),
            Document(
                id="document-text", user_id=member.id, title="Text", source_type="text",
                meta_json={"text_size": 128},
            ),
            Document(
                id="document-legacy", user_id=admin.id, title="Legacy text",
                source_type="url", content="你", meta_json={},
            ),
        ])
        db.commit()
        project_question_total = sum(
            sum(day["question_count"] for day in get_project_analytics(
                db, project.id, project.user_id, 7,
            )["questions_by_day"])
            for project in (project_a, project_b)
        )

    response = client.get("/api/admin/usage?days=7")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["totals"] == {
        "users": 2,
        "queries": 2,
        "studio_generations": 2,
        "tokens": 480,
        "estimated_cost_usd": 0.00136,
        "storage_bytes": 1667,
    }
    assert body["totals"]["queries"] == project_question_total
    admin_row, member_row = body["users"]
    assert admin_row["user_id"] == "admin-1"
    assert admin_row["queries"] == 2
    assert admin_row["studio_generations"] == 1
    assert admin_row["tokens"] == 450
    assert admin_row["storage_bytes"] == 515
    assert member_row["user_id"] == "member-1"
    assert member_row["studio_generations"] == 1
    assert member_row["tokens"] == 30
    assert member_row["storage_bytes"] == 1152
    assert sum(row["queries"] for row in body["users"]) == body["totals"]["queries"]
    assert sum(row["tokens"] for row in body["users"]) == body["totals"]["tokens"]
    assert sum(row["storage_bytes"] for row in body["users"]) == body["totals"]["storage_bytes"]
    assert max(item["user_count"] for item in body["active_users_by_day"]) == 2
    assert body["active_users_by_week"][-1]["user_count"] == 2


def test_successful_studio_calls_capture_provider_tokens(admin_client):
    """A generated result records all LLM calls made inside its route scope."""
    _, session_factory = admin_client
    with session_factory() as db:
        with track_studio_generation(db, "admin-1"):
            record_llm_usage({"total_tokens": 23})
            record_llm_usage({"total_tokens": 7})
        row = db.query(StudioGeneration).one()

        assert row.user_id == "admin-1"
        assert row.token_count == 30


def test_admin_allowlist_sync_grants_and_revokes_roles(admin_client):
    """Configured emails are case-insensitive and removed emails lose access."""
    _, session_factory = admin_client
    with session_factory() as db:
        admin = db.get(User, "admin-1")
        member = User(
            id="member-1", username="member", email="member@example.com",
            hashed_password="unused",
        )
        db.add(member)
        db.commit()

        sync_admin_users(db, [" ADMIN@example.com "])
        assert admin.is_admin is True
        assert member.is_admin is False

        sync_admin_users(db, [])
        assert admin.is_admin is False

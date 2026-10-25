"""Project usage analytics response and privacy contracts."""
from datetime import datetime, time, timedelta, timezone
from time import perf_counter
import uuid

import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import get_db
from app.db.models import (
    Base,
    Conversation,
    Document,
    Message,
    ProjectDocument,
    ProjectMember,
    User,
)
from app.routers import projects
from app.utils.time import utc_now
from conftest import authenticated_client, owner_id, seed_user


@pytest.fixture
def env():
    """Build an authenticated project API over an isolated SQLite database.

    Yields:
        A client, database session factory, and project id.
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override_get_db():
        with session_factory() as db:
            yield db

    app = FastAPI()
    app.include_router(projects.router, prefix="/api")
    app.dependency_overrides[get_db] = override_get_db
    with session_factory() as db:
        client = authenticated_client(app, db)
    project_id = client.post("/api/projects", json={"name": "Analytics"}).json()["id"]

    yield client, session_factory, project_id
    engine.dispose()


def at_day_offset(days_ago: int, hour: int = 12) -> datetime:
    """Return a UTC timestamp on a calendar day relative to today.

    Args:
        days_ago: Number of UTC calendar days before today.
        hour: UTC hour for the timestamp.

    Returns:
        An aware UTC timestamp.
    """
    target_day = utc_now().date() - timedelta(days=days_ago)
    return datetime.combine(target_day, time(hour=hour), tzinfo=timezone.utc)


def add_document(session_factory, project_id: str, title: str, linked: bool = True) -> str:
    """Create a project source, optionally leaving it unlinked.

    Args:
        session_factory: Test database session factory.
        project_id: Project receiving the source.
        title: Current source title.
        linked: Whether this source belongs to the project.

    Returns:
        The new document id.
    """
    document_id = str(uuid.uuid4())
    with session_factory() as db:
        db.add(Document(
            id=document_id,
            user_id=owner_id(db),
            title=title,
            source_type="text",
            status="ready",
        ))
        if linked:
            db.add(ProjectDocument(project_id=project_id, document_id=document_id))
        db.commit()
    return document_id


def add_conversation(session_factory, project_id: str, user_id: str | None = None) -> str:
    """Insert a conversation with the given creator.

    Args:
        session_factory: Test database session factory.
        project_id: Parent project id.
        user_id: Conversation creator; None models a legacy owner conversation.

    Returns:
        The new conversation id.
    """
    conversation_id = str(uuid.uuid4())
    with session_factory() as db:
        db.add(Conversation(
            id=conversation_id,
            project_id=project_id,
            user_id=user_id,
            title="Question thread",
        ))
        db.commit()
    return conversation_id


def add_message(
    session_factory,
    conversation_id: str,
    role: str,
    text: str,
    days_ago: int,
    *,
    rating: str | None = None,
    citations: list | None = None,
    hour: int = 12,
    minute: int = 0,
) -> None:
    """Insert one timestamped message.

    Args:
        session_factory: Test database session factory.
        conversation_id: Conversation containing the message.
        role: Message role.
        text: Message body.
        days_ago: UTC calendar days before today.
        rating: Optional answer rating.
        citations: Optional stored citation objects.
        hour: UTC hour for the timestamp.
        minute: Minute offset to order messages on the same day.
    """
    with session_factory() as db:
        db.add(Message(
            id=str(uuid.uuid4()),
            conversation_id=conversation_id,
            role=role,
            text=text,
            rating=rating,
            citations_json=citations or [],
            created_at=at_day_offset(days_ago, hour) + timedelta(minutes=minute),
        ))
        db.commit()


def test_analytics_aggregates_shared_activity_but_hides_member_questions(env):
    client, session_factory, project_id = env
    cited_document = add_document(session_factory, project_id, "Current source title")
    uncited_document = add_document(session_factory, project_id, "Never cited")
    detached_document = add_document(
        session_factory, project_id, "Removed source", linked=False
    )
    with session_factory() as db:
        owner = db.get(User, owner_id(db))
        member = seed_user(db, "shared-member")
        db.add(ProjectMember(
            project_id=project_id,
            user_id=member.id,
            role="viewer",
        ))
        db.commit()
        owner_id_value = owner.id
        member_id = member.id

    owner_conversation = add_conversation(session_factory, project_id, owner_id_value)
    member_conversation = add_conversation(session_factory, project_id, member_id)
    citations = [
        {
            "document_id": cited_document,
            "document_title": "Old source title",
            "chunk_id": "chunk-1",
            "text_preview": "passage",
        },
        {
            "document_id": cited_document,
            "document_title": "Old source title",
            "chunk_id": "chunk-2",
            "text_preview": "another passage",
        },
    ]
    add_message(session_factory, owner_conversation, "user", "Owner question", 2)
    add_message(
        session_factory, owner_conversation, "assistant", "Owner answer", 2,
        rating="down", citations=citations, minute=1,
    )
    add_message(session_factory, owner_conversation, "assistant", "Unrated answer", 1)
    add_message(session_factory, member_conversation, "user", "PRIVATE member question", 1)
    add_message(
        session_factory, member_conversation, "assistant", "Member answer", 1,
        rating="up",
        citations=[{
            "document_id": cited_document,
            "document_title": "Stale citation title",
            "chunk_id": "chunk-3",
            "text_preview": "member passage",
        }, {
            "document_id": detached_document,
            "document_title": "Removed source",
            "chunk_id": "chunk-4",
            "text_preview": "stale passage",
        }],
    )

    response = client.get("/api/projects/%s/analytics?days=7" % project_id)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["days"] == 7
    assert len(body["questions_by_day"]) == 7
    assert sum(day["question_count"] for day in body["questions_by_day"]) == 2
    assert body["conversation_count"] == 2
    assert body["top_cited_sources"] == [{
        "document_id": cited_document,
        "title": "Current source title",
        "citation_count": 3,
    }]
    assert body["ratings"] == {"up": 1, "down": 1, "unrated": 1}
    assert body["recent_down_rated_questions"] == [{
        "question": "Owner question",
        "answered_at": (at_day_offset(2) + timedelta(minutes=1)).isoformat()
        .replace("+00:00", "Z"),
    }]
    assert body["uncited_sources"] == [{
        "document_id": uncited_document,
        "title": "Never cited",
    }]
    assert "PRIVATE member question" not in response.text
    assert "Old source title" not in response.text
    assert "Removed source" not in response.text


@pytest.mark.parametrize("days", [7, 30, 90])
def test_analytics_zero_fills_utc_days_and_excludes_out_of_window_messages(env, days):
    client, session_factory, project_id = env
    conversation_id = add_conversation(session_factory, project_id)
    add_message(
        session_factory, conversation_id, "user", "Included", days - 1, hour=23
    )
    add_message(session_factory, conversation_id, "user", "Outside", days)

    response = client.get(
        "/api/projects/%s/analytics?days=%s" % (project_id, days)
    )

    assert response.status_code == 200, response.text
    day_rows = response.json()["questions_by_day"]
    expected_dates = [
        (utc_now().date() - timedelta(days=offset)).isoformat()
        for offset in range(days - 1, -1, -1)
    ]
    assert [day["date"] for day in day_rows] == expected_dates
    assert [day["question_count"] for day in day_rows] == [
        1, *([0] * (len(day_rows) - 1))
    ]
    assert response.json()["conversation_count"] == 1


def test_recent_down_rating_finds_and_truncates_the_previous_owner_question(env):
    client, session_factory, project_id = env
    conversation_id = add_conversation(session_factory, project_id)
    long_question = "Q" * 400
    add_message(session_factory, conversation_id, "user", long_question, 8)
    add_message(session_factory, conversation_id, "system", "interstitial", 6)
    add_message(
        session_factory, conversation_id, "assistant", "Bad answer", 5,
        rating="down",
    )

    response = client.get("/api/projects/%s/analytics?days=7" % project_id)

    assert response.status_code == 200, response.text
    item = response.json()["recent_down_rated_questions"][0]
    assert len(item["question"]) <= 280
    assert item["question"].endswith("…")


def test_analytics_rejects_unsupported_day_ranges(env):
    client, _, project_id = env

    response = client.get("/api/projects/%s/analytics?days=14" % project_id)

    assert response.status_code == 422


def test_analytics_stays_responsive_with_ten_thousand_messages(env):
    client, session_factory, project_id = env
    conversations = []
    messages = []
    base_time = at_day_offset(1)
    for conversation_index in range(100):
        conversation_id = "perf-conversation-%03d" % conversation_index
        conversations.append({
            "id": conversation_id,
            "project_id": project_id,
            "user_id": None,
            "title": "Load test",
        })
        for message_index in range(100):
            role = "user" if message_index % 2 == 0 else "assistant"
            messages.append({
                "id": "perf-message-%03d-%03d" % (conversation_index, message_index),
                "conversation_id": conversation_id,
                "role": role,
                "text": "Question %s" % message_index,
                "rating": "down" if role == "assistant" and message_index % 10 == 1 else None,
                "citations_json": [],
                "created_at": base_time + timedelta(minutes=message_index),
            })
    with session_factory() as db:
        db.bulk_insert_mappings(Conversation, conversations)
        db.bulk_insert_mappings(Message, messages)
        db.commit()

    started = perf_counter()
    response = client.get("/api/projects/%s/analytics?days=7" % project_id)
    elapsed = perf_counter() - started

    assert response.status_code == 200, response.text
    assert response.json()["conversation_count"] == 100
    assert sum(day["question_count"] for day in response.json()["questions_by_day"]) == 5000
    assert len(response.json()["recent_down_rated_questions"]) == 10
    assert elapsed < 5, "10,000-message analytics query took %.2fs" % elapsed

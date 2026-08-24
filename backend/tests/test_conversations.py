"""Conversation API contract tests."""
from __future__ import annotations

import inspect
import sys
from datetime import datetime, timedelta, timezone
from types import ModuleType

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import get_db
from app.db.models import Base, Message


# Conversation route tests do not exercise retrieval or model inference. Replace
# that external, heavyweight boundary before importing the router so the tests
# can run in the minimal API environment.
rag_module = ModuleType("app.services.rag")


class StubRAGService:
    """Stand-in for the unused RAG dependency during route contract tests."""


rag_module.RAGService = StubRAGService
sys.modules["app.services.rag"] = rag_module

from app.routers import projects, query  # noqa: E402
from conftest import authorize  # noqa: E402


@pytest.fixture()
def client():
    """Create an API client backed by a fresh in-memory database."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=engine,
    )
    Base.metadata.create_all(bind=engine)

    app = FastAPI()
    app.include_router(projects.router, prefix="/api")
    app.include_router(query.router, prefix="/api")

    def override_get_db():
        db = testing_session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    # The routers refuse anonymous callers, so the client holds a token.
    with testing_session() as setup_session:
        headers = authorize(app, setup_session)

    with TestClient(app, headers=headers) as test_client:
        yield test_client, testing_session

    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def create_project(client: TestClient, name: str = "Research") -> dict:
    """Create a real project through the API for a test scenario."""
    response = client.post("/api/projects", json={"name": name})
    assert response.status_code == 200
    return response.json()


def test_create_conversation_for_project(client):
    """Catch a missing route or a response without project ownership."""
    test_client, _ = client
    project = create_project(test_client)

    response = test_client.post(
        f"/api/projects/{project['id']}/conversations",
        json={"title": "First chat"},
    )

    assert response.status_code == 200
    assert response.json()["project_id"] == project["id"]
    assert response.json()["title"] == "First chat"
    assert response.json()["message_count"] == 0


def test_create_conversation_rejects_missing_project(client):
    """Catch conversation records being created for a nonexistent project."""
    test_client, _ = client

    response = test_client.post(
        "/api/projects/missing/conversations",
        json={"title": "First chat"},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Project not found"}


def test_conversation_list_has_one_route_and_one_response_shape(client):
    """Catch duplicate route registration or an omitted project_id field."""
    test_client, _ = client
    project = create_project(test_client)
    created = test_client.post(
        f"/api/projects/{project['id']}/conversations",
        json={"title": "First chat"},
    ).json()

    matching_routes = [
        route
        for route in [*projects.router.routes, *query.router.routes]
        if getattr(route, "path", None) == "/projects/{project_id}/conversations"
        and "GET" in getattr(route, "methods", set())
    ]
    response = test_client.get(f"/api/projects/{project['id']}/conversations")

    assert len(matching_routes) == 1
    assert response.status_code == 200
    assert response.json() == [
        {
            "id": created["id"],
            "project_id": project["id"],
            "title": "First chat",
            "created_at": created["created_at"],
            "updated_at": created["updated_at"],
            "message_count": 0,
        }
    ]


def test_conversation_details_include_message_text_and_citations(client):
    """Catch message fields drifting from the frontend API contract."""
    test_client, testing_session = client
    project = create_project(test_client)
    conversation = test_client.post(
        f"/api/projects/{project['id']}/conversations",
        json={"title": "First chat"},
    ).json()

    with testing_session() as db:
        db.add(
            Message(
                id="message-1",
                conversation_id=conversation["id"],
                role="assistant",
                text="Answer",
                citations_json=[{
                    "document_id": "document-1",
                    "document_title": "Research paper",
                    "page_num": 4,
                    "text_preview": "Evidence",
                }],
            )
        )
        db.commit()

    response = test_client.get(f"/api/conversations/{conversation['id']}")

    assert response.status_code == 200
    assert response.json()["messages"] == [
        {
            "id": "message-1",
            "role": "assistant",
            "text": "Answer",
            "created_at": response.json()["messages"][0]["created_at"],
            "citations": [{
                "document_id": "document-1",
                "document_title": "Research paper",
                "page_num": 4,
                "text_preview": "Evidence",
            }],
        }
    ]


def test_conversation_details_orders_persisted_messages_by_time_and_legacy_id(client):
    """Details API must give legacy timestamp ties a deterministic message order."""
    test_client, testing_session = client
    project = create_project(test_client)
    conversation = test_client.post(
        f"/api/projects/{project['id']}/conversations",
        json={"title": "Ordered chat"},
    ).json()
    tied_timestamp = datetime(2026, 8, 24, 8, 0, tzinfo=timezone.utc)

    # Insert in the opposite of the required order, including an old tied pair.
    with testing_session() as db:
        db.add_all([
            Message(
                id="later-message",
                conversation_id=conversation["id"],
                role="assistant",
                text="Later",
                created_at=tied_timestamp + timedelta(seconds=1),
            ),
            Message(
                id="legacy-z-message",
                conversation_id=conversation["id"],
                role="assistant",
                text="Legacy Z",
                created_at=tied_timestamp,
            ),
            Message(
                id="earlier-message",
                conversation_id=conversation["id"],
                role="user",
                text="Earlier",
                created_at=tied_timestamp - timedelta(seconds=1),
            ),
            Message(
                id="legacy-a-message",
                conversation_id=conversation["id"],
                role="user",
                text="Legacy A",
                created_at=tied_timestamp,
            ),
        ])
        db.commit()

    response = test_client.get(f"/api/conversations/{conversation['id']}")

    assert response.status_code == 200
    assert [message["id"] for message in response.json()["messages"]] == [
        "earlier-message",
        "legacy-a-message",
        "legacy-z-message",
        "later-message",
    ]


def test_update_conversation_changes_the_persisted_title(client):
    """Catch the edit action closing without persisting its new title."""
    test_client, _ = client
    project = create_project(test_client)
    conversation = test_client.post(
        f"/api/projects/{project['id']}/conversations",
        json={"title": "First chat"},
    ).json()

    response = test_client.put(
        f"/api/conversations/{conversation['id']}",
        json={"title": "Renamed chat"},
    )

    assert response.status_code == 200
    assert response.json()["id"] == conversation["id"]
    assert response.json()["project_id"] == project["id"]
    assert response.json()["title"] == "Renamed chat"

    details = test_client.get(f"/api/conversations/{conversation['id']}")
    assert details.json()["title"] == "Renamed chat"


def test_update_conversation_rejects_missing_conversation(client):
    """Catch rename requests silently succeeding for a missing record."""
    test_client, _ = client

    response = test_client.put(
        "/api/conversations/missing",
        json={"title": "Renamed chat"},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Conversation not found"}


def test_update_conversation_rejects_a_whitespace_only_title(client):
    """Keep direct API clients from persisting an empty display title."""
    test_client, _ = client
    project = create_project(test_client)
    conversation = test_client.post(
        f"/api/projects/{project['id']}/conversations",
        json={"title": "First chat"},
    ).json()

    response = test_client.put(
        f"/api/conversations/{conversation['id']}",
        json={"title": "   "},
    )

    assert response.status_code == 422


def test_query_preserves_project_not_found_status(client):
    """Catch a known 404 being converted into an unrelated 500 response."""
    test_client, _ = client

    response = test_client.post(
        "/api/query",
        json={"project_id": "missing", "query": "Question"},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Project not found"}


def test_query_rejects_a_conversation_from_another_project(client):
    """Prevent one project's sources from being written into another's chat."""
    test_client, _ = client
    first_project = create_project(test_client, "First")
    second_project = create_project(test_client, "Second")
    conversation = test_client.post(
        f"/api/projects/{first_project['id']}/conversations",
        json={"title": "First chat"},
    ).json()

    response = test_client.post(
        "/api/query",
        json={
            "project_id": second_project["id"],
            "conversation_id": conversation["id"],
            "query": "Question",
        },
    )

    assert response.status_code == 400
    assert response.json() == {
        "detail": "Conversation does not belong to the selected project",
    }


def test_no_route_in_this_router_is_a_coroutine():
    """These routes await nothing, so none of them may claim to.

    `/query` embeds the question and then blocks on the LLM; on the event loop
    that stalls every other request for the whole call, and the container runs a
    single uvicorn worker. The conversation routes are cheap by comparison, but
    they hold the same rule so that the next route added here does not have to
    relitigate it.
    """
    routes = (
        query.query,
        query.create_conversation,
        query.get_conversation,
        query.update_conversation,
        query.list_project_conversations,
        query.delete_conversation,
    )

    assert [
        route.__name__ for route in routes
        if inspect.iscoroutinefunction(route)
    ] == []

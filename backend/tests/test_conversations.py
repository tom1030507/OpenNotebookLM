"""Conversation API contract tests."""
from __future__ import annotations

import sys
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

    with TestClient(app) as test_client:
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
                citations_json=[{"doc_id": "document-1"}],
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
            "citations": [{"doc_id": "document-1"}],
        }
    ]

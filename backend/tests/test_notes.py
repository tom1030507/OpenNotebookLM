"""Notes API: manual notes, saved answers, and their lifecycle."""
from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import get_db
from app.db.models import Base, Conversation, Message, Note
from app.routers import notes, projects
from conftest import authorize


@pytest.fixture()
def client():
    """Create an API client backed by a fresh in-memory database.

    Yields:
        The client and the session factory behind it.
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    app = FastAPI()
    app.include_router(projects.router, prefix="/api")
    app.include_router(notes.router, prefix="/api")

    def override_get_db():
        db = testing_session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with testing_session() as setup_session:
        headers = authorize(app, setup_session)

    with TestClient(app, headers=headers) as test_client:
        yield test_client, testing_session

    engine.dispose()


def create_project(client: TestClient, name: str = "Research") -> str:
    """Create a project through the API and return its id."""
    response = client.post("/api/projects", json={"name": name})
    assert response.status_code == 200
    return response.json()["id"]


def add_message(session_factory, project_id: str, role: str = "assistant",
                text: str = "Water boils at 100 C [1].", citations=None) -> str:
    """Insert a conversation message directly and return its id."""
    with session_factory() as db:
        conversation = Conversation(id=str(uuid.uuid4()), project_id=project_id, title="Chat")
        message = Message(
            id=str(uuid.uuid4()),
            conversation_id=conversation.id,
            role=role,
            text=text,
            citations_json=citations or [],
        )
        db.add_all([conversation, message])
        db.commit()
        return message.id


CITATIONS = [{
    "id": 1,
    "document_id": "doc-1",
    "document_title": "Physics handbook",
    "page_num": 12,
    "text_preview": "At sea level,\nwater boils at 100 C.",
}]


def test_manual_note_can_be_created_edited_and_deleted(client):
    api, _ = client
    project_id = create_project(api)
    base = "/api/projects/%s/notes" % project_id

    created = api.post(base, json={"title": "Idea", "content": "# Draft"})
    assert created.status_code == 200
    note = created.json()
    assert note["origin"] == "manual"
    assert note["content"] == "# Draft"
    assert note["created_at"].endswith("Z") or "+00:00" in note["created_at"]

    edited = api.put("%s/%s" % (base, note["id"]), json={"content": "# Final"})
    assert edited.status_code == 200
    assert edited.json()["title"] == "Idea"
    assert edited.json()["content"] == "# Final"

    assert api.delete("%s/%s" % (base, note["id"])).status_code == 200
    assert api.get(base).json() == []


def test_notes_list_newest_first(client):
    api, _ = client
    project_id = create_project(api)
    base = "/api/projects/%s/notes" % project_id
    for title in ("first", "second", "third"):
        api.post(base, json={"title": title})

    assert [n["title"] for n in api.get(base).json()] == ["third", "second", "first"]


def test_saving_an_answer_keeps_its_citations(client):
    api, session_factory = client
    project_id = create_project(api)
    message_id = add_message(session_factory, project_id, citations=CITATIONS)

    response = api.post("/api/projects/%s/notes" % project_id, json={
        "title": "Boiling point", "content": "ignored", "source_message_id": message_id})

    assert response.status_code == 200
    note = response.json()
    assert note["origin"] == "answer"
    assert note["source_message_id"] == message_id
    assert note["content"].startswith("Water boils at 100 C [1].")
    assert "- [1] Physics handbook, page 12" in note["content"]
    assert "> At sea level, water boils at 100 C." in note["content"]


def test_saved_answer_outlives_its_conversation(client):
    api, session_factory = client
    project_id = create_project(api)
    message_id = add_message(session_factory, project_id)
    api.post("/api/projects/%s/notes" % project_id,
             json={"title": "Kept", "source_message_id": message_id})

    with session_factory() as db:
        db.delete(db.query(Conversation).one())
        db.commit()

    assert [n["title"] for n in api.get("/api/projects/%s/notes" % project_id).json()] == ["Kept"]


@pytest.mark.parametrize("other_project, role", [(True, "assistant"), (False, "user")])
def test_only_an_answer_from_the_same_project_can_be_saved(client, other_project, role):
    api, session_factory = client
    project_id = create_project(api)
    source_project = create_project(api, "Other") if other_project else project_id
    message_id = add_message(session_factory, source_project, role=role)

    response = api.post("/api/projects/%s/notes" % project_id,
                        json={"title": "Nope", "source_message_id": message_id})

    assert response.status_code == 404


def test_a_note_cannot_be_reached_through_another_project(client):
    api, _ = client
    project_id = create_project(api)
    other_id = create_project(api, "Other")
    note_id = api.post("/api/projects/%s/notes" % project_id, json={"title": "Mine"}).json()["id"]

    assert api.put("/api/projects/%s/notes/%s" % (other_id, note_id),
                   json={"title": "x"}).status_code == 404
    assert api.delete("/api/projects/%s/notes/%s" % (other_id, note_id)).status_code == 404


def test_notes_are_deleted_with_their_project(client):
    api, session_factory = client
    project_id = create_project(api)
    api.post("/api/projects/%s/notes" % project_id, json={"title": "Gone soon"})

    assert api.delete("/api/projects/%s" % project_id).status_code == 200

    with session_factory() as db:
        assert db.query(Note).count() == 0

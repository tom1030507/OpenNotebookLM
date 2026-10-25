"""Notes API: manual notes, saved answers, and their lifecycle."""
from __future__ import annotations

import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Lock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import create_database_engine, get_db
from app.db.models import Base, Conversation, Message, Note, Project
from app.routers import notes, projects
from app.schemas import MindMapResponse, NoteCreate, NOTE_PAYLOAD_MAX_BYTES
from app.services.notes import create_note
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

MIND_MAP = {
    "project_id": "project-1",
    "project_name": "Research",
    "generated_at": "2026-10-25T00:00:00Z",
    "model_used": "fallback",
    "node_count": 1,
    "source_count": 0,
    "total_source_count": 0,
    "root": {
        "id": "root", "label": "Research", "kind": "project",
        "detail": None, "document_id": None, "children": [],
    },
}

VIDEO_SUMMARY = {
    "project_id": "project-1",
    "project_name": "Research",
    "generated_at": "2026-10-25T00:00:00Z",
    "model_used": "fallback",
    "scene_count": 2,
    "estimated_seconds": 3,
    "scenes": [
        {"id": "title", "kind": "title", "headline": "Research",
         "bullets": [], "narration": "Research overview.",
         "document_id": None, "source_label": None},
        {"id": "closing", "kind": "closing", "headline": "Summary",
         "bullets": [], "narration": "That is the summary.",
         "document_id": None, "source_label": None},
    ],
}


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
    assert "- Physics handbook" in note["content"]
    assert "  - [1], page 12" in note["content"]
    assert "    > At sea level, water boils at 100 C." in note["content"]


@pytest.mark.parametrize(("kind", "payload"), [
    ("mindmap", MIND_MAP),
    ("video_summary", VIDEO_SUMMARY),
])
def test_studio_json_notes_keep_the_payload_needed_to_reopen(client, kind, payload):
    api, _ = client
    project_id = create_project(api)

    response = api.post("/api/projects/%s/notes" % project_id, json={
        "title": "Saved %s" % kind,
        "studio_kind": kind,
        "payload_json": {**payload, "project_id": project_id},
    })

    assert response.status_code == 200
    note = response.json()
    assert note["origin"] == "studio"
    assert note["studio_kind"] == kind
    assert note["payload_json"] == {**payload, "project_id": project_id}
    assert api.get("/api/projects/%s/notes" % project_id).json()[0] == note


def test_studio_report_saves_its_markdown_content(client):
    api, _ = client
    project_id = create_project(api)

    response = api.post("/api/projects/%s/notes" % project_id, json={
        "title": "Saved report",
        "content": "# Report\n\nFindings",
        "studio_kind": "report",
    })

    assert response.status_code == 200
    assert response.json()["origin"] == "studio"
    assert response.json()["studio_kind"] == "report"
    assert response.json()["content"] == "# Report\n\nFindings"
    assert response.json()["payload_json"] is None


@pytest.mark.parametrize("payload", [
    {"project_id": "project-1"},
    {**VIDEO_SUMMARY, "scenes": [VIDEO_SUMMARY["scenes"][0]]},
])
def test_malformed_studio_payload_is_rejected(client, payload):
    api, _ = client
    project_id = create_project(api)

    response = api.post("/api/projects/%s/notes" % project_id, json={
        "title": "Invalid", "studio_kind": "video_summary", "payload_json": payload,
    })

    assert 400 <= response.status_code < 500


def test_oversized_studio_payload_is_rejected(client):
    api, _ = client
    project_id = create_project(api)
    payload = {**MIND_MAP, "project_id": project_id, "project_name": "x" * 800_000}

    response = api.post("/api/projects/%s/notes" % project_id, json={
        "title": "Too large", "studio_kind": "mindmap", "payload_json": payload,
    })

    assert response.status_code == 413


def test_studio_payload_is_bounded_after_schema_defaults_are_added(client):
    api, _ = client
    project_id = create_project(api)
    payload = {
        **MIND_MAP,
        "project_id": project_id,
        "root": {
            **MIND_MAP["root"],
            "children": [
                {"id": "n", "label": "x", "kind": "topic"}
                for _ in range(10_000)
            ],
        },
    }
    input_size = len(json.dumps(
        payload, ensure_ascii=False, separators=(",", ":")
    ).encode())
    stored_payload = MindMapResponse.model_validate(payload).model_dump(mode="json")
    stored_size = len(json.dumps(
        stored_payload, ensure_ascii=False, separators=(",", ":")
    ).encode())
    assert input_size < NOTE_PAYLOAD_MAX_BYTES < stored_size

    response = api.post("/api/projects/%s/notes" % project_id, json={
        "title": "Expanded map", "studio_kind": "mindmap", "payload_json": payload,
    })

    assert response.status_code == 413


def test_concurrent_saves_of_the_same_answer_return_one_note(tmp_path):
    database_url = "sqlite:///%s" % (tmp_path / "notes.db")
    engine = create_database_engine(database_url, echo=False)
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    project_id, conversation_id, message_id = (str(uuid.uuid4()) for _ in range(3))
    with session_factory() as db:
        db.add_all([
            Project(id=project_id, name="Research"),
            Conversation(id=conversation_id, project_id=project_id, title="Chat"),
            Message(
                id=message_id, conversation_id=conversation_id,
                role="assistant", text="Answer",
            ),
        ])
        db.commit()

    barrier = Barrier(2)
    barrier_lock = Lock()
    synchronized = 0

    def synchronize_duplicate_lookups(
        _conn, _cursor, statement, _parameters, _context, _many,
    ):
        nonlocal synchronized
        if "FROM notes" not in statement or "source_message_id" not in statement:
            return
        with barrier_lock:
            should_wait = synchronized < 2
            synchronized += 1
        if should_wait:
            barrier.wait(timeout=5)

    event.listen(engine, "before_cursor_execute", synchronize_duplicate_lookups)

    def save_answer(title):
        with session_factory() as db:
            return create_note(db, Project(id=project_id, name="Research"), NoteCreate(
                title=title, source_message_id=message_id,
            )).id

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            note_ids = list(pool.map(save_answer, ["First", "Second"]))
        with session_factory() as db:
            count = db.query(Note).filter(
                Note.project_id == project_id,
                Note.source_message_id == message_id,
            ).count()
        assert note_ids[0] == note_ids[1]
        assert count == 1
    finally:
        event.remove(engine, "before_cursor_execute", synchronize_duplicate_lookups)
        engine.dispose()


def test_studio_payload_must_belong_to_the_note_project(client):
    api, _ = client
    project_id = create_project(api)
    payload = {**MIND_MAP, "project_id": "other-project"}

    response = api.post("/api/projects/%s/notes" % project_id, json={
        "title": "Wrong project", "studio_kind": "mindmap", "payload_json": payload,
    })

    assert response.status_code == 422


def test_saving_the_same_answer_twice_returns_the_existing_note(client):
    api, session_factory = client
    project_id = create_project(api)
    message_id = add_message(session_factory, project_id)
    base = "/api/projects/%s/notes" % project_id

    first = api.post(base, json={"title": "First", "source_message_id": message_id})
    second = api.post(base, json={"title": "Second", "source_message_id": message_id})

    assert first.status_code == second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    assert [note["id"] for note in api.get(base).json()] == [first.json()["id"]]


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

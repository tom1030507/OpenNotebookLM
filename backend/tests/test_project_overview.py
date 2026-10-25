"""Tests for the generated project overview and suggested questions.

The model is injected, so these tests never reach a model server; what they
pin is when generation runs, what is stored, and whose name it may change.
"""
import json
import uuid

import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import get_db
from app.db.models import (
    Base, Chunk, Conversation, Document, Message, Project, ProjectDocument,
)
from app.routers import project_overview, projects
from app.services.project_overview import ProjectOverviewService
from conftest import OfflineLLM, authenticated_client, owner_id

OVERVIEW_REPLY = {
    "title": "Glacier Retreat",
    "overview": "These sources describe how glaciers shrink.",
    "questions": ["Why do glaciers retreat?", "How fast?", "Where?", "A fourth"],
}


class ScriptedLLM:
    """Answers every request with one fixed JSON reply and counts the calls."""

    def __init__(self, reply):
        """Store the reply.

        Args:
            reply: Object serialized as the model's text.
        """
        self.reply = reply
        self.prompts = []

    def generate(self, prompt, **kwargs):
        """Record the prompt and return the scripted reply.

        Args:
            prompt: The prompt sent to the model.
            **kwargs: Ignored.

        Returns:
            The real service's result shape from a named model.
        """
        self.prompts.append(prompt)
        return {"text": json.dumps(self.reply), "model": "scripted", "usage": {}}


@pytest.fixture
def env():
    """An app with the project routes, a fresh database and a scripted model.

    Yields:
        The client, a session factory and the scripted model.
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
    app.include_router(project_overview.router, prefix="/api")
    llm = ScriptedLLM(OVERVIEW_REPLY)
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[project_overview.get_project_overview_service] = (
        lambda: ProjectOverviewService(llm_service=llm)
    )
    with session_factory() as db:
        client = authenticated_client(app, db)

    yield client, session_factory, llm
    engine.dispose()


def add_source(session_factory, project_id, status="ready", title="Glaciers"):
    """Attach a document with one chunk to a project.

    Args:
        session_factory: Session factory for the test database.
        project_id: Project receiving the source.
        status: Document status.
        title: Document title.

    Returns:
        The document id.
    """
    document_id = str(uuid.uuid4())
    with session_factory() as db:
        db.add(Document(
            id=document_id, user_id=owner_id(db), title=title,
            source_type="url", status=status,
        ))
        db.flush()
        db.add_all([
            ProjectDocument(project_id=project_id, document_id=document_id),
            Chunk(id=str(uuid.uuid4()), document_id=document_id,
                  text="Glaciers are retreating worldwide."),
        ])
        db.commit()
    return document_id


def test_a_project_created_without_a_name_gets_a_placeholder(env):
    client, _, _ = env

    response = client.post("/api/projects", json={})

    assert response.status_code == 200
    assert response.json()["name"] == "Untitled notebook"


def test_no_ready_source_means_no_overview_and_no_model_call(env):
    client, session_factory, llm = env
    project_id = client.post("/api/projects", json={}).json()["id"]
    add_source(session_factory, project_id, status="processing")

    body = client.get("/api/projects/%s/overview" % project_id).json()
    with session_factory() as db:
        project = db.get(Project, project_id)
        assert ProjectOverviewService(llm_service=llm).summary(db, project) is None

    assert body == {"project_name": "Untitled notebook", "overview": None, "questions": []}
    assert llm.prompts == []


def test_overview_is_generated_stored_and_titles_an_untitled_project(env):
    client, session_factory, llm = env
    project_id = client.post("/api/projects", json={}).json()["id"]
    add_source(session_factory, project_id)

    first = client.get("/api/projects/%s/overview" % project_id).json()
    second = client.get("/api/projects/%s/overview" % project_id).json()

    assert first == {
        "project_name": "Glacier Retreat",
        "overview": OVERVIEW_REPLY["overview"],
        "questions": OVERVIEW_REPLY["questions"][:3],
    }
    assert second == first
    assert len(llm.prompts) == 1
    assert client.get("/api/projects/%s" % project_id).json()["name"] == "Glacier Retreat"


def test_summary_reuses_the_overview_for_all_ready_sources(env):
    client, session_factory, llm = env
    project_id = client.post("/api/projects", json={}).json()["id"]
    add_source(session_factory, project_id)

    with session_factory() as db:
        project = db.get(Project, project_id)
        service = ProjectOverviewService(llm_service=llm)
        first = service.summary(db, project)
        second = service.summary(db, project)

    assert first == second == OVERVIEW_REPLY["overview"]
    assert len(llm.prompts) == 1


def test_summary_for_a_source_subset_does_not_overwrite_the_project_overview(env):
    client, session_factory, llm = env
    project_id = client.post(
        "/api/projects", json={"name": "My sources"}
    ).json()["id"]
    selected_id = add_source(session_factory, project_id, title="Volcanoes")
    add_source(session_factory, project_id, title="Sea ice")

    with session_factory() as db:
        project = db.get(Project, project_id)
        summary = ProjectOverviewService(llm_service=llm).summary(
            db, project, [selected_id]
        )

        assert project.name == "My sources"
        assert project.overview_json is None

    assert summary == OVERVIEW_REPLY["overview"]
    assert "Source 1: Volcanoes" in llm.prompts[0]
    assert "Sea ice" not in llm.prompts[0]


def test_a_changed_source_set_regenerates(env):
    client, session_factory, llm = env
    project_id = client.post("/api/projects", json={}).json()["id"]
    add_source(session_factory, project_id)
    client.get("/api/projects/%s/overview" % project_id)

    add_source(session_factory, project_id, title="Sea ice")
    client.get("/api/projects/%s/overview" % project_id)

    assert len(llm.prompts) == 2
    assert "Sea ice" in llm.prompts[1]


def test_changing_output_language_regenerates_cached_overview(env):
    client, session_factory, llm = env
    project_id = client.post("/api/projects", json={}).json()["id"]
    add_source(session_factory, project_id)
    client.get("/api/projects/%s/overview" % project_id)

    settings_url = "/api/projects/%s/chat-settings" % project_id
    assert client.put(settings_url, json={"output_language": "fr"}).status_code == 200
    result = client.get("/api/projects/%s/overview" % project_id).json()

    assert result["overview"] == OVERVIEW_REPLY["overview"]
    assert len(llm.prompts) == 2
    assert "Write all generated output in French." in llm.prompts[1]


def test_old_language_overview_is_not_served_when_regeneration_fails(env):
    client, session_factory, llm = env
    project_id = client.post("/api/projects", json={}).json()["id"]
    add_source(session_factory, project_id)
    client.get("/api/projects/%s/overview" % project_id)
    with session_factory() as db:
        project = db.get(Project, project_id)
        project.output_language = "fr"
        db.commit()

    client.app.dependency_overrides[project_overview.get_project_overview_service] = (
        lambda: ProjectOverviewService(llm_service=OfflineLLM())
    )
    result = client.get("/api/projects/%s/overview" % project_id).json()

    assert result["overview"] is None
    assert result["questions"] == []


def test_a_name_the_user_chose_is_never_overwritten(env):
    client, session_factory, _ = env
    named = client.post("/api/projects", json={"name": "My glaciers"}).json()["id"]
    renamed = client.post("/api/projects", json={}).json()["id"]
    client.put("/api/projects/%s" % renamed, json={"name": "Renamed"})
    for project_id in (named, renamed):
        add_source(session_factory, project_id)

    assert client.get(
        "/api/projects/%s/overview" % named).json()["project_name"] == "My glaciers"
    body = client.get("/api/projects/%s/overview" % renamed).json()
    assert body["project_name"] == "Renamed"
    assert body["overview"] == OVERVIEW_REPLY["overview"]


@pytest.mark.parametrize("llm", [OfflineLLM(), ScriptedLLM({"title": "No questions"})])
def test_no_model_or_an_unusable_reply_leaves_the_empty_state(env, llm):
    client, session_factory, _ = env
    project_id = client.post("/api/projects", json={}).json()["id"]
    add_source(session_factory, project_id)
    client.app.dependency_overrides[project_overview.get_project_overview_service] = (
        lambda: ProjectOverviewService(llm_service=llm)
    )

    body = client.get("/api/projects/%s/overview" % project_id).json()

    assert body == {"project_name": "Untitled notebook", "overview": None, "questions": []}
    with session_factory() as db:
        assert db.get(Project, project_id).overview_json is None


def test_follow_ups_come_from_the_last_answer(env):
    client, session_factory, llm = env
    llm.reply = {"questions": ["What next?", "And then?", "Too many"]}
    project_id = client.post("/api/projects", json={"name": "Notes"}).json()["id"]
    with session_factory() as db:
        db.add(Conversation(id="c1", project_id=project_id))
        db.add_all([
            Message(id="m1", conversation_id="c1", role="user", text="Why retreat?"),
            Message(id="m2", conversation_id="c1", role="assistant", text="Warming."),
        ])
        db.commit()

    body = client.post("/api/conversations/c1/follow-ups").json()

    assert body == {"questions": ["What next?", "And then?"]}
    assert "Why retreat?" in llm.prompts[0] and "Warming." in llm.prompts[0]


def test_follow_ups_use_the_project_output_language(env):
    client, session_factory, llm = env
    llm.reply = {"questions": ["Que se passe-t-il ensuite ?", "Pourquoi ?"]}
    project_id = client.post("/api/projects", json={"name": "Notes"}).json()["id"]
    client.put(
        "/api/projects/%s/chat-settings" % project_id,
        json={"output_language": "fr"},
    )
    with session_factory() as db:
        db.add(Conversation(id="c-fr", project_id=project_id, title="Chat"))
        db.add_all([
            Message(id="m-fr-user", conversation_id="c-fr", role="user", text="Why?"),
            Message(id="m-fr-answer", conversation_id="c-fr", role="assistant", text="Because."),
        ])
        db.commit()

    client.post("/api/conversations/c-fr/follow-ups")

    assert "Write all generated output in French." in llm.prompts[0]


def test_an_unanswered_conversation_has_no_follow_ups(env):
    client, session_factory, llm = env
    project_id = client.post("/api/projects", json={"name": "Notes"}).json()["id"]
    with session_factory() as db:
        db.add(Conversation(id="c1", project_id=project_id))
        db.commit()

    assert client.post("/api/conversations/c1/follow-ups").json() == {"questions": []}
    assert llm.prompts == []

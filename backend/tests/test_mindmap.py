"""Tests for the mind map API.

The service is injected rather than constructed by the router, so these tests
never reach for a model server. With `LLM_MODE` defaulting to `auto` a
module-level service would point at a local provider and every request here
would open a socket to it.
"""
import inspect

import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import get_db
from app.db.models import Base, Chunk, Document, Project, ProjectDocument, User
from app.routers import mindmap
from app.services.mindmap import MindMapService
from conftest import auth_headers, authenticated_client, owner_id, seed_user

app = FastAPI()
app.include_router(mindmap.router, prefix="/api")

engine = create_engine(
    "sqlite:///:memory:",
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


class SilentLLM:
    """LLM stand-in that answers as the unconfigured service does.

    Topics then come from document structure, which is what these tests are
    about; the generated path is covered in `tests/unit/test_mindmap_service.py`.
    """

    def generate(self, prompt, **kwargs):
        """Return the extractive fallback shape."""
        return {
            "text": "Configure an LLM for better answers.",
            "model": "fallback",
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }


app.dependency_overrides[get_db] = override_get_db
app.dependency_overrides[mindmap.get_mindmap_service] = lambda: MindMapService(
    llm_service=SilentLLM(),
)

Base.metadata.create_all(bind=engine)

with TestingSessionLocal() as setup_session:
    client = authenticated_client(app, setup_session)


@pytest.fixture
def two_projects_with_own_documents():
    """Seed two projects, each owning one document with one chunk."""
    with TestingSessionLocal() as db:
        owner = owner_id(db)
        db.add_all([
            Project(id="project-a", user_id=owner, name="Project A"),
            Project(id="project-b", user_id=owner, name="Project B"),
            Document(
                id="document-a",
                user_id=owner,
                title="Only In A",
                source_type="url",
                status="ready",
            ),
            Document(
                id="document-b",
                user_id=owner,
                title="Only In B",
                source_type="url",
                status="ready",
            ),
        ])
        db.flush()
        db.add_all([
            ProjectDocument(project_id="project-a", document_id="document-a"),
            ProjectDocument(project_id="project-b", document_id="document-b"),
            Chunk(
                id="chunk-a",
                document_id="document-a",
                text="Anything",
                heading_path="Only In A/Rainfall",
            ),
            Chunk(
                id="chunk-b",
                document_id="document-b",
                text="Anything",
                heading_path="Only In B/Glaciers",
            ),
        ])
        db.commit()

    yield

    with TestingSessionLocal() as db:
        db.query(Chunk).delete()
        db.query(ProjectDocument).delete()
        db.query(Document).delete()
        db.query(Project).delete()
        db.commit()


@pytest.fixture
def empty_project():
    """Seed a project with no sources attached."""
    with TestingSessionLocal() as db:
        db.add(Project(id="project-empty", user_id=owner_id(db), name="Nothing yet"))
        db.commit()

    yield

    with TestingSessionLocal() as db:
        db.query(Project).delete()
        db.commit()


def test_the_root_is_the_project(two_projects_with_own_documents):
    """The map is rooted in the project it was asked about."""
    response = client.post("/api/projects/project-a/mindmap")

    assert response.status_code == 200
    body = response.json()
    assert body["project_id"] == "project-a"
    assert body["root"]["label"] == "Project A"
    assert body["root"]["kind"] == "project"


def test_each_source_is_a_branch(two_projects_with_own_documents):
    """One branch per source, and only this project's sources."""
    body = client.post("/api/projects/project-a/mindmap").json()

    branches = body["root"]["children"]
    assert [branch["label"] for branch in branches] == ["Only In A"]
    assert branches[0]["document_id"] == "document-a"


def test_another_projects_sources_are_absent(two_projects_with_own_documents):
    """A mind map must not leak a sibling project's sources."""
    assert "Only In B" not in client.post("/api/projects/project-a/mindmap").text


@pytest.mark.parametrize("status", ["queued", "processing", "failed"])
def test_unready_sources_never_reach_the_map_or_model(
    two_projects_with_own_documents, monkeypatch, status,
):
    """Partly extracted or failed sources cannot contribute unreliable content."""
    prompts = []

    class CapturingLLM(SilentLLM):
        def generate(self, prompt, **kwargs):
            prompts.append(prompt)
            return super().generate(prompt, **kwargs)

    monkeypatch.setitem(app.dependency_overrides, mindmap.get_mindmap_service,
                        lambda: MindMapService(CapturingLLM()))
    with TestingSessionLocal() as db:
        db.query(Document).filter(Document.id == "document-a").update({"status": status})
        db.commit()

    response = client.post("/api/projects/project-a/mindmap")

    assert response.status_code == 200
    assert response.json()["root"]["children"] == []
    assert prompts == []


def test_foreign_document_link_cannot_leak_content_to_the_model(
    two_projects_with_own_documents, monkeypatch,
):
    """An invalid cross-account project link must not defeat document ownership."""
    prompts = []

    class CapturingLLM(SilentLLM):
        def generate(self, prompt, **kwargs):
            prompts.append(prompt)
            return super().generate(prompt, **kwargs)

    monkeypatch.setitem(app.dependency_overrides, mindmap.get_mindmap_service,
                        lambda: MindMapService(CapturingLLM()))
    with TestingSessionLocal() as db:
        stranger = seed_user(db, "mindmap-stranger")
        db.add(Document(id="foreign-document", user_id=stranger.id,
                        title="Foreign private source", content="Private source evidence",
                        source_type="txt", status="ready"))
        db.flush()
        db.add(ProjectDocument(project_id="project-a", document_id="foreign-document"))
        db.commit()

    try:
        response = client.post("/api/projects/project-a/mindmap")

        assert response.status_code == 200
        assert "Foreign private source" not in response.text
        assert "Private source evidence" not in "\n".join(prompts)
        assert "Foreign private source" not in "\n".join(prompts)
    finally:
        with TestingSessionLocal() as db:
            db.query(ProjectDocument).filter(
                ProjectDocument.document_id == "foreign-document",
            ).delete()
            db.query(Document).filter(Document.id == "foreign-document").delete()
            db.query(User).filter(User.username == "mindmap-stranger").delete()
            db.commit()


def test_headings_become_topics(two_projects_with_own_documents):
    """The second level is the document's own structure."""
    body = client.post("/api/projects/project-a/mindmap").json()

    topics = body["root"]["children"][0]["children"]
    assert [topic["label"] for topic in topics] == ["Rainfall"]


def test_node_count_covers_the_whole_tree(two_projects_with_own_documents):
    """Root, one document, one topic."""
    assert client.post("/api/projects/project-a/mindmap").json()["node_count"] == 3


@pytest.fixture
def many_project_documents(two_projects_with_own_documents):
    """A project larger than the model input budget still owns all its sources."""
    with TestingSessionLocal() as db:
        for index in range(1, 25):
            document_id = "extra-%02d" % index
            db.add(Document(
                id=document_id, user_id=owner_id(db), title="ZZ Source %02d" % index,
                content="Climate rainfall glaciers oceans wind atmosphere.",
                source_type="txt", status="ready",
            ))
            db.flush()
            db.add(ProjectDocument(project_id="project-a", document_id=document_id))
        db.commit()


def test_fallback_keeps_every_source_when_project_exceeds_model_budget(many_project_documents):
    """A model input cap must not silently remove ready sources from the outline."""
    response = client.post("/api/projects/project-a/mindmap")

    assert response.status_code == 200
    body = response.json()
    assert len(body["root"]["children"]) == 25
    assert "extra-24" in {node["document_id"] for node in body["root"]["children"]}
    assert body["source_count"] == 25
    assert body["total_source_count"] == 25
    assert body["node_count"] <= 25 + 96 + 1


def test_generated_map_reports_partial_source_coverage(many_project_documents, monkeypatch):
    """The UI must distinguish the first 24 sampled sources from the full project."""
    class ConceptLLM:
        def generate(self, prompt, **kwargs):
            return {
                "text": ('{"root":{"label":"Climate","children":'
                         '[{"label":"Atmosphere","document_index":1,"children":'
                         '[{"label":"Rainfall","document_index":1}]}]}}'),
                "model": "test-concept-model",
            }

    monkeypatch.setitem(app.dependency_overrides, mindmap.get_mindmap_service,
                        lambda: MindMapService(ConceptLLM()))

    response = client.post("/api/projects/project-a/mindmap")

    assert response.status_code == 200
    body = response.json()
    assert body["root"]["label"] == "Climate"
    assert body["root"]["children"][0]["children"][0]["label"] == "Rainfall"
    assert body["source_count"] == 24
    assert body["total_source_count"] == 25


def test_the_model_is_reported(two_projects_with_own_documents):
    """`model_used` distinguishes a generated map from an extracted one."""
    body = client.post("/api/projects/project-a/mindmap").json()

    assert body["model_used"] == "fallback"


def test_generated_at_carries_a_utc_designator(two_projects_with_own_documents):
    """A designator-less timestamp is read as local time by the browser."""
    generated_at = client.post("/api/projects/project-a/mindmap").json()["generated_at"]

    assert generated_at.endswith("Z") or generated_at.endswith("+00:00")


def test_an_empty_project_maps_to_a_lone_root(empty_project):
    """A project with no sources answers, rather than failing."""
    response = client.post("/api/projects/project-empty/mindmap")

    assert response.status_code == 200
    assert response.json()["root"]["children"] == []
    assert response.json()["node_count"] == 1


def test_a_missing_project_is_not_found():
    """An id that names nothing answers 404, not 500."""
    assert client.post("/api/projects/nope/mindmap").status_code == 404


def test_an_anonymous_caller_is_refused():
    """Every data-bearing route sits behind the token check."""
    anonymous = client.__class__(app)

    assert anonymous.post("/api/projects/project-a/mindmap").status_code == 401
    assert client.__class__(
        app, headers=auth_headers(),
    ).post("/api/projects/project-a/mindmap").status_code in (200, 404)


def test_get_cannot_generate_a_mind_map(two_projects_with_own_documents):
    """Reading a URL must not run the project generation command."""
    assert client.get("/api/projects/project-a/mindmap").status_code == 405


def test_the_route_is_not_a_coroutine():
    """A blocking route has to run in the threadpool, not on the event loop.

    Building a map calls the LLM, which blocks for as long as the model takes.
    The container runs a single uvicorn worker, so an `async def` here that
    never awaits stalls every other request for that whole time — `/healthz`
    included, which the compose healthcheck gives ten seconds. FastAPI hands a
    plain `def` handler to its threadpool, which is where that work belongs.
    """
    assert not inspect.iscoroutinefunction(mindmap.project_mindmap)

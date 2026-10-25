"""Tests for project management API."""
import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import get_db
from app.db.models import (
    Base,
    Conversation,
    Document,
    Note,
    Project,
    ProjectDocument,
    User,
)
from app.routers import projects
from app.services.projects import ProjectService
from app.schemas import PROJECT_COVER_COLORS, PROJECT_COVER_EMOJIS
from conftest import authenticated_client


app = FastAPI()
app.include_router(projects.router, prefix="/api")

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


def test_create_project():
    """Test creating a new project."""
    response = client.post(
        "/api/projects",
        json={
            "name": "Test Project",
            "description": "A test project description"
        }
    )
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Test Project"
    assert data["description"] == "A test project description"
    assert "id" in data


def test_list_projects():
    """Test listing projects."""
    # Create a few projects first
    for i in range(3):
        client.post(
            "/api/projects",
            json={"name": f"Project {i}"}
        )
    
    response = client.get("/api/projects")
    assert response.status_code == 200
    data = response.json()
    assert "projects" in data
    assert "total" in data
    assert len(data["projects"]) > 0


def test_get_project():
    """Test getting a specific project."""
    # Create a project first
    create_response = client.post(
        "/api/projects",
        json={"name": "Get Test Project"}
    )
    project_id = create_response.json()["id"]
    
    # Get the project
    response = client.get(f"/api/projects/{project_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == project_id
    assert data["name"] == "Get Test Project"


def test_get_nonexistent_project():
    """Test getting a project that doesn't exist."""
    response = client.get("/api/projects/nonexistent-id")
    assert response.status_code == 404


def test_update_project():
    """Test updating a project."""
    # Create a project first
    create_response = client.post(
        "/api/projects",
        json={"name": "Original Name"}
    )
    project_id = create_response.json()["id"]
    
    # Update the project
    response = client.put(
        f"/api/projects/{project_id}",
        json={
            "name": "Updated Name",
            "description": "Updated description"
        }
    )
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Updated Name"
    assert data["description"] == "Updated description"


def test_delete_project():
    """Test deleting a project."""
    # Create a project first
    create_response = client.post(
        "/api/projects",
        json={"name": "To Delete"}
    )
    project_id = create_response.json()["id"]
    
    # Delete the project
    response = client.delete(f"/api/projects/{project_id}")
    assert response.status_code == 200
    
    # Verify it's deleted
    get_response = client.get(f"/api/projects/{project_id}")
    assert get_response.status_code == 404


def test_remove_document_from_project_preserves_shared_document():
    """Removing a source from one project must not globally delete it."""
    first_project = client.post(
        "/api/projects",
        json={"name": "First Shared Project"},
    ).json()
    second_project = client.post(
        "/api/projects",
        json={"name": "Second Shared Project"},
    ).json()

    with TestingSessionLocal() as db:
        db.add(Document(
            id="shared-document",
            title="Shared Paper",
            source_type="pdf",
            status="ready",
        ))
        db.add_all([
            ProjectDocument(
                project_id=first_project["id"],
                document_id="shared-document",
            ),
            ProjectDocument(
                project_id=second_project["id"],
                document_id="shared-document",
            ),
        ])
        db.commit()

    response = client.delete(
        f"/api/projects/{first_project['id']}/documents/shared-document",
    )

    assert response.status_code == 200
    with TestingSessionLocal() as db:
        assert db.get(Document, "shared-document") is not None
        assert db.query(ProjectDocument).filter_by(
            project_id=first_project["id"],
            document_id="shared-document",
        ).first() is None
        assert db.query(ProjectDocument).filter_by(
            project_id=second_project["id"],
            document_id="shared-document",
        ).first() is not None


def test_search_projects():
    """Test searching projects."""
    # Create projects with different names
    client.post("/api/projects", json={"name": "Alpha Project"})
    client.post("/api/projects", json={"name": "Beta Test"})
    client.post("/api/projects", json={"name": "Gamma Project"})
    
    # Search for projects containing "Project"
    response = client.get("/api/projects?search=Project")
    assert response.status_code == 200
    data = response.json()
    
    # Should find Alpha and Gamma projects
    project_names = [p["name"] for p in data["projects"]]
    assert any("Alpha" in name for name in project_names)
    assert any("Gamma" in name for name in project_names)


def test_pagination():
    """Test project list pagination."""
    # Create 15 projects
    for i in range(15):
        client.post("/api/projects", json={"name": f"Page Test {i}"})
    
    # Get first page
    response = client.get("/api/projects?page=1&per_page=5")
    assert response.status_code == 200
    data = response.json()
    assert len(data["projects"]) <= 5
    assert data["page"] == 1
    assert data["per_page"] == 5
    
    # Get second page
    response = client.get("/api/projects?page=2&per_page=5")
    assert response.status_code == 200
    data = response.json()
    assert data["page"] == 2


def test_project_cover_defaults_validates_and_persists():
    """New projects get a stable emoji, and updates reject unsupported covers."""
    response = client.post("/api/projects", json={"name": "Covered"})

    assert response.status_code == 200
    project = response.json()
    expected = PROJECT_COVER_EMOJIS[int(project["id"].replace("-", ""), 16) % len(PROJECT_COVER_EMOJIS)]
    assert project["cover_emoji"] == expected
    assert project["cover_color"] is None

    saved = client.put(
        f"/api/projects/{project['id']}",
        json={"cover_emoji": PROJECT_COVER_EMOJIS[1], "cover_color": PROJECT_COVER_COLORS[0]},
    )
    assert saved.status_code == 200
    assert saved.json()["cover_emoji"] == PROJECT_COVER_EMOJIS[1]
    assert saved.json()["cover_color"] == PROJECT_COVER_COLORS[0]
    assert client.put(
        f"/api/projects/{project['id']}", json={"cover_emoji": "📚hello"}
    ).status_code == 422
    assert client.put(
        f"/api/projects/{project['id']}", json={"cover_color": "#ffffff"}
    ).status_code == 422


def test_duplicate_project_copies_owned_data_but_not_conversations():
    """A duplicate owns its links and notes without cloning conversations."""
    original = client.post(
        "/api/projects",
        json={"name": "Notebook", "description": "Summary", "meta_json": {"nested": {"key": "value"}}},
    ).json()
    client.put(
        f"/api/projects/{original['id']}/chat-settings",
        json={"role": "custom", "instructions": "Be concise", "answer_length": "longer"},
    )

    with TestingSessionLocal() as db:
        project = db.get(Project, original["id"])
        owner_id = project.user_id
        foreign_owner = User(
            id="foreign-owner",
            username="foreign-owner",
            email="foreign-owner@example.com",
            hashed_password="unused",
        )
        own_document = Document(
            id="copy-own-document", user_id=owner_id, title="Owned", source_type="pdf", status="ready"
        )
        foreign_document = Document(
            id="copy-foreign-document", user_id=foreign_owner.id, title="Foreign", source_type="pdf", status="ready"
        )
        db.add_all([
            foreign_owner,
            own_document,
            foreign_document,
            ProjectDocument(project_id=project.id, document_id=own_document.id),
            ProjectDocument(project_id=project.id, document_id=foreign_document.id),
            Note(
                id="copy-note",
                project_id=project.id,
                title="Saved",
                content="Body",
                origin="studio",
                studio_kind="video_summary",
                payload_json={"project_id": project.id, "project_name": project.name, "x": [1]},
            ),
            Conversation(id="copy-conversation", project_id=project.id, title="Chat"),
        ])
        project.overview_json = {"private": "generated overview"}
        db.commit()

    response = client.post(f"/api/projects/{original['id']}/duplicate")

    assert response.status_code == 200, response.text
    duplicate = response.json()
    assert duplicate["id"] != original["id"]
    assert duplicate["name"] == "Notebook (copy)"
    assert duplicate["description"] == "Summary"
    assert duplicate["meta_json"] == {"nested": {"key": "value"}}
    assert client.get(f"/api/projects/{duplicate['id']}/chat-settings").json() == {
        "role": "custom", "instructions": "Be concise", "answer_length": "longer"
    }
    with TestingSessionLocal() as db:
        copied = db.get(Project, duplicate["id"])
        assert copied.overview_json is None
        assert {link.document_id for link in copied.documents} == {"copy-own-document"}
        assert len(copied.notes) == 1
        assert (copied.notes[0].title, copied.notes[0].content, copied.notes[0].payload_json) == (
            "Saved", "Body", {
                "project_id": duplicate["id"],
                "project_name": duplicate["name"],
                "x": [1],
            }
        )
        assert copied.conversations == []
        copied.notes[0].payload_json = {
            **copied.notes[0].payload_json,
            "x": [*copied.notes[0].payload_json["x"], 2],
        }
        db.commit()
        assert db.get(Note, "copy-note").payload_json["x"] == [1]

    changed = client.put(
        f"/api/projects/{duplicate['id']}",
        json={"name": "Independent copy", "meta_json": {"changed": True}},
    )
    assert changed.status_code == 200
    client.put(
        f"/api/projects/{duplicate['id']}/chat-settings",
        json={"role": "default", "instructions": "", "answer_length": "shorter"},
    )
    assert client.delete(
        f"/api/projects/{duplicate['id']}/documents/copy-own-document"
    ).status_code == 200
    assert client.get(f"/api/projects/{original['id']}").json()["name"] == "Notebook"
    assert client.get(f"/api/projects/{original['id']}/chat-settings").json() == {
        "role": "custom", "instructions": "Be concise", "answer_length": "longer"
    }
    assert "copy-own-document" in {
        document["id"] for document in client.get(
            f"/api/projects/{original['id']}/documents"
        ).json()
    }

    assert client.delete(f"/api/projects/{duplicate['id']}").status_code == 200
    with TestingSessionLocal() as db:
        assert db.get(Document, "copy-own-document") is not None
        assert db.get(Project, original["id"]) is not None
        assert db.get(Note, "copy-note") is not None


def test_duplicate_rolls_back_when_link_creation_fails():
    """A failed association insert leaves no half-created project behind."""
    original = client.post("/api/projects", json={"name": "Atomic"}).json()
    with TestingSessionLocal() as db:
        project = db.get(Project, original["id"])
        document = Document(
            id="atomic-document", user_id=project.user_id, title="Owned", source_type="pdf", status="ready"
        )
        db.add_all([document, ProjectDocument(project_id=project.id, document_id=document.id)])
        db.commit()

    def fail_link_insert(mapper, connection, link):
        raise RuntimeError("simulated link failure")

    event.listen(ProjectDocument, "before_insert", fail_link_insert)
    try:
        response = client.post(f"/api/projects/{original['id']}/duplicate")
    finally:
        event.remove(ProjectDocument, "before_insert", fail_link_insert)

    assert response.status_code == 500
    with TestingSessionLocal() as db:
        assert db.query(Project).filter(Project.name == "Atomic (copy)").count() == 0


def test_duplicate_preserves_suffix_for_max_length_project_name():
    """A copied name retains the required suffix when the source is 200 chars."""
    name = "x" * 200
    original = client.post("/api/projects", json={"name": name}).json()

    response = client.post(f"/api/projects/{original['id']}/duplicate")

    assert response.status_code == 200, response.text
    assert response.json()["name"] == f"{name} (copy)"


if __name__ == "__main__":
    # Run basic tests
    print("Running project API tests...")
    test_create_project()
    print("✓ Create project test passed")
    test_list_projects()
    print("✓ List projects test passed")
    test_get_project()
    print("✓ Get project test passed")
    test_update_project()
    print("✓ Update project test passed")
    test_delete_project()
    print("✓ Delete project test passed")
    print("\n✅ All tests passed!")


def test_chat_settings_default_until_set():
    """A new project answers with the default role and length."""
    project_id = client.post("/api/projects", json={"name": "Chat"}).json()["id"]

    response = client.get(f"/api/projects/{project_id}/chat-settings")

    assert response.status_code == 200
    assert response.json() == {
        "role": "default", "instructions": "", "answer_length": "default"}


def test_chat_settings_persist():
    """Saved chat settings are what the project reads back."""
    project_id = client.post("/api/projects", json={"name": "Chat"}).json()["id"]
    settings = {"role": "custom", "instructions": "Answer as a terse reviewer.",
                "answer_length": "shorter"}

    assert client.put(
        f"/api/projects/{project_id}/chat-settings", json=settings).json() == settings
    assert client.get(f"/api/projects/{project_id}/chat-settings").json() == settings


def test_chat_settings_reject_unknown_values_and_long_instructions():
    """Only the listed roles and lengths are accepted, and instructions are capped."""
    project_id = client.post("/api/projects", json={"name": "Chat"}).json()["id"]
    url = f"/api/projects/{project_id}/chat-settings"

    assert client.put(url, json={"role": "pirate"}).status_code == 422
    assert client.put(url, json={"answer_length": "epic"}).status_code == 422
    assert client.put(url, json={"instructions": "x" * 2001}).status_code == 422
    assert client.get(url).json()["role"] == "default"

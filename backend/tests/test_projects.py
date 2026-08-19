"""Tests for project management API."""
import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import get_db
from app.db.models import Base, Document, ProjectDocument
from app.routers import projects
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

"""Tests for the export API."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import get_db
from app.db.models import Base, Document, Project, ProjectDocument
from app.routers import export


app = FastAPI()
app.include_router(export.router, prefix="/api")

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

# Create test client
client = TestClient(app)


@pytest.fixture
def two_projects_with_own_documents():
    """Seed two projects, each owning exactly one document."""
    with TestingSessionLocal() as db:
        db.add_all([
            Project(id="project-a", name="Project A"),
            Project(id="project-b", name="Project B"),
            Document(
                id="document-a",
                title="Only In A",
                source_type="pdf",
                status="ready",
            ),
            Document(
                id="document-b",
                title="Only In B",
                source_type="pdf",
                status="ready",
            ),
        ])
        db.flush()
        db.add_all([
            ProjectDocument(project_id="project-a", document_id="document-a"),
            ProjectDocument(project_id="project-b", document_id="document-b"),
        ])
        db.commit()

    yield

    with TestingSessionLocal() as db:
        db.query(ProjectDocument).delete()
        db.query(Document).delete()
        db.query(Project).delete()
        db.commit()


def test_json_export_only_includes_own_documents(two_projects_with_own_documents):
    """A JSON project export must not leak another project's sources."""
    response = client.get("/api/export/project/project-a?format=json")

    assert response.status_code == 200
    document_ids = [doc["id"] for doc in response.json()["documents"]]
    assert document_ids == ["document-a"]


def test_markdown_export_only_includes_own_documents(two_projects_with_own_documents):
    """A Markdown project export must not leak another project's sources."""
    response = client.get("/api/export/project/project-a?format=markdown")

    assert response.status_code == 200
    assert "Only In A" in response.text
    assert "Only In B" not in response.text


def test_project_summary_only_includes_own_documents(two_projects_with_own_documents):
    """A project summary report must not leak another project's sources."""
    response = client.get("/api/export/project/project-a/summary")

    assert response.status_code == 200
    assert "**Documents**: 1" in response.text
    assert "Only In A" in response.text
    assert "Only In B" not in response.text

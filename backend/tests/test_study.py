"""API tests for source-scoped study generation."""
from __future__ import annotations

from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import get_db
from app.db.models import Base, Document, Project, ProjectDocument
from app.routers import study
from conftest import authenticated_client, owner_id

app = FastAPI()
app.include_router(study.router, prefix="/api")
engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    """Provide the test database session."""
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


class StubStudyService:
    """Capture route inputs and return a fixed study response."""

    def __init__(self):
        self.calls = []
        self.result = {"model_used": "stub-model", "items": [], "sources": []}

    def generate_flashcards(self, db, project, document_ids, count, focus):
        self.calls.append(("flashcards", project.id, document_ids, count, focus))
        return self.result

    def generate_quiz(self, db, project, document_ids, count, focus):
        self.calls.append(("quiz", project.id, document_ids, count, focus))
        return self.result


service = StubStudyService()
app.dependency_overrides[get_db] = override_get_db
app.dependency_overrides[study.get_study_service] = lambda: service
Base.metadata.create_all(bind=engine)
with TestingSessionLocal() as setup_session:
    client = authenticated_client(app, setup_session)


def test_flashcards_route_scopes_sources_and_forwards_options():
    """The route validates ownership before forwarding generation options."""
    service.calls.clear()
    service.result = {
        "model_used": "stub-model",
        "items": [{"front": "Term", "back": "Meaning", "document_id": "study-document"}],
        "sources": [{
            "document_id": "study-document", "title": "Source", "excerpt": "Source content",
        }],
    }
    with TestingSessionLocal() as db:
        project_id = "study-project"
        document_id = "study-document"
        db.add(Project(id=project_id, user_id=owner_id(db), name="Study project"))
        db.add(Document(
            id=document_id, user_id=owner_id(db), title="Source",
            source_type="txt", status="ready", content="Source content",
        ))
        db.flush()
        db.add(ProjectDocument(project_id=project_id, document_id=document_id))
        db.commit()

    try:
        response = client.post(
            "/api/projects/study-project/flashcards",
            json={"document_ids": ["study-document"], "count": 7, "focus": "Key ideas"},
        )

        assert response.status_code == 200, response.text
        assert response.json()["project_name"] == "Study project"
        assert response.json()["model_used"] == "stub-model"
        assert response.json()["items"][0]["document_id"] == "study-document"
        assert response.json()["sources"][0]["excerpt"] == "Source content"
        assert service.calls == [("flashcards", "study-project", ["study-document"], 7, "Key ideas")]
    finally:
        with TestingSessionLocal() as db:
            db.query(ProjectDocument).filter_by(project_id="study-project").delete()
            db.query(Document).filter_by(id="study-document").delete()
            db.query(Project).filter_by(id="study-project").delete()
            db.commit()


def test_quiz_route_returns_empty_items_for_unusable_generation():
    """A provider fallback is a valid empty response, not a server error."""
    service.calls.clear()
    service.result = {"model_used": "fallback", "items": [], "sources": []}
    with TestingSessionLocal() as db:
        project_id = "empty-study-project"
        db.add(Project(id=project_id, user_id=owner_id(db), name="Empty study"))
        db.commit()

    try:
        response = client.post("/api/projects/empty-study-project/quiz")

        assert response.status_code == 200, response.text
        assert response.json()["items"] == []
        assert response.json()["sources"] == []
        assert service.calls == [("quiz", "empty-study-project", None, 10, None)]
    finally:
        with TestingSessionLocal() as db:
            db.query(Project).filter_by(id="empty-study-project").delete()
            db.commit()


def test_study_routes_reject_count_and_focus_outside_bounds():
    """Request limits are enforced before the service runs."""
    service.calls.clear()
    with TestingSessionLocal() as db:
        project_id = "bounds-study-project"
        db.add(Project(id=project_id, user_id=owner_id(db), name="Bounds"))
        db.commit()

    try:
        for route, payload in (
            ("flashcards", {"count": 4}),
            ("quiz", {"count": 31}),
            ("flashcards", {"focus": "x" * 501}),
        ):
            response = client.post("/api/projects/bounds-study-project/" + route, json=payload)
            assert response.status_code == 422
        assert service.calls == []
    finally:
        with TestingSessionLocal() as db:
            db.query(Project).filter_by(id="bounds-study-project").delete()
            db.commit()

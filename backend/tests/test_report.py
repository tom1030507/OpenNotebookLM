"""API tests for ownership-scoped report generation."""
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import Settings, get_settings
from app.db.database import get_db
from app.db.models import Base, Document, Project, ProjectDocument
from app.routers import report
from app.routers.rate_limit import get_concurrency_limiter, get_rate_limiter
from app.services.rate_limit import ConcurrencyLimiter, SlidingWindowRateLimiter
from conftest import authenticated_client, owner_id

app = FastAPI()
app.include_router(report.router, prefix="/api")
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


class StubReportService:
    """Capture report requests without loading embeddings or an LLM."""

    def __init__(self):
        self.calls = []

    def generate(self, db, project_id, report_format, instruction, document_ids):
        self.calls.append((project_id, report_format, instruction, document_ids))
        return {
            "markdown": "# Report\n\nFinding [Source 1].",
            "citations": [{
                "id": 1,
                "document_id": "report-document-a",
                "source": "Source A",
                "text": "Finding evidence.",
            }],
        }


service = StubReportService()
app.dependency_overrides[get_db] = override_get_db
app.dependency_overrides[report.get_report_service] = lambda: service
Base.metadata.create_all(bind=engine)
with TestingSessionLocal() as setup_session:
    client = authenticated_client(app, setup_session)


def _seed_project(project_id="report-project"):
    """Create a project and two linked ready sources."""
    with TestingSessionLocal() as db:
        user_id = owner_id(db)
        db.add(Project(id=project_id, user_id=user_id, name="Report project"))
        db.add_all([
            Document(
                id="report-document-a", user_id=user_id, title="Source A",
                source_type="txt", status="ready", content="Finding evidence.",
            ),
            Document(
                id="report-document-b", user_id=user_id, title="Source B",
                source_type="txt", status="ready", content="Additional evidence.",
            ),
        ])
        db.flush()
        db.add_all([
            ProjectDocument(project_id=project_id, document_id="report-document-a"),
            ProjectDocument(project_id=project_id, document_id="report-document-b"),
        ])
        db.commit()


def _delete_project(project_id="report-project"):
    with TestingSessionLocal() as db:
        db.query(ProjectDocument).filter_by(project_id=project_id).delete()
        db.query(Document).filter(
            Document.id.in_(["report-document-a", "report-document-b"]),
        ).delete(synchronize_session=False)
        db.query(Project).filter_by(id=project_id).delete()
        db.commit()


def test_report_route_passes_format_instruction_and_owned_selection_to_service():
    service.calls.clear()
    _seed_project()
    try:
        response = client.post("/api/projects/report-project/report", json={
            "format": "custom",
            "instruction": "Explain the main finding",
            "document_ids": ["report-document-b"],
        })

        assert response.status_code == 200, response.text
        assert response.json() == {
            "markdown": "# Report\n\nFinding [Source 1].",
            "citations": [{
                "id": 1,
                "document_id": "report-document-a",
                "source": "Source A",
                "text": "Finding evidence.",
            }],
        }
        assert service.calls == [(
            "report-project", "custom", "Explain the main finding", ["report-document-b"],
        )]
    finally:
        _delete_project()


def test_report_route_scopes_omitted_selection_to_visible_project_documents():
    service.calls.clear()
    _seed_project()
    try:
        response = client.post("/api/projects/report-project/report", json={
            "format": "briefing",
        })

        assert response.status_code == 200, response.text
        assert service.calls == [(
            "report-project", "briefing", None,
            ["report-document-a", "report-document-b"],
        )]
    finally:
        _delete_project()


def test_report_route_rejects_empty_selection_and_invalid_custom_instructions():
    service.calls.clear()
    _seed_project()
    try:
        responses = [
            client.post("/api/projects/report-project/report", json={
                "format": "briefing", "document_ids": [],
            }),
            client.post("/api/projects/report-project/report", json={
                "format": "briefing", "instruction": "customize this",
            }),
            client.post("/api/projects/report-project/report", json={
                "format": "custom", "instruction": "  ",
            }),
            client.post("/api/projects/report-project/report", json={
                "format": "custom",
            }),
            client.post("/api/projects/report-project/report", json={
                "format": "custom", "instruction": "x" * 501,
            }),
        ]

        assert [response.status_code for response in responses] == [422] * 5
        assert service.calls == []
    finally:
        _delete_project()


def test_report_generation_has_per_account_rate_and_concurrency_limits(monkeypatch):
    _seed_project()
    limiter = SlidingWindowRateLimiter()
    concurrency = ConcurrencyLimiter(max_concurrent=1)
    monkeypatch.setitem(app.dependency_overrides, get_rate_limiter, lambda: limiter)
    monkeypatch.setitem(app.dependency_overrides, get_concurrency_limiter, lambda: concurrency)
    monkeypatch.setitem(
        app.dependency_overrides, get_settings,
        lambda: Settings(rate_limit_enabled=True),
    )
    service.calls.clear()
    with TestingSessionLocal() as db:
        user_id = owner_id(db)
    occupied = concurrency.acquire("report:%s" % user_id)
    try:
        busy = client.post("/api/projects/report-project/report", json={"format": "briefing"})
        occupied.release()
        success = client.post(
            "/api/projects/report-project/report", json={"format": "briefing"},
        )
        within_limit = [
            client.post(
                "/api/projects/report-project/report", json={"format": "briefing"},
            )
            for _ in range(8)
        ]
        over_limit = client.post(
            "/api/projects/report-project/report", json={"format": "briefing"},
        )

        assert busy.status_code == 429
        assert success.status_code == 200
        assert [response.status_code for response in within_limit] == [200] * 8
        assert over_limit.status_code == 429
        assert len(service.calls) == 9
        available = concurrency.acquire("report:%s" % user_id)
        available.release()
    finally:
        occupied.release()
        monkeypatch.delitem(app.dependency_overrides, get_rate_limiter, raising=False)
        monkeypatch.delitem(app.dependency_overrides, get_concurrency_limiter, raising=False)
        monkeypatch.delitem(app.dependency_overrides, get_settings, raising=False)
        _delete_project()

"""API coverage for durable audio overviews and their project ownership."""
from pathlib import Path

import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import Settings, get_settings
from app.db.database import get_db
from app.db.models import AudioOverview, Base, Document, Project, ProjectDocument
from app.routers import audio_overview, projects
from app.routers.audio_overview import get_audio_overview_worker
import app.services.audio_overview as audio_overview_service
from app.services.audio_overview import audio_overview_file_key
from app.services.projects import ProjectService
from conftest import authenticated_client, owner_id


class NotifyingWorker:
    def __init__(self):
        self.notifications = 0

    def notify(self):
        self.notifications += 1


@pytest.fixture
def audio_api():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    app = FastAPI()
    app.include_router(audio_overview.router, prefix="/api")
    app.include_router(projects.router, prefix="/api")

    def override_get_db():
        with sessions() as db:
            yield db

    worker = NotifyingWorker()
    settings = Settings(audio_overview_tts_enabled=True)
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_audio_overview_worker] = lambda: worker
    app.dependency_overrides[get_settings] = lambda: settings
    with sessions() as db:
        client = authenticated_client(app, db)
        user_id = owner_id(db)
        db.add_all([
            Project(id="project-audio-a", user_id=user_id, name="Climate"),
            Project(id="project-audio-b", user_id=user_id, name="Other"),
            Document(
                id="audio-doc-a",
                user_id=user_id,
                title="Selected",
                source_type="text",
                content="Source evidence for the climate overview.",
                status="ready",
            ),
            Document(
                id="audio-doc-b",
                user_id=user_id,
                title="Unselected",
                source_type="text",
                content="This source belongs to another project.",
                status="ready",
            ),
        ])
        db.flush()
        db.add_all([
            ProjectDocument(project_id="project-audio-a", document_id="audio-doc-a"),
            ProjectDocument(project_id="project-audio-b", document_id="audio-doc-b"),
        ])
        db.commit()

    yield client, sessions, worker, settings
    app.dependency_overrides.clear()
    engine.dispose()


@pytest.fixture
def audio_file_root(tmp_path, monkeypatch):
    def resolve(file_path):
        return tmp_path / Path(file_path).name

    monkeypatch.setattr(audio_overview, "resolve_audio_file", resolve)
    monkeypatch.setattr(audio_overview_service, "resolve_audio_file", resolve)
    return tmp_path


def test_create_persists_options_and_notifies_worker(audio_api):
    client, sessions, worker, _ = audio_api

    response = client.post(
        "/api/projects/project-audio-a/audio-overviews",
        json={
            "format": "critique",
            "length": "short",
            "focus": "methods",
            "document_ids": ["audio-doc-a"],
        },
    )

    assert response.status_code == 202, response.text
    body = response.json()
    assert body["status"] == "queued"
    assert body["options"] == {
        "document_ids": ["audio-doc-a"],
        "format": "critique",
        "length": "short",
        "focus": "methods",
        "audience": "general",
    }
    assert worker.notifications == 1
    with sessions() as db:
        saved = db.get(AudioOverview, body["id"])
        assert saved.project_id == "project-audio-a"
        assert saved.file_path == audio_overview_file_key(body["id"])


def test_create_rejects_an_owned_document_not_attached_to_this_project(audio_api):
    client, _, _, _ = audio_api

    response = client.post(
        "/api/projects/project-audio-a/audio-overviews",
        json={"document_ids": ["audio-doc-b"]},
    )

    assert response.status_code == 404


def test_disabled_tts_is_reported_without_queueing_work(audio_api):
    client, sessions, worker, settings = audio_api
    settings.audio_overview_tts_enabled = False

    response = client.post(
        "/api/projects/project-audio-a/audio-overviews",
        json={},
    )

    assert response.status_code == 409
    assert worker.notifications == 0
    with sessions() as db:
        assert db.query(AudioOverview).count() == 0


def test_list_status_file_and_delete_survive_a_reload(audio_api, audio_file_root):
    client, sessions, _, _ = audio_api
    overview_id = "persisted-audio"
    file_key = audio_overview_file_key(overview_id)
    file_path = audio_file_root / Path(file_key).name
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_bytes(b"ID3 test audio")
    with sessions() as db:
        db.add(AudioOverview(
            id=overview_id,
            project_id="project-audio-a",
            status="ready",
            options_json={"format": "brief", "length": "short"},
            script_json=[
                {"speaker": "A", "text": "First host."},
                {"speaker": "B", "text": "Second host."},
            ],
            file_path=file_key,
            duration_seconds=2.0,
        ))
        db.commit()

    listing = client.get("/api/projects/project-audio-a/audio-overviews")
    assert listing.status_code == 200
    assert listing.json()["enabled"] is True
    assert listing.json()["items"][0]["script"][1]["speaker"] == "B"
    assert client.get(
        f"/api/projects/project-audio-a/audio-overviews/{overview_id}"
    ).json()["status"] == "ready"
    audio = client.get(
        f"/api/projects/project-audio-a/audio-overviews/{overview_id}/file"
    )
    assert audio.status_code == 200
    assert audio.headers["content-type"] == "audio/mpeg"
    assert audio.content == b"ID3 test audio"

    deleted = client.delete(
        f"/api/projects/project-audio-a/audio-overviews/{overview_id}"
    )
    assert deleted.status_code == 204
    assert not file_path.exists()
    assert client.get(
        f"/api/projects/project-audio-a/audio-overviews/{overview_id}"
    ).status_code == 404


def test_project_deletion_cascades_rows_and_removes_audio_files(
    audio_api,
    audio_file_root,
):
    _, sessions, _, _ = audio_api
    overview_id = "project-delete-audio"
    file_key = audio_overview_file_key(overview_id)
    file_path = audio_file_root / Path(file_key).name
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_bytes(b"generated audio")
    with sessions() as db:
        db.add(AudioOverview(
            id=overview_id,
            project_id="project-audio-a",
            status="ready",
            options_json={},
            script_json=[],
            file_path=file_key,
        ))
        db.commit()
        assert ProjectService.delete_project(db, "project-audio-a") is True
        assert db.get(AudioOverview, overview_id) is None
    assert not file_path.exists()

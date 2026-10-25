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
from app.routers.rate_limit import get_rate_limiter
from app.services.rate_limit import SlidingWindowRateLimiter
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
        "voice_a": "af_heart",
        "voice_b": "am_adam",
    }
    assert worker.notifications == 1
    with sessions() as db:
        saved = db.get(AudioOverview, body["id"])
        assert saved.project_id == "project-audio-a"
        assert saved.file_path == audio_overview_file_key(body["id"])


def test_create_persists_selected_host_voices(audio_api):
    client, _, _, _ = audio_api

    response = client.post(
        "/api/projects/project-audio-a/audio-overviews",
        json={"voice_a": "af_sarah", "voice_b": "am_eric"},
    )

    assert response.status_code == 202, response.text
    assert response.json()["options"]["voice_a"] == "af_sarah"
    assert response.json()["options"]["voice_b"] == "am_eric"


def test_create_rejects_unlisted_host_voice(audio_api):
    client, _, worker, _ = audio_api

    response = client.post(
        "/api/projects/project-audio-a/audio-overviews",
        json={"voice_a": "not-a-kokoro-voice"},
    )

    assert response.status_code == 422
    assert worker.notifications == 0


def test_voice_preview_returns_audio_from_the_selected_voice(audio_api, monkeypatch):
    client, _, _, _ = audio_api
    calls = []

    class FakeTTS:
        def synthesize(self, script, output_path, voice_a, voice_b="am_adam"):
            calls.append((script, voice_a, voice_b))
            output_path.write_bytes(b"preview mp3")

    monkeypatch.setattr(audio_overview, "get_kokoro_tts", lambda: FakeTTS())

    response = client.post("/api/audio-overview-voices/af_sarah/preview")

    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/mpeg"
    assert response.content == b"preview mp3"
    assert calls == [(
        [{"speaker": "A", "text": audio_overview_service.VOICE_PREVIEW_TEXT}],
        "af_sarah",
        "am_adam",
    )]


def test_voice_preview_rejects_unlisted_voice_without_synthesis(audio_api, monkeypatch):
    client, _, _, _ = audio_api
    monkeypatch.setattr(
        audio_overview,
        "get_kokoro_tts",
        lambda: pytest.fail("invalid voice must not load Kokoro"),
    )

    response = client.post("/api/audio-overview-voices/not-a-kokoro-voice/preview")

    assert response.status_code == 422


def test_voice_preview_respects_disabled_tts(audio_api, monkeypatch):
    client, _, _, settings = audio_api
    settings.audio_overview_tts_enabled = False
    monkeypatch.setattr(
        audio_overview,
        "get_kokoro_tts",
        lambda: pytest.fail("disabled TTS must not load Kokoro"),
    )

    response = client.post("/api/audio-overview-voices/af_sarah/preview")

    assert response.status_code == 409


def test_voice_preview_is_rate_limited_per_account(audio_api, monkeypatch):
    client, _, _, _ = audio_api
    limiter = SlidingWindowRateLimiter()
    client.app.dependency_overrides[get_rate_limiter] = lambda: limiter

    class FakeTTS:
        def synthesize(self, _script, output_path, voice_a, voice_b="am_adam"):
            output_path.write_bytes(b"preview mp3")

    monkeypatch.setattr(audio_overview, "get_kokoro_tts", lambda: FakeTTS())

    for _ in range(20):
        assert client.post("/api/audio-overview-voices/af_sarah/preview").status_code == 200

    response = client.post("/api/audio-overview-voices/af_sarah/preview")

    assert response.status_code == 429


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
    assert {"af_heart", "am_adam"}.issubset(set(listing.json()["voices"]))
    assert listing.json()["items"][0]["options"]["voice_a"] == "af_heart"
    assert listing.json()["items"][0]["options"]["voice_b"] == "am_adam"
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

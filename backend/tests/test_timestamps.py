"""Timestamp contract tests for everything the API emits.

Timestamps are stored naive and in UTC. Serialised without a timezone
designator they read as ``2026-08-13T09:00:00``, and ECMAScript parses a
designator-less date-time as *local* time, so a browser in UTC+8 renders a
conversation created seconds ago as "about 8 hours ago" and files it under the
wrong date-group header.

These tests pin the fix at the source: every datetime the API emits says it is
UTC, and says it without moving the instant.
"""
from __future__ import annotations

import asyncio
import json
import re
import sys
from datetime import datetime, timezone
from types import ModuleType

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import get_db
from app.db.models import (
    Base,
    Conversation,
    Document,
    Message,
    Project,
    ProjectDocument,
)
from app.services.documents import DocumentService


# The timestamp contract does not involve retrieval or model inference. Replace
# that heavyweight boundary before importing the routers so these tests run in
# the minimal API environment.
rag_module = ModuleType("app.services.rag")


class StubRAGService:
    """Stand-in for the unused RAG dependency during route contract tests."""


rag_module.RAGService = StubRAGService
sys.modules["app.services.rag"] = rag_module

from app.routers import export, health, projects, query  # noqa: E402
from conftest import authorize  # noqa: E402


# A JSON string that starts like an ISO 8601 date-time. Deliberately loose: the
# point is to catch every timestamp-shaped value in a payload, including ones
# nested inside meta_json, not to validate the whole grammar.
DATETIME_SHAPED = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}")

# "Z" or a numeric offset. Either one tells a client which zone the value is in;
# absent both, the client has to guess, and guesses local.
UTC_DESIGNATOR = re.compile(r"(?:Z|[+-]\d{2}:?\d{2})$")

# The instant a fixed row was written, as it sits in the database: naive UTC.
STORED_NAIVE_UTC = datetime(2026, 8, 13, 9, 0, 0)
STORED_INSTANT = STORED_NAIVE_UTC.replace(tzinfo=timezone.utc)


def timestamps(payload, path: str = "response"):
    """Yield every ``(path, value)`` in a decoded payload that looks like a datetime."""
    if isinstance(payload, dict):
        for key, value in payload.items():
            yield from timestamps(value, f"{path}.{key}")
    elif isinstance(payload, list):
        for index, value in enumerate(payload):
            yield from timestamps(value, f"{path}[{index}]")
    elif isinstance(payload, str) and DATETIME_SHAPED.match(payload):
        yield path, payload


def assert_all_utc(payload) -> list[str]:
    """Assert every timestamp in a payload is marked UTC; return what was checked."""
    found = list(timestamps(payload))
    undesignated = [
        f"{path}={value!r}"
        for path, value in found
        if not UTC_DESIGNATOR.search(value)
    ]

    assert not undesignated, (
        "timestamps emitted without a UTC designator, which a browser reads as "
        f"local time: {undesignated}"
    )

    return [path for path, _ in found]


def parse_utc(value: str) -> datetime:
    """Parse an API timestamp into an aware datetime (Python 3.10 rejects "Z")."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


@pytest.fixture()
def session_factory():
    """A session factory bound to a fresh in-memory database."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    testing_session = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    yield testing_session

    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture()
def client(session_factory):
    """An API client backed by the fresh in-memory database."""
    app = FastAPI()
    app.include_router(projects.router, prefix="/api")
    app.include_router(query.router, prefix="/api")
    app.include_router(export.router, prefix="/api")
    app.include_router(health.router, prefix="/api")

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    # The routers refuse anonymous callers, so the client holds a token.
    with session_factory() as setup_session:
        headers = authorize(app, setup_session)

    with TestClient(app, headers=headers) as test_client:
        yield test_client


def create_project(client: TestClient, name: str = "Research") -> dict:
    """Create a project through the API."""
    response = client.post("/api/projects", json={"name": name})
    assert response.status_code == 200
    return response.json()


def create_conversation(client: TestClient, project_id: str) -> dict:
    """Create a conversation through the API."""
    response = client.post(
        f"/api/projects/{project_id}/conversations",
        json={"title": "First chat"},
    )
    assert response.status_code == 200
    return response.json()


class TestApiTimestampsAreMarkedUtc:
    """Every datetime-emitting surface has to say the value is UTC."""

    def test_project_create_get_and_list_mark_their_timestamps(self, client):
        created = create_project(client)

        fetched = client.get(f"/api/projects/{created['id']}")
        listed = client.get("/api/projects")

        assert assert_all_utc(created) == ["response.created_at", "response.updated_at"]
        assert assert_all_utc(fetched.json())
        assert assert_all_utc(listed.json())

    def test_conversation_create_rename_and_list_mark_their_timestamps(self, client):
        project = create_project(client)
        created = create_conversation(client, project["id"])

        renamed = client.put(
            f"/api/conversations/{created['id']}",
            json={"title": "Renamed chat"},
        )
        listed = client.get(f"/api/projects/{project['id']}/conversations")

        assert assert_all_utc(created) == ["response.created_at", "response.updated_at"]
        assert assert_all_utc(renamed.json())
        assert assert_all_utc(listed.json())

    def test_conversation_details_mark_conversation_and_message_timestamps(
        self, client, session_factory
    ):
        project = create_project(client)
        conversation = create_conversation(client, project["id"])
        with session_factory() as db:
            db.add(
                Message(
                    id="message-1",
                    conversation_id=conversation["id"],
                    role="assistant",
                    text="Answer",
                    citations_json=[],
                )
            )
            db.commit()

        response = client.get(f"/api/conversations/{conversation['id']}")

        checked = assert_all_utc(response.json())
        # The message timestamp is built by hand into a plain dict rather than a
        # response model, so it is the one most easily left behind.
        assert "response.messages[0].created_at" in checked

    def test_project_documents_mark_record_and_metadata_timestamps(
        self, client, session_factory
    ):
        project = create_project(client)
        with session_factory() as db:
            db.add(
                Document(
                    id="document-1",
                    title="Example Domain",
                    source_type="url",
                    source_url="https://example.com",
                    status="ready",
                    meta_json={"url": "https://example.com"},
                )
            )
            db.add(
                ProjectDocument(project_id=project["id"], document_id="document-1")
            )
            db.commit()

        response = client.get(f"/api/projects/{project['id']}/documents")

        checked = assert_all_utc(response.json())
        assert "response[0].created_at" in checked
        assert "response[0].updated_at" in checked

    def test_conversation_json_export_marks_its_timestamps(
        self, client, session_factory
    ):
        project = create_project(client)
        conversation = create_conversation(client, project["id"])
        with session_factory() as db:
            db.add(
                Message(
                    id="message-1",
                    conversation_id=conversation["id"],
                    role="user",
                    text="Question",
                    citations_json=[],
                )
            )
            db.commit()

        response = client.get(
            f"/api/export/conversation/{conversation['id']}?format=json"
        )

        assert response.status_code == 200
        checked = assert_all_utc(json.loads(response.text))
        assert "response.created_at" in checked
        assert "response.messages[0].created_at" in checked

    def test_project_json_export_marks_its_timestamps(self, client):
        project = create_project(client)
        create_conversation(client, project["id"])

        response = client.get(f"/api/export/project/{project['id']}?format=json")

        assert response.status_code == 200
        assert assert_all_utc(json.loads(response.text))

    def test_health_check_marks_its_timestamp(self, client):
        response = client.get("/api/healthz")

        assert response.status_code == 200
        assert assert_all_utc(response.json()) == ["response.timestamp"]


class TestStoredInstantsSurviveTheRoundTrip:
    """Labelling a value UTC must not also move it."""

    def test_a_stored_naive_utc_row_is_emitted_as_the_same_instant(
        self, client, session_factory
    ):
        project = create_project(client)
        with session_factory() as db:
            db.add(
                Conversation(
                    id="conversation-1",
                    project_id=project["id"],
                    title="Fixed instant",
                    created_at=STORED_NAIVE_UTC,
                    updated_at=STORED_NAIVE_UTC,
                )
            )
            db.commit()

        response = client.get(f"/api/projects/{project['id']}/conversations")

        emitted = response.json()[0]["created_at"]
        assert parse_utc(emitted) == STORED_INSTANT

    def test_a_freshly_written_row_stays_naive_utc_in_the_database(
        self, client, session_factory
    ):
        project = create_project(client)
        conversation = create_conversation(client, project["id"])

        with session_factory() as db:
            # Read the raw column text through textual SQL, bypassing the column
            # type entirely, to prove storage is unchanged: still naive, still
            # UTC, no migration and no offset baked in.
            stored = db.execute(
                text("SELECT created_at FROM conversations WHERE id = :id"),
                {"id": conversation["id"]},
            ).scalar_one()

        assert not UTC_DESIGNATOR.search(stored)
        assert parse_utc(conversation["created_at"]) == datetime.fromisoformat(
            stored
        ).replace(tzinfo=timezone.utc)


class TestIngestionMetadataTimestamps:
    """The timestamps ingestion writes into meta_json are emitted too."""

    def test_url_ingestion_metadata_timestamps_are_marked_utc(self, session_factory):
        class FakeURLAdapter:
            def extract_content(self, url):
                return {
                    "text": "Extracted page body.",
                    "title": "Example Domain",
                    "metadata": {},
                    "headings": [],
                    "links": [],
                }

        class FakeChunkingService:
            def chunk_document(self, db, document_id):
                return []

        class FakeEmbeddingService:
            def embed_chunks(self, db, document_id, force_regenerate=False):
                return []

        service = DocumentService(
            chunking_service=FakeChunkingService(),
            embedding_service=FakeEmbeddingService(),
        )
        service.url_adapter = FakeURLAdapter()

        with session_factory() as db:
            db.add(Project(id="project-1", name="Research notes", meta_json={}))
            db.add(
                Document(
                    id="document-1",
                    title="https://example.com",
                    source_type="url",
                    source_url="https://example.com",
                    status="queued",
                    meta_json={"url": "https://example.com"},
                )
            )
            db.add(ProjectDocument(project_id="project-1", document_id="document-1"))
            db.commit()

            asyncio.run(
                service._process_url_async(db, "document-1", "https://example.com")
            )

            document = db.query(Document).filter(Document.id == "document-1").first()
            checked = assert_all_utc(document.meta_json)

        assert "response.processed_at" in checked

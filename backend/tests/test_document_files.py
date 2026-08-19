"""Tests for the route that serves an uploaded document's file.

The preview pane loads a PDF straight into an iframe, so the bytes have to be
reachable over HTTP. They are reachable per document and nowhere else: the
uploads directory is not mounted, a stored path is only honoured while it stays
inside that directory, and a document without a stored file is a 404 rather
than a hole to probe with guessed filenames.
"""
import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import get_db
from app.db.models import Base, Document
from app.routers import files
from conftest import authenticated_client, owner_id


PDF_BYTES = b"%PDF-1.4 preview me"
DOC_ID = "document-1"
STORED_NAME = f"{DOC_ID}_paper.pdf"


@pytest.fixture
def uploads(tmp_path, monkeypatch):
    """An uploads directory the service will resolve against."""
    monkeypatch.chdir(tmp_path)
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()

    return upload_dir


@pytest.fixture
def db():
    """An isolated in-memory database."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(autocommit=False, autoflush=False, bind=engine)()

    yield session

    session.close()
    engine.dispose()


@pytest.fixture
def client(db):
    """A signed-in client for just the document file route."""
    app = FastAPI()
    app.include_router(files.router, prefix="/api")
    app.dependency_overrides[get_db] = lambda: db

    return authenticated_client(app, db)


def add_document(db, source_url, source_type="pdf", meta_json=None):
    """Record a document with the given stored path."""
    db.add(Document(
        id=DOC_ID,
        user_id=owner_id(db),
        title="Paper",
        source_type=source_type,
        source_url=source_url,
        status="ready",
        meta_json=meta_json if meta_json is not None else {"filename": "paper.pdf"},
    ))
    db.commit()


class TestServingAStoredFile:
    """A real document hands back its real bytes, ready to render inline."""

    @pytest.mark.parametrize("stored_path_is_absolute", [False, True])
    def test_returns_the_stored_bytes(
        self, client, db, uploads, stored_path_is_absolute
    ):
        stored_file = uploads / STORED_NAME
        stored_file.write_bytes(PDF_BYTES)
        # Uploads record a path relative to the working directory, but an
        # absolute one has to work too: it is the same file either way.
        add_document(db, str(stored_file) if stored_path_is_absolute
                     else f"uploads/{STORED_NAME}")

        response = client.get(f"/api/docs/{DOC_ID}/file")

        assert response.status_code == 200
        assert response.content == PDF_BYTES

    def test_is_typed_and_dispositioned_for_inline_preview(
        self, client, db, uploads
    ):
        (uploads / STORED_NAME).write_bytes(PDF_BYTES)
        add_document(db, f"uploads/{STORED_NAME}")

        response = client.get(f"/api/docs/{DOC_ID}/file")

        assert response.headers["content-type"] == "application/pdf"
        # "attachment" would make the iframe download the file instead of
        # showing it, which is the whole point of the route.
        disposition = response.headers["content-disposition"]
        assert disposition.startswith("inline")
        assert "attachment" not in disposition
        assert "paper.pdf" in disposition


class TestMissingFiles:
    """Nothing to serve is a 404, not an error and not someone else's file."""

    def test_unknown_document_id_is_not_found(self, client, uploads):
        response = client.get("/api/docs/does-not-exist/file")

        assert response.status_code == 404

    def test_document_without_a_stored_file_is_not_found(self, client, db, uploads):
        add_document(db, None, meta_json={})

        response = client.get(f"/api/docs/{DOC_ID}/file")

        assert response.status_code == 404

    def test_stored_file_deleted_from_disk_is_not_found(self, client, db, uploads):
        add_document(db, f"uploads/{STORED_NAME}")

        response = client.get(f"/api/docs/{DOC_ID}/file")

        assert response.status_code == 404

    def test_external_source_is_never_read_from_disk(self, client, db, uploads):
        add_document(
            db,
            "https://example.com/article",
            source_type="url",
            meta_json={"url": "https://example.com/article"},
        )

        response = client.get(f"/api/docs/{DOC_ID}/file")

        assert response.status_code == 404


class TestPathTraversal:
    """A stored path may not be used to climb out of the uploads directory."""

    @pytest.mark.parametrize("escape", [
        "uploads/../secret.txt",
        "uploads/../../secret.txt",
        "uploads/subdir/../../secret.txt",
        "/etc/passwd",
    ])
    def test_paths_outside_uploads_are_refused(
        self, client, db, uploads, tmp_path, escape
    ):
        (tmp_path / "secret.txt").write_bytes(b"private")
        add_document(db, escape)

        response = client.get(f"/api/docs/{DOC_ID}/file")

        assert response.status_code == 404
        assert b"private" not in response.content

    def test_traversal_in_the_document_id_serves_no_file(self, client, uploads):
        response = client.get("/api/docs/..%2F..%2Fetc%2Fpasswd/file")

        assert response.status_code == 404
        assert "content-disposition" not in response.headers

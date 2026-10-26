import hashlib
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.db.models import Base, Document, IngestionJob, Project, ProjectDocument
from app.services import watched_folders
from app.services.watched_folders import resolve_watched_folder, scan_watched_folders
from app.utils.time import utc_now


def test_resolve_watched_folder_rejects_paths_outside_configured_root(tmp_path):
    root = tmp_path / "allowed"
    folder = root / "project"
    outside = tmp_path / "private"
    folder.mkdir(parents=True)
    outside.mkdir()

    assert resolve_watched_folder(root, folder) == folder.resolve()
    with pytest.raises(ValueError, match="configured root"):
        resolve_watched_folder(root, outside)


def test_resolve_watched_folder_rejects_symlink_escaping_root(tmp_path):
    root = tmp_path / "allowed"
    root.mkdir()
    outside = tmp_path / "private"
    outside.mkdir()
    link = root / "linked"
    link.symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="configured root"):
        resolve_watched_folder(root, link)


def test_snapshot_skips_file_symlinks_that_escape_watched_folder(tmp_path):
    root = tmp_path / "allowed"
    root.mkdir()
    outside = tmp_path / "private.txt"
    outside.write_text("private", encoding="utf-8")
    (root / "linked.txt").symlink_to(outside)

    snapshot, seen, complete = watched_folders._snapshot_folder(
        root,
        Settings(allowed_file_types="txt", max_file_size_mb=1),
    )

    assert snapshot == {}
    assert seen == set()
    assert complete is False


def test_snapshot_skips_obsidian_settings_directory(tmp_path):
    vault = tmp_path / "vault"
    config = vault / ".obsidian"
    config.mkdir(parents=True)
    (config / "appearance.md").write_text("plugin settings", encoding="utf-8")
    note = vault / "welcome.md"
    note.write_text("# Welcome", encoding="utf-8")

    snapshot, seen, complete = watched_folders._snapshot_folder(
        vault,
        Settings(allowed_file_types="md", max_file_size_mb=1),
    )

    assert set(snapshot) == {str(note.resolve())}
    assert seen == {str(note.resolve())}
    assert complete is True


def test_failed_copy_keeps_existing_private_source(tmp_path):
    target = tmp_path / "uploads" / "source.txt"
    target.parent.mkdir()
    target.write_text("previous source", encoding="utf-8")

    with pytest.raises(FileNotFoundError):
        watched_folders._copy_source(tmp_path / "missing.txt", target, 1024)

    assert target.read_text(encoding="utf-8") == "previous source"


def test_watch_scan_does_not_recreate_a_trashed_source(tmp_path, monkeypatch):
    root = tmp_path / "allowed"
    folder = root / "project"
    folder.mkdir(parents=True)
    source = folder / "notes.txt"
    source.write_text("trashed source", encoding="utf-8")

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    with session_factory() as db:
        project = Project(
            id="project-1",
            name="Watched",
            watched_folder=str(folder),
        )
        document = Document(
            id="trashed-document",
            title="notes.txt",
            source_type="txt",
            source_url="uploads/trashed.txt",
            status="ready",
            watch_source_path=str(source.resolve()),
            deleted_at=utc_now(),
        )
        db.add_all([project, document])
        db.flush()
        db.add(ProjectDocument(project_id=project.id, document_id=document.id))
        db.commit()

    monkeypatch.setattr(watched_folders, "UPLOAD_DIR", tmp_path / "uploads")
    settings = Settings(
        watched_folder_root=str(root),
        allowed_file_types="txt",
        max_file_size_mb=1,
    )

    assert scan_watched_folders(session_factory, settings) == 0

    with session_factory() as db:
        assert db.query(Document).count() == 1
        assert db.query(IngestionJob).count() == 0
    engine.dispose()


def test_watch_imports_edits_and_marks_removed_files(tmp_path, monkeypatch):
    root = tmp_path / "allowed"
    folder = root / "project"
    folder.mkdir(parents=True)
    source = folder / "notes.txt"
    source.write_text("first version", encoding="utf-8")

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    with session_factory() as db:
        db.add(Project(id="project-1", name="Watched", watched_folder=str(folder)))
        db.commit()

    upload_dir = tmp_path / "uploads"
    monkeypatch.setattr(watched_folders, "UPLOAD_DIR", upload_dir)

    class RetrievalIndex:
        deleted = []

        def delete_document(self, _db, document_id):
            self.deleted.append(document_id)

    index = RetrievalIndex()
    monkeypatch.setattr(watched_folders, "get_retrieval_index", lambda: index)
    settings = Settings(
        watched_folder_root=str(root),
        allowed_file_types="txt",
        max_file_size_mb=1,
    )

    try:
        scan_watched_folders(session_factory, settings)
        with session_factory() as db:
            document = db.query(Document).one()
            first_id = document.id
            first_job = db.query(IngestionJob).one()
            assert document.watch_source_path == str(source.resolve())
            assert document.source_url.startswith(str(upload_dir))
            assert first_job.document_id == first_id
            assert first_job.job_type == "file"
            assert document.watch_file_hash == hashlib.sha256(
                b"first version"
            ).hexdigest()
            assert Path(document.source_url).read_text(encoding="utf-8") == "first version"
            first_job.status = "completed"
            first_job.completed_at = utc_now()
            document.status = "ready"
            document.content_hash = hashlib.sha256(b"first version").hexdigest()
            document.last_synced_at = utc_now()
            db.commit()

        scan_watched_folders(session_factory, settings)
        with session_factory() as db:
            assert db.query(IngestionJob).count() == 1
            document = db.query(Document).one()
            assert document.last_sync_changed is False

        source.write_text("second version", encoding="utf-8")
        scan_watched_folders(session_factory, settings)
        with session_factory() as db:
            document = db.query(Document).one()
            assert document.id == first_id
            assert document.watch_file_hash == hashlib.sha256(
                b"second version"
            ).hexdigest()
            jobs = db.query(IngestionJob).order_by(IngestionJob.created_at).all()
            assert len(jobs) == 2
            assert jobs[1].document_id == first_id
            assert jobs[1].status == "queued"
            assert jobs[1].payload_json["previous_status"] == "ready"
            assert Path(document.source_url).read_text(encoding="utf-8") == "second version"
            jobs[1].status = "completed"
            jobs[1].completed_at = utc_now()
            document.status = "ready"
            document.content_hash = hashlib.sha256(b"second version").hexdigest()
            db.commit()

        source.unlink()
        scan_watched_folders(session_factory, settings)
        with session_factory() as db:
            document = db.query(Document).one()
            assert document.id == first_id
            assert document.status == "error"
            assert "removed from the watched folder" in document.error_message
            assert document.last_sync_changed is True
            assert index.deleted == [first_id]
    finally:
        engine.dispose()

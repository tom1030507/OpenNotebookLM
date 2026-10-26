from contextlib import contextmanager
from datetime import timedelta
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import Base, Document, Note, Project, User
from app.services import documents, trash
from app.utils.time import utc_now


@pytest.fixture
def trash_session_factory():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, expire_on_commit=False)
    engine.dispose()


class RecordingRetrievalIndex:
    def __init__(self):
        self.deleted = []

    def delete_document(self, _db, document_id):
        self.deleted.append(document_id)
        return 1


def _owner(db):
    owner = User(
        id=str(uuid.uuid4()),
        username="owner",
        email="owner@example.com",
        hashed_password="unused",
    )
    db.add(owner)
    db.commit()
    return owner


def test_delete_forever_removes_source_file_and_index(trash_session_factory, tmp_path, monkeypatch):
    source_file = tmp_path / "source.txt"
    source_file.write_text("source content", encoding="utf-8")
    index = RecordingRetrievalIndex()
    monkeypatch.setattr(documents, "get_retrieval_index", lambda: index)

    with trash_session_factory() as db:
        owner = _owner(db)
        source = Document(
            id=str(uuid.uuid4()),
            user_id=owner.id,
            title="Source",
            source_type="txt",
            source_url=str(source_file),
            status="ready",
            deleted_at=utc_now(),
        )
        db.add(source)
        db.commit()

        trash.TrashService.delete_forever(db, owner, "source", source.id)

        assert db.get(Document, source.id) is None

    assert not source_file.exists()
    assert index.deleted == [source.id]


def test_purge_expired_trash_deletes_expired_rows_only(trash_session_factory, tmp_path, monkeypatch):
    old = utc_now() - timedelta(days=31)
    source_file = tmp_path / "expired.txt"
    source_file.write_text("expired", encoding="utf-8")
    index = RecordingRetrievalIndex()
    monkeypatch.setattr(documents, "get_retrieval_index", lambda: index)

    with trash_session_factory() as db:
        owner = _owner(db)
        active_project = Project(id="active-project", user_id=owner.id, name="Active")
        expired_project = Project(
            id="expired-project",
            user_id=owner.id,
            name="Expired",
            deleted_at=old,
        )
        expired_note = Note(
            id="expired-note",
            project_id=active_project.id,
            title="Expired note",
            content="",
            deleted_at=old,
        )
        expired_source = Document(
            id="expired-source",
            user_id=owner.id,
            title="Expired source",
            source_type="txt",
            source_url=str(source_file),
            status="ready",
            deleted_at=old,
        )
        recent_source = Document(
            id="recent-source",
            user_id=owner.id,
            title="Recent source",
            source_type="text",
            status="ready",
            deleted_at=utc_now(),
        )
        db.add_all([active_project, expired_project, expired_note, expired_source, recent_source])
        db.commit()

    assert trash.purge_expired_trash(trash_session_factory, 30) == 3

    with trash_session_factory() as db:
        assert db.get(Project, "expired-project") is None
        assert db.get(Note, "expired-note") is None
        assert db.get(Document, "expired-source") is None
        assert db.get(Document, "recent-source") is not None
    assert not source_file.exists()
    assert index.deleted == ["expired-source"]


def test_purge_skips_source_restored_after_expired_snapshot(trash_session_factory):
    old = utc_now() - timedelta(days=31)
    with trash_session_factory() as db:
        owner = _owner(db)
        source = Document(
            id="restored-source",
            user_id=owner.id,
            title="Restored source",
            source_type="txt",
            status="ready",
            deleted_at=old,
        )
        db.add(source)
        db.commit()

    calls = 0

    def restoring_session_factory():
        @contextmanager
        def session_scope():
            nonlocal calls
            calls += 1
            if calls == 2:
                with trash_session_factory() as restore_db:
                    restore_db.get(Document, "restored-source").deleted_at = None
                    restore_db.commit()
            with trash_session_factory() as db:
                yield db
        return session_scope()

    assert trash.purge_expired_trash(restoring_session_factory, 30) == 0

    with trash_session_factory() as db:
        assert db.get(Document, "restored-source").deleted_at is None

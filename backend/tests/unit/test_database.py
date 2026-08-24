"""Tests for SQLite engine pooling and connection safety."""
import pytest
from sqlalchemy.pool import StaticPool

from app.db import database
from app.db.models import Base, Document, IngestionJob


def test_file_sqlite_sessions_use_distinct_isolated_connections(tmp_path):
    """File SQLite uses its supported pool and transaction isolation.

    Args:
        tmp_path: Per-test database directory.

    Returns:
        None.
    """
    engine = database.create_database_engine(
        "sqlite:///%s" % (tmp_path / "pool.db"),
        echo=False,
    )
    try:
        assert not isinstance(engine.pool, StaticPool)
        with engine.connect() as first, engine.connect() as second:
            assert (
                first.connection.driver_connection
                is not second.connection.driver_connection
            )
            first.exec_driver_sql("CREATE TABLE isolation_probe (value INTEGER)")
            first.commit()

            first.exec_driver_sql(
                "INSERT INTO isolation_probe (value) VALUES (1)"
            )
            assert second.exec_driver_sql(
                "SELECT COUNT(*) FROM isolation_probe"
            ).scalar_one() == 0
            first.rollback()
    finally:
        engine.dispose()


def test_file_sqlite_sets_pragmas_on_every_connection(tmp_path):
    """Every pooled file connection enforces FK, timeout, and WAL policy.

    Args:
        tmp_path: Per-test database directory.

    Returns:
        None.
    """
    engine = database.create_database_engine(
        "sqlite:///%s" % (tmp_path / "pragmas.db"),
        echo=False,
    )
    try:
        with engine.connect() as first, engine.connect() as second:
            for connection in (first, second):
                assert connection.exec_driver_sql(
                    "PRAGMA foreign_keys"
                ).scalar_one() == 1
                assert connection.exec_driver_sql(
                    "PRAGMA busy_timeout"
                ).scalar_one() == 5000
                assert connection.exec_driver_sql(
                    "PRAGMA journal_mode"
                ).scalar_one().lower() == "wal"
    finally:
        engine.dispose()


@pytest.mark.parametrize("database_url", ["sqlite:///:memory:", "sqlite://"])
def test_explicit_memory_sqlite_alone_uses_static_pool(database_url):
    """The two explicit in-memory URL forms retain one shared connection.

    Args:
        database_url: SQLAlchemy in-memory SQLite URL form.

    Returns:
        None.
    """
    engine = database.create_database_engine(database_url, echo=False)
    try:
        assert isinstance(engine.pool, StaticPool)
        with engine.connect() as connection:
            assert connection.exec_driver_sql(
                "PRAGMA foreign_keys"
            ).scalar_one() == 1
            assert connection.exec_driver_sql(
                "PRAGMA busy_timeout"
            ).scalar_one() == 5000
            assert connection.exec_driver_sql(
                "PRAGMA journal_mode"
            ).scalar_one().lower() != "wal"
    finally:
        engine.dispose()


def test_foreign_key_cascade_removes_jobs_with_their_document(tmp_path):
    """A raw document delete cannot leave a durable orphan job.

    Args:
        tmp_path: Per-test database directory.

    Returns:
        None.
    """
    engine = database.create_database_engine(
        "sqlite:///%s" % (tmp_path / "cascade.db"),
        echo=False,
    )
    try:
        Base.metadata.create_all(engine)
        with engine.begin() as connection:
            connection.execute(Document.__table__.insert().values(
                id="document-1",
                title="Cascade source",
                source_type="url",
                status="queued",
            ))
            connection.execute(IngestionJob.__table__.insert().values(
                id="job-1",
                document_id="document-1",
                job_type="url",
                payload_json={"url": "https://example.com"},
                status="queued",
                attempts=0,
            ))

        with engine.begin() as connection:
            connection.execute(
                Document.__table__.delete().where(Document.id == "document-1")
            )
        with engine.connect() as connection:
            assert connection.exec_driver_sql(
                "SELECT COUNT(*) FROM ingestion_jobs"
            ).scalar_one() == 0
    finally:
        engine.dispose()

"""Pool selection contracts for application database URLs."""
from sqlalchemy.pool import StaticPool

from app.db import database


def _dbapi_connection(connection):
    """Return SQLAlchemy's underlying DBAPI connection for identity assertions."""
    return connection.connection.driver_connection


def test_in_memory_sqlite_engine_shares_one_connection():
    """In-memory SQLite needs StaticPool so every session sees the same database."""
    engine = database.create_database_engine("sqlite:///:memory:", echo=False)
    try:
        assert isinstance(engine.pool, StaticPool)
        with engine.connect() as first, engine.connect() as second:
            assert _dbapi_connection(first) is _dbapi_connection(second)
    finally:
        engine.dispose()


def test_file_sqlite_engine_uses_distinct_simultaneous_connections(tmp_path):
    """File-backed SQLite must not share one connection across worker sessions."""
    engine = database.create_database_engine(
        f"sqlite:///{tmp_path / 'runtime.db'}", echo=False
    )
    try:
        assert not isinstance(engine.pool, StaticPool)
        with engine.connect() as first, engine.connect() as second:
            assert _dbapi_connection(first) is not _dbapi_connection(second)
    finally:
        engine.dispose()

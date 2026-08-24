"""Database connection and session management."""
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool
from contextlib import contextmanager
from typing import Generator
import os
import sqlite3
from pathlib import Path

from app.config import get_settings
from app.db.models import Base

settings = get_settings()

# Ensure data directory exists
Path(os.path.dirname(settings.db_path)).mkdir(parents=True, exist_ok=True)

SQLITE_BUSY_TIMEOUT_MS = 5000


def create_database_engine(database_url: str, echo: bool) -> Engine:
    """Create an engine with pooling and connection policy for its database.

    Args:
        database_url: SQLAlchemy URL for the database.
        echo: Whether SQLAlchemy should log emitted SQL.

    Returns:
        A configured SQLAlchemy engine.
    """
    parsed_url = make_url(database_url)
    if parsed_url.get_backend_name() != "sqlite":
        return create_engine(database_url, echo=echo, pool_pre_ping=True)

    is_memory = parsed_url.database in (None, "", ":memory:")
    engine_options = {
        "connect_args": {"check_same_thread": False},
        "echo": echo,
    }
    if is_memory:
        # Separate in-memory connections each get a different database, so one
        # shared connection is required for app sessions to see the same data.
        engine_options["poolclass"] = StaticPool

    database_engine = create_engine(database_url, **engine_options)

    @event.listens_for(database_engine, "connect")
    def configure_sqlite_connection(dbapi_connection, _connection_record):
        """Apply correctness and contention policy to each pooled connection.

        Args:
            dbapi_connection: Newly opened sqlite3 connection.
            _connection_record: SQLAlchemy pool record for the connection.

        Returns:
            None.
        """
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute(
                "PRAGMA busy_timeout=%d" % SQLITE_BUSY_TIMEOUT_MS
            )
            if not is_memory:
                # WAL lets readers continue while ingestion commits chunks on
                # another connection; applying it to :memory: is unsupported.
                cursor.execute("PRAGMA journal_mode=WAL")
        finally:
            cursor.close()

        # SQLite extensions are connection-local. Loading here makes pooled,
        # reindex, and evaluation connections behave identically; failures are
        # deliberately non-fatal because RetrievalIndex exposes the named
        # brute fallback when sqlite-vec cannot be imported or loaded.
        try:
            import sqlite_vec

            dbapi_connection.enable_load_extension(True)
            sqlite_vec.load(dbapi_connection)
        except (ImportError, AttributeError, OSError, sqlite3.Error):
            pass
        finally:
            try:
                dbapi_connection.enable_load_extension(False)
            except (AttributeError, sqlite3.Error):
                pass

    return database_engine


engine = create_database_engine(settings.database_url, echo=settings.debug)

# Create session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# Columns added to a model after its table already existed somewhere, as
# (table, column, type, index name).
#
# `Base.metadata.create_all` creates missing *tables* and nothing else: a column
# added to a model later never reaches a database that already exists. Without
# this the app starts cleanly against an older file and then fails on "no such
# column" for every query that touches it. The project has no migration tool --
# alembic is in requirements but unused -- so this list is explicit and short
# rather than generated.
#
# On SQLite, ALTER TABLE can add the column but not the foreign-key constraint; a
# database created fresh gets the constraint from create_all. The column and its
# index are what queries need.
ADDED_COLUMNS = (
    ("projects", "user_id", "VARCHAR", "idx_projects_user_id"),
    ("documents", "user_id", "VARCHAR", "idx_documents_user_id"),
)


def ensure_added_columns(bind=None):
    """Add any column in ADDED_COLUMNS that this database does not have yet.

    Safe on every start: each column is checked before it is added, and an
    existing value is never touched.

    Args:
        bind: Engine to inspect and alter. Defaults to the module engine.

    Returns:
        The columns that were added, as "table.column" strings.
    """
    bind = bind or engine
    inspector = inspect(bind)
    added = []

    for table, column, column_type, index_name in ADDED_COLUMNS:
        if table not in inspector.get_table_names():
            continue
        if column in {existing["name"] for existing in inspector.get_columns(table)}:
            continue

        with bind.begin() as connection:
            connection.execute(
                text("ALTER TABLE %s ADD COLUMN %s %s" % (table, column, column_type))
            )
            connection.execute(
                text("CREATE INDEX IF NOT EXISTS %s ON %s (%s)" % (
                    index_name, table, column))
            )
        added.append("%s.%s" % (table, column))

    return added


def init_db():
    """Initialize database tables, and upgrade an older one in place."""
    Base.metadata.create_all(bind=engine)
    ensure_added_columns()
    # Import inside startup after models exist to avoid a database/service
    # import cycle. Committing the virtual-table schema here makes health
    # diagnostics accurate before the first retrieval request.
    from app.services.retrieval_index import get_retrieval_index

    with Session(bind=engine) as db:
        get_retrieval_index().ensure_schema(db, settings.emb_dimension)
        db.commit()


def get_db() -> Generator[Session, None, None]:
    """Get database session for dependency injection."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def get_db_context() -> Generator[Session, None, None]:
    """Get database session as context manager."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

"""Database connection and session management."""
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool
from contextlib import contextmanager
from typing import Generator
import os
from pathlib import Path

from app.config import get_settings
from app.db.models import Base

settings = get_settings()

# Ensure data directory exists
Path(os.path.dirname(settings.db_path)).mkdir(parents=True, exist_ok=True)

# Create engine
if "sqlite" in settings.database_url:
    # SQLite specific settings
    engine = create_engine(
        settings.database_url,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=settings.debug,
    )
else:
    # For other databases
    engine = create_engine(
        settings.database_url,
        echo=settings.debug,
        pool_pre_ping=True,
    )

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

"""An existing database gains the ownership columns instead of breaking.

`Base.metadata.create_all` creates missing tables and nothing else, so adding a
column to a model does not reach a database that already exists. The app would
start cleanly against an older file and then fail on "no such column" for every
query touching it — which is what would have happened to the database this
project was developed against.
"""
from __future__ import annotations

import sqlite3

import pytest
from sqlalchemy import create_engine, inspect

from app.db.database import ADDED_COLUMNS, ensure_added_columns
from app.db.models import Base

# The shape these two tables had before ownership existed.
OLD_SCHEMA = (
    """
    CREATE TABLE projects (
        id VARCHAR NOT NULL PRIMARY KEY,
        name VARCHAR NOT NULL,
        description TEXT,
        meta_json JSON,
        created_at DATETIME,
        updated_at DATETIME
    )
    """,
    """
    CREATE TABLE documents (
        id VARCHAR NOT NULL PRIMARY KEY,
        title VARCHAR NOT NULL,
        source_type VARCHAR NOT NULL,
        source_url TEXT,
        content TEXT,
        meta_json JSON,
        status VARCHAR,
        error_message TEXT,
        created_at DATETIME,
        updated_at DATETIME
    )
    """,
)


@pytest.fixture
def old_database(tmp_path):
    """A database file with the pre-ownership schema and one row in each table.

    Args:
        tmp_path: Per-test temporary directory.

    Returns:
        An engine bound to the file.
    """
    path = tmp_path / "old.db"
    connection = sqlite3.connect(path)
    for statement in OLD_SCHEMA:
        connection.execute(statement)
    connection.execute(
        "INSERT INTO projects (id, name) VALUES ('project-1', 'Existing work')")
    connection.execute(
        "INSERT INTO documents (id, title, source_type, status)"
        " VALUES ('document-1', 'Existing upload', 'pdf', 'ready')")
    connection.commit()
    connection.close()

    engine = create_engine("sqlite:///%s" % path)
    try:
        yield engine
    finally:
        engine.dispose()


class TestUpgrade:
    """The columns and their indexes appear, and the data survives."""

    def test_columns_are_added(self, old_database):
        added = ensure_added_columns(old_database)

        assert sorted(added) == ["documents.user_id", "projects.user_id"]
        inspector = inspect(old_database)
        for table, column, _, _ in ADDED_COLUMNS:
            if table not in inspector.get_table_names():
                continue
            names = {c["name"] for c in inspector.get_columns(table)}
            assert column in names, table

    def test_indexes_are_added(self, old_database):
        ensure_added_columns(old_database)

        inspector = inspect(old_database)
        for table, _, _, index_name in ADDED_COLUMNS:
            if table not in inspector.get_table_names() or index_name is None:
                continue
            names = {index["name"] for index in inspector.get_indexes(table)}
            assert index_name in names, table

    def test_existing_rows_survive_and_are_ownerless(self, old_database):
        ensure_added_columns(old_database)

        with old_database.connect() as connection:
            rows = list(connection.exec_driver_sql(
                "SELECT id, name, user_id FROM projects"))

        assert rows == [("project-1", "Existing work", None)]

    def test_running_twice_changes_nothing(self, old_database):
        assert ensure_added_columns(old_database)
        assert ensure_added_columns(old_database) == []

    def test_existing_database_gains_durable_jobs_idempotently(
        self,
        old_database,
    ):
        """A pre-feature file gains one queue table without changing old rows.

        Args:
            old_database: Database with pre-ownership documents and projects.

        Returns:
            None.
        """
        for _attempt in range(2):
            Base.metadata.create_all(old_database)
            ensure_added_columns(old_database)

        inspector = inspect(old_database)
        assert inspector.get_table_names().count("ingestion_jobs") == 1
        with old_database.connect() as connection:
            projects = list(connection.exec_driver_sql(
                "SELECT id, name FROM projects"
            ))
            documents = list(connection.exec_driver_sql(
                "SELECT id, title, status FROM documents"
            ))
            jobs = connection.exec_driver_sql(
                "SELECT COUNT(*) FROM ingestion_jobs"
            ).scalar_one()

        assert projects == [("project-1", "Existing work")]
        assert documents == [("document-1", "Existing upload", "ready")]
        assert jobs == 0

    def test_a_database_with_no_tables_is_left_alone(self, tmp_path):
        engine = create_engine("sqlite:///%s" % (tmp_path / "empty.db"))
        assert ensure_added_columns(engine) == []

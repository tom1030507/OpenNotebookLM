"""Focused coverage for the persistent-index maintenance command."""
from dataclasses import dataclass
from types import ModuleType, SimpleNamespace
import sys

import pytest
from sqlalchemy import inspect, text

from scripts import reindex


@dataclass
class _Status:
    """Small stand-in for the retrieval service's public status object."""

    requested_backend: str = "sqlitevec"
    active_backend: str = "sqlitevec"
    canonical_chunks: int = 4
    dense_rows: int = 3
    lexical_rows: int = 4


class _Changes:
    """Exercise the service's ``as_dict`` compatibility contract."""

    def as_dict(self):
        """Return a deliberately complete reconciliation report."""
        return {
            "canonical_chunks": 4,
            "dense_rows": 3,
            "lexical_rows": 4,
            "dense_missing": 1,
            "dense_stale": 0,
            "lexical_missing": 0,
            "lexical_stale": 0,
            "added": 1,
            "updated": 0,
            "removed": 0,
            "dimension_mismatch": 0,
            "dry_run": True,
            "active_backend": "sqlitevec",
            "fallback_reason": None,
        }


def test_normalize_index_report_accepts_service_value_shapes():
    """Tooling must not force the core service to return a plain dict."""
    assert reindex.normalize_index_report({"dense_rows": 2}) == {"dense_rows": 2}
    assert reindex.normalize_index_report(_Status())["canonical_chunks"] == 4
    assert reindex.normalize_index_report(_Changes())["dense_missing"] == 1


def test_build_session_uses_app_schema_and_sqlite_connection_policy(tmp_path):
    """A custom maintenance database behaves like the running application."""
    db, engine = reindex.build_session("sqlite:///" + (tmp_path / "index.db").as_posix())
    try:
        assert "chunks" in inspect(engine).get_table_names()
        assert db.execute(text("PRAGMA foreign_keys")).scalar_one() == 1
        assert db.execute(text("PRAGMA busy_timeout")).scalar_one() >= 5000
    finally:
        db.close()
        engine.dispose()


def test_dry_run_reports_index_changes_without_loading_ingestion_or_writing(
    tmp_path, monkeypatch, capsys
):
    """Dry-run audits canonical/index drift and leaves reconciliation read-only."""
    database_url = "sqlite:///" + (tmp_path / "dry-run.db").as_posix()
    db, engine = reindex.build_session(database_url)
    db.close()
    engine.dispose()
    database_path = tmp_path / "dry-run.db"
    before_bytes = database_path.read_bytes()
    before_mtime = database_path.stat().st_mtime_ns

    calls = []

    class FakeIndex:
        """Retrieval index spy used by the command."""

        def status(self, db):
            """Return current index shape."""
            calls.append(("status", None))
            return _Status()

        def backfill(self, db, dry_run=False, document_ids=None):
            """Reject any attempt to turn the dry-run into a write."""
            assert dry_run is True
            calls.append(("backfill", document_ids))
            return _Changes()

    fake_module = ModuleType("app.services.retrieval_index")
    fake_module.get_retrieval_index = lambda: FakeIndex()
    monkeypatch.setitem(sys.modules, "app.services.retrieval_index", fake_module)

    import app.config

    monkeypatch.setattr(
        app.config,
        "get_settings",
        lambda: SimpleNamespace(database_url=database_url),
    )
    # If the command imports the ingestion pipeline, this sentinel makes the
    # regression fail before a model can be loaded.
    monkeypatch.setitem(sys.modules, "app.services.documents", None)

    assert reindex.main(["--dry-run"]) == 0

    output = capsys.readouterr().out
    assert "canonical chunks" in output
    assert "dense missing" in output
    assert "dimension mismatch" in output
    assert calls == [("status", None), ("backfill", None)]
    # A byte-for-byte and metadata match covers both schema and row data. SQLite
    # may create transient -wal/-shm coordination files while reading a database
    # whose persistent journal mode is WAL; those do not alter the database.
    assert database_path.read_bytes() == before_bytes
    assert database_path.stat().st_mtime_ns == before_mtime


def test_read_only_session_rejects_sqlite_writes(tmp_path):
    """The dry-run guarantee is enforced by SQLite, not caller discipline."""
    database_url = "sqlite:///" + (tmp_path / "read only.db").as_posix()
    db, engine = reindex.build_session(database_url)
    db.close()
    engine.dispose()

    db, engine = reindex.build_session(
        database_url,
        initialize=False,
        read_only=True,
    )
    try:
        from sqlalchemy import text
        from sqlalchemy.exc import OperationalError

        try:
            db.execute(text("CREATE TABLE forbidden_write (id INTEGER)"))
        except OperationalError as exc:
            assert "readonly" in str(exc).lower()
        else:
            raise AssertionError("SQLite accepted a write through a read-only engine")
    finally:
        db.rollback()
        db.close()
        engine.dispose()


def test_index_only_is_repeatable_and_does_not_load_ingestion(
    tmp_path, monkeypatch, capsys
):
    """A second reconciliation exposes zero changes without loading the model."""
    database_url = "sqlite:///" + (tmp_path / "repeat.db").as_posix()
    repair_calls = 0
    audit_calls = 0

    class FakeIndex:
        """Stateful stand-in for an idempotent retrieval index."""

        def status(self, db):
            """Return a stable, healthy shape."""
            return _Status(canonical_chunks=0, dense_rows=0, lexical_rows=0)

        def backfill(self, db, dry_run=False, document_ids=None):
            """Return one change once, then the required fixed point."""
            nonlocal audit_calls, repair_calls
            if dry_run:
                audit_calls += 1
                return {
                    "dense_missing": 0,
                    "dense_stale": 0,
                    "lexical_missing": 0,
                    "lexical_stale": 0,
                    "dimension_mismatch": 0,
                    "added": 0,
                    "updated": 0,
                    "removed": 0,
                }
            repair_calls += 1
            return {
                "canonical_chunks": 0,
                "dense_rows": 0,
                "lexical_rows": 0,
                "added": 1 if repair_calls == 1 else 0,
                "updated": 0,
                "removed": 0,
                "dimension_mismatch": 0,
            }

    instance = FakeIndex()
    fake_module = ModuleType("app.services.retrieval_index")
    fake_module.get_retrieval_index = lambda: instance
    monkeypatch.setitem(sys.modules, "app.services.retrieval_index", fake_module)

    import app.config

    monkeypatch.setattr(
        app.config,
        "get_settings",
        lambda: SimpleNamespace(database_url=database_url),
    )
    monkeypatch.setitem(sys.modules, "app.services.documents", None)

    assert reindex.main(["--index-only"]) == 0
    first_output = capsys.readouterr().out
    assert "added                  1" in first_output

    assert reindex.main(["--index-only"]) == 0
    second_output = capsys.readouterr().out
    assert "added                  0" in second_output
    assert repair_calls == 2
    assert audit_calls == 2


def test_backfill_commits_then_verifies_with_a_fresh_session(tmp_path):
    """Repair is durable before the second, read-only reconciliation runs."""
    database_url = "sqlite:///" + (tmp_path / "transaction.db").as_posix()
    db, engine = reindex.build_session(database_url)
    db.execute(text("CREATE TABLE index_marker (id INTEGER PRIMARY KEY)"))
    db.commit()

    class TransactionalIndex:
        """Use a real SQL row to expose commit/session mistakes."""

        def backfill(self, session, dry_run=False, document_ids=None):
            """Insert once, then report the resulting fixed point."""
            present = session.execute(text("SELECT count(*) FROM index_marker")).scalar_one()
            if dry_run:
                return {
                    "dense_missing": 0 if present else 1,
                    "dense_stale": 0,
                    "lexical_missing": 0,
                    "lexical_stale": 0,
                    "dimension_mismatch": 0,
                    "added": 0 if present else 1,
                    "updated": 0,
                    "removed": 0,
                }
            session.execute(text("INSERT INTO index_marker (id) VALUES (1)"))
            return {"added": 1, "updated": 0, "removed": 0}

        def status(self, session):
            """Report shape through the verification session."""
            present = session.execute(text("SELECT count(*) FROM index_marker")).scalar_one()
            return _Status(canonical_chunks=present, dense_rows=present, lexical_rows=present)

    try:
        changes, audit, status = reindex.apply_and_verify_backfill(
            TransactionalIndex(), db, engine, document_ids=None
        )
        assert changes["added"] == 1
        assert audit["added"] == 0
        assert not reindex.unresolved_index_drift(audit)
        assert status["dense_rows"] == 1

        verification, verification_engine = reindex.build_session(database_url)
        try:
            assert verification.execute(
                text("SELECT count(*) FROM index_marker")
            ).scalar_one() == 1
        finally:
            verification.close()
            verification_engine.dispose()
    finally:
        db.close()
        engine.dispose()


def test_backfill_rolls_back_when_repair_raises(tmp_path):
    """A partial index repair never leaks through an exception."""
    database_url = "sqlite:///" + (tmp_path / "rollback.db").as_posix()
    db, engine = reindex.build_session(database_url)
    db.execute(text("CREATE TABLE index_marker (id INTEGER PRIMARY KEY)"))
    db.commit()

    class FailingIndex:
        """Write one row and fail before the repair can be acknowledged."""

        def backfill(self, session, dry_run=False, document_ids=None):
            """Simulate a mid-reconciliation failure."""
            session.execute(text("INSERT INTO index_marker (id) VALUES (1)"))
            raise RuntimeError("repair failed")

    try:
        with pytest.raises(RuntimeError, match="repair failed"):
            reindex.apply_and_verify_backfill(FailingIndex(), db, engine, None)

        assert db.execute(text("SELECT count(*) FROM index_marker")).scalar_one() == 0
    finally:
        db.close()
        engine.dispose()


def test_fresh_audit_must_be_a_complete_fixed_point():
    """Post-commit missing, mismatch, or orphan work is still unhealthy."""
    assert reindex.unresolved_index_drift({
        "added": 0,
        "updated": 0,
        "removed": 0,
        "dense_missing": 0,
        "dense_stale": 0,
        "lexical_missing": 0,
        "lexical_stale": 0,
        "dimension_mismatch": 0,
    }) == {}
    assert reindex.unresolved_index_drift({
        "added": 0,
        "dimension_mismatch": 4,
    }) == {"dimension_mismatch": 4}
    assert reindex.unresolved_index_drift({
        "removed": 2,
    }) == {"removed": 2}


def test_cli_requires_ids_rejects_negative_limit_and_honors_zero(
    tmp_path, monkeypatch, capsys
):
    """Selection flags cannot silently widen a maintenance run."""
    with pytest.raises(SystemExit):
        reindex.main(["--ids"])
    with pytest.raises(SystemExit):
        reindex.main(["--limit", "-1"])

    database_url = "sqlite:///" + (tmp_path / "limit.db").as_posix()
    db, engine = reindex.build_session(database_url)
    try:
        from app.db.models import Document

        db.add(Document(
            id="document-1",
            title="selected unless limit is zero",
            source_type="url",
            source_url="https://example.test",
            status="ready",
            meta_json={},
        ))
        db.commit()
    finally:
        db.close()
        engine.dispose()

    class EmptyIndex:
        """Read-only index spy for argument behavior."""

        def status(self, db):
            """Return an empty shape."""
            return _Status(canonical_chunks=0, dense_rows=0, lexical_rows=0)

        def backfill(self, db, dry_run=False, document_ids=None):
            """Return a clean audit."""
            return {
                "dense_missing": 0,
                "dense_stale": 0,
                "lexical_missing": 0,
                "lexical_stale": 0,
                "dimension_mismatch": 0,
            }

    fake_module = ModuleType("app.services.retrieval_index")
    fake_module.get_retrieval_index = EmptyIndex
    monkeypatch.setitem(sys.modules, "app.services.retrieval_index", fake_module)

    import app.config

    monkeypatch.setattr(
        app.config,
        "get_settings",
        lambda: SimpleNamespace(database_url=database_url),
    )

    assert reindex.main(["--dry-run", "--limit", "0"]) == 0
    assert "0 document(s) selected" in capsys.readouterr().out

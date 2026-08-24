"""Focused coverage for the persistent-index maintenance command."""
from dataclasses import dataclass
from types import ModuleType, SimpleNamespace
import sys

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
    calls = 0

    class FakeIndex:
        """Stateful stand-in for an idempotent retrieval index."""

        def status(self, db):
            """Return a stable, healthy shape."""
            return _Status(canonical_chunks=0, dense_rows=0, lexical_rows=0)

        def backfill(self, db, dry_run=False, document_ids=None):
            """Return one change once, then the required fixed point."""
            nonlocal calls
            assert dry_run is False
            calls += 1
            return {
                "canonical_chunks": 0,
                "dense_rows": 0,
                "lexical_rows": 0,
                "added": 1 if calls == 1 else 0,
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
    assert calls == 2

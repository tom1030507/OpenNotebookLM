"""Re-extract, re-chunk and re-embed documents that are already in the database.

Needed whenever extraction, chunking or the embedding model changes: stored
chunks were produced by the old code and do not improve on their own. The
alternative the README used to describe -- delete every embedding and re-upload
each source by hand -- also throws away the projects and conversations attached
to those documents.

This rebuilds in place. Document rows keep their ids, so project membership,
conversations and citations survive; only `content`, `chunks` and `embeddings` are
replaced, through the same code path an upload takes.

Run inside the backend container, from /app:

    python -m scripts.reindex --dry-run
    python -m scripts.reindex --source-type url
    python -m scripts.reindex --index-only

The dry-run also audits the persistent dense and lexical indexes against
canonical chunks and embeddings without importing the ML pipeline. Index-only
mode repairs those candidate indexes without re-reading sources.

Back up the database first. A source that cannot be re-read -- a URL that now
404s, a PDF whose upload is gone -- is marked `error` and keeps its old chunks,
so it stops being retrievable until it is re-added.
"""
import argparse
import asyncio
from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from sqlalchemy import create_engine, event, func
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import sessionmaker


INDEX_REPORT_FIELDS = (
    "requested_backend",
    "active_backend",
    "fallback_reason",
    "dimension",
    "canonical_chunks",
    "dense_rows",
    "lexical_rows",
    "dense_missing",
    "dense_stale",
    "lexical_missing",
    "lexical_stale",
    "added",
    "updated",
    "removed",
    "dimension_mismatch",
)

UNRESOLVED_INDEX_FIELDS = (
    "dense_missing",
    "dense_stale",
    "lexical_missing",
    "lexical_stale",
    "dimension_mismatch",
    "added",
    "updated",
    "removed",
)


def non_negative_int(value: str) -> int:
    """Parse a command-line integer that may be zero but not negative.

    Args:
        value: Raw argparse value.

    Returns:
        Parsed non-negative integer.

    Raises:
        argparse.ArgumentTypeError: If the value is not a non-negative integer.
    """
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be zero or greater")
    return parsed


def normalize_index_report(value: Any) -> Dict[str, Any]:
    """Turn a retrieval-index result into a serializable mapping.

    The service exposes typed status/change values. Accepting its documented
    conversion methods as well as dataclasses keeps this operational script
    independent of the concrete value class.

    Args:
        value: Mapping or typed retrieval-index report.

    Returns:
        A shallow dictionary containing the report fields.

    Raises:
        TypeError: If the service returns an unsupported value.
    """
    if isinstance(value, Mapping):
        return dict(value)
    for method_name in ("as_dict", "to_dict"):
        method = getattr(value, method_name, None)
        if callable(method):
            converted = method()
            if not isinstance(converted, Mapping):
                raise TypeError("%s() must return a mapping" % method_name)
            return dict(converted)
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    raise TypeError("unsupported retrieval-index report: %r" % (type(value),))


def print_index_report(label: str, report: Dict[str, Any]) -> None:
    """Print index shape and reconciliation counters in a stable order.

    Args:
        label: Human-readable heading.
        report: Normalized retrieval-index report.

    Returns:
        None.
    """
    print(label)
    seen = set()
    for key in INDEX_REPORT_FIELDS:
        if key not in report:
            continue
        seen.add(key)
        value = report[key]
        print("  %-22s %s" % (key.replace("_", " "), "-" if value is None else value))
    for key in sorted(set(report) - seen - {"dry_run"}):
        value = report[key]
        print("  %-22s %s" % (key.replace("_", " "), "-" if value is None else value))


def unresolved_index_drift(report: Dict[str, Any]) -> Dict[str, int]:
    """Return repairable-or-actionable drift still present after reconciliation.

    This function is only for the fresh post-commit dry audit. The applied
    change report may legitimately contain non-zero counters; the second audit
    must be a complete fixed point, including zero orphan/add/update work.

    Args:
        report: Normalized dry-run reconciliation report.

    Returns:
        Non-zero unresolved counters keyed by field name.
    """
    unresolved = {}
    for field in UNRESOLVED_INDEX_FIELDS:
        value = int(report.get(field, 0) or 0)
        if value:
            unresolved[field] = value
    return unresolved


def apply_and_verify_backfill(
    retrieval_index,
    db,
    engine: Engine,
    document_ids: Optional[List[str]],
):
    """Commit index repair and verify its fixed point through a new session.

    Args:
        retrieval_index: RetrievalIndex service.
        db: Session used to apply the repair.
        engine: Engine used to open an independent verification session.
        document_ids: Optional document scope.

    Returns:
        A tuple of applied changes, post-commit dry audit, and fresh status.

    Raises:
        Exception: Re-raises repair or verification errors after rolling back
            any uncommitted repair work.
    """
    try:
        changes = normalize_index_report(retrieval_index.backfill(
            db,
            dry_run=False,
            document_ids=document_ids,
        ))
        db.commit()
    except Exception:
        db.rollback()
        raise

    verification_db = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=engine,
    )()
    try:
        audit = normalize_index_report(retrieval_index.backfill(
            verification_db,
            dry_run=True,
            document_ids=document_ids,
        ))
        status = normalize_index_report(retrieval_index.status(verification_db))
        return changes, audit, status
    except Exception:
        verification_db.rollback()
        raise
    finally:
        verification_db.close()


def create_read_only_sqlite_engine(database_url: str) -> Engine:
    """Open SQLite without changing its journal mode, schema, or row data.

    The application's normal connection hook enables WAL, which is correct for
    the running service but can modify a database header. A dry-run instead uses
    SQLite's URI ``mode=ro`` and applies only connection-local read policies.
    The retrieval index may still load sqlite-vec on this connection; loading an
    extension does not modify the database.

    Args:
        database_url: File-backed SQLite SQLAlchemy URL.

    Returns:
        A read-only SQLAlchemy engine.

    Raises:
        ValueError: If the URL is not a file-backed SQLite database.
    """
    parsed_url = make_url(database_url)
    if parsed_url.get_backend_name() != "sqlite":
        raise ValueError("read-only SQLite engine requires a sqlite URL")
    if parsed_url.database in (None, "", ":memory:"):
        raise ValueError("read-only maintenance requires a file-backed database")

    database_path = Path(parsed_url.database).resolve().as_posix()
    uri_path = quote(database_path, safe="/:")
    engine = create_engine(
        "sqlite:///file:%s?mode=ro&uri=true" % uri_path,
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def configure_read_only_connection(dbapi_connection, _connection_record):
        """Apply safe per-connection correctness policy without enabling WAL.

        Args:
            dbapi_connection: Newly opened sqlite3 connection.
            _connection_record: SQLAlchemy pool record for the connection.

        Returns:
            None.
        """
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=5000")
        finally:
            cursor.close()

    return engine


def build_session(
    database_url: str,
    initialize: bool = True,
    read_only: bool = False,
):
    """Open a session against the application's own database.

    Args:
        database_url: SQLAlchemy URL.
        initialize: Whether to create the canonical application schema. A
            dry-run against the production database sets this false so the
            command itself cannot create missing tables.
        read_only: Whether SQLite must enforce URI-level read-only access.

    Returns:
        A tuple of (session, engine).
    """
    from app.db.database import create_database_engine, ensure_added_columns
    from app.db.models import Base

    if initialize and read_only:
        raise ValueError("a read-only session cannot initialize schema")

    parsed_url = make_url(database_url)
    if read_only and parsed_url.get_backend_name() == "sqlite":
        engine = create_read_only_sqlite_engine(database_url)
    else:
        engine = create_database_engine(database_url, echo=False)
    if initialize:
        Base.metadata.create_all(bind=engine)
        ensure_added_columns(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)(), engine


def chunk_stats(db) -> dict:
    """Summarise the shape of the whole index.

    Args:
        db: Database session.

    Returns:
        Counts and the worst-case chunk length.
    """
    from app.db.models import Chunk

    total = db.query(func.count(Chunk.id)).scalar() or 0
    with_heading = db.query(func.count(Chunk.id)).filter(
        Chunk.heading_path.isnot(None), Chunk.heading_path != ""
    ).scalar() or 0
    longest = db.query(func.max(func.length(Chunk.text))).scalar() or 0
    return {"chunks": total, "with_heading_path": with_heading, "longest": longest}


def reindex_document(service, db, document) -> str:
    """Re-run ingestion for one document.

    Args:
        service: A DocumentService.
        db: Database session.
        document: The Document row to rebuild.

    Returns:
        The status the document ended up in.
    """
    from app.db.models import Document

    if document.source_type == "url":
        asyncio.run(service._process_url_async(db, document.id, document.source_url))
    elif document.source_type == "pdf":
        asyncio.run(service._process_pdf_async(db, document.id, document.source_url))
    elif document.source_type == "youtube":
        asyncio.run(service._process_youtube_async(db, document.id, document.source_url))
    else:
        return "skipped"

    refreshed = db.query(Document).filter(Document.id == document.id).first()
    return refreshed.status if refreshed else "missing"


def main(argv: Optional[List[str]] = None) -> int:
    """Entry point.

    Args:
        argv: Optional argument list, for testing.

    Returns:
        Process exit code; non-zero if any document ended in error.
    """
    parser = argparse.ArgumentParser(description="Rebuild content, chunks and embeddings.")
    parser.add_argument("--source-type", default="all",
                        choices=["all", "url", "pdf", "youtube"],
                        help="restrict to one kind of source")
    parser.add_argument("--status", default="ready",
                        help="only rebuild documents currently in this status; "
                             "'any' for all of them")
    parser.add_argument("--ids", nargs="+", default=None, help="specific document ids")
    parser.add_argument("--limit", type=non_negative_int, default=None,
                        help="stop after this many; zero selects none")
    parser.add_argument("--dry-run", action="store_true",
                        help="audit canonical/index drift without loading the model or writing")
    parser.add_argument("--index-only", action="store_true",
                        help="reconcile dense/lexical indexes from stored chunks and embeddings; "
                             "do not re-extract or re-embed sources")
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    from app.config import get_settings
    from app.db.models import Chunk, Document

    settings = get_settings()
    db, engine = build_session(
        settings.database_url,
        initialize=not args.dry_run,
        read_only=args.dry_run,
    )

    try:
        query = db.query(Document)
        if args.source_type != "all":
            query = query.filter(Document.source_type == args.source_type)
        if args.status != "any":
            query = query.filter(Document.status == args.status)
        if args.ids:
            query = query.filter(Document.id.in_(args.ids))
        documents = query.order_by(Document.source_type, Document.created_at).all()
        if args.limit is not None:
            documents = documents[:args.limit]

        before = chunk_stats(db)
        print("canonical before: %d chunks, %d with a heading path, longest %d chars" % (
            before["chunks"], before["with_heading_path"], before["longest"]))
        print("%d document(s) selected" % len(documents))

        # Importing this service does not load the embedding model. Its dry-run
        # contract only compares canonical rows with the two candidate indexes;
        # that is why `--dry-run` remains safe and cheap even on a model change.
        from app.services.retrieval_index import get_retrieval_index

        retrieval_index = get_retrieval_index()
        status_before = normalize_index_report(retrieval_index.status(db))
        print_index_report("retrieval index before:", status_before)

        scoped_ids = list(args.ids) if args.ids else None

        if args.dry_run:
            for document in documents:
                count = db.query(func.count(Chunk.id)).filter(
                    Chunk.document_id == document.id).scalar() or 0
                print("  would rebuild %-8s %-40s (%d chunks)" % (
                    document.source_type, (document.title or "")[:38], count))
            changes = normalize_index_report(retrieval_index.backfill(
                db,
                dry_run=True,
                document_ids=scoped_ids,
            ))
            print_index_report("retrieval index changes (dry-run):", changes)
            return 0

        outcomes = {}
        if not args.index_only and documents:
            # Loading the model here rather than at import time keeps dry-run
            # and index-only reconciliation usable on low-memory hosts.
            from app.services.documents import DocumentService
            service = DocumentService()

            for index, document in enumerate(documents, start=1):
                was = db.query(func.count(Chunk.id)).filter(
                    Chunk.document_id == document.id).scalar() or 0
                status = reindex_document(service, db, document)
                now = db.query(func.count(Chunk.id)).filter(
                    Chunk.document_id == document.id).scalar() or 0
                outcomes[status] = outcomes.get(status, 0) + 1
                print("  [%d/%d] %-8s %-38s %-8s chunks %d -> %d%s" % (
                    index, len(documents), document.source_type,
                    (document.title or "")[:36], status, was, now,
                    "" if status == "ready" else "  <-- check this one"), flush=True)

        changes, audit, status_after = apply_and_verify_backfill(
            retrieval_index,
            db,
            engine,
            scoped_ids,
        )
        print_index_report("retrieval index changes:", changes)
        print_index_report("retrieval index verification (dry-run):", audit)

        after = chunk_stats(db)
        print("canonical after:  %d chunks, %d with a heading path, longest %d chars" % (
            after["chunks"], after["with_heading_path"], after["longest"]))
        print_index_report("retrieval index after:", status_after)
        if outcomes:
            print("outcomes: %s" % ", ".join(
                "%s=%d" % item for item in sorted(outcomes.items())
            ))
        unresolved = unresolved_index_drift(audit)
        if unresolved:
            print("unresolved index drift: %s" % ", ".join(
                "%s=%d" % item for item in sorted(unresolved.items())
            ))
        return 1 if outcomes.get("error") or unresolved else 0
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())

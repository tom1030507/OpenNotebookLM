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

Back up the database first. A source that cannot be re-read -- a URL that now
404s, a PDF whose upload is gone -- is marked `error` and keeps its old chunks,
so it stops being retrievable until it is re-added.
"""
import argparse
import asyncio
import sys
from typing import List, Optional

from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


def build_session(database_url: str):
    """Open a session against the application's own database.

    Args:
        database_url: SQLAlchemy URL.

    Returns:
        A tuple of (session, engine).
    """
    engine = create_engine(
        database_url,
        connect_args={"check_same_thread": False} if database_url.startswith("sqlite") else {},
        poolclass=StaticPool if database_url.startswith("sqlite") else None,
    )
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
    parser.add_argument("--ids", nargs="*", default=None, help="specific document ids")
    parser.add_argument("--limit", type=int, default=None, help="stop after this many")
    parser.add_argument("--dry-run", action="store_true",
                        help="list what would be rebuilt and exit")
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    from app.config import get_settings
    from app.db.models import Chunk, Document

    settings = get_settings()
    db, engine = build_session(settings.database_url)

    try:
        query = db.query(Document)
        if args.source_type != "all":
            query = query.filter(Document.source_type == args.source_type)
        if args.status != "any":
            query = query.filter(Document.status == args.status)
        if args.ids:
            query = query.filter(Document.id.in_(args.ids))
        documents = query.order_by(Document.source_type, Document.created_at).all()
        if args.limit:
            documents = documents[:args.limit]

        before = chunk_stats(db)
        print("index before: %d chunks, %d with a heading path, longest %d chars" % (
            before["chunks"], before["with_heading_path"], before["longest"]))
        print("%d document(s) selected" % len(documents))

        if args.dry_run:
            for document in documents:
                count = db.query(func.count(Chunk.id)).filter(
                    Chunk.document_id == document.id).scalar() or 0
                print("  would rebuild %-8s %-40s (%d chunks)" % (
                    document.source_type, (document.title or "")[:38], count))
            return 0

        # Loading the model here rather than at import time keeps --dry-run cheap.
        from app.services.documents import DocumentService
        service = DocumentService()

        outcomes = {}
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

        after = chunk_stats(db)
        print("index after:  %d chunks, %d with a heading path, longest %d chars" % (
            after["chunks"], after["with_heading_path"], after["longest"]))
        print("outcomes: %s" % ", ".join("%s=%d" % item for item in sorted(outcomes.items())))
        return 1 if outcomes.get("error") else 0
    finally:
        db.close()
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())

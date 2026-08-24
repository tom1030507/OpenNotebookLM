"""Persistent dense and lexical candidate indexes."""
from __future__ import annotations

import hashlib
import importlib
import math
import pickle
import re
import sqlite3
import struct
from collections import Counter
from dataclasses import asdict, dataclass
from typing import Any, Iterable, Optional, Sequence

from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import Chunk, Document, Embedding, RetrievalIndexEntry
from app.services import retrieval


VECTOR_TABLE = "retrieval_index_vec"
FTS_TABLE = "retrieval_index_fts"
SCOPE_BATCH_SIZE = 800
VECTOR_DIMENSION_PATTERN = re.compile(
    r"embedding\s+FLOAT\[(\d+)\]",
    flags=re.IGNORECASE,
)


class RetrievalIndexError(RuntimeError):
    """Base error for an unavailable or inconsistent retrieval index."""


class RetrievalIndexDimensionError(RetrievalIndexError):
    """Raised when a query vector does not fit the persistent vec0 table."""


class _VectorExtensionUnavailable(RetrievalIndexError):
    """Internal signal allowing only extension-load failures to use brute mode."""


@dataclass(frozen=True)
class IndexedChunk:
    """Canonical chunk data written to both retrieval indexes."""

    chunk_id: str
    document_id: str
    text: str
    vector: Sequence[float]
    model_name: Optional[str] = None
    heading_path: Optional[str] = None
    searchable: bool = False


@dataclass(frozen=True)
class RetrievalCandidate:
    """One bounded candidate returned by an index search."""

    chunk_id: str
    document_id: str
    score: float


@dataclass(frozen=True)
class IndexStatus:
    """Availability and row counts for the retrieval indexes."""

    requested_backend: str = "sqlitevec+fts5"
    configured_backend: str = "sqlitevec+fts5"
    active_backend: str = "uninitialized"
    dense_backend: str = "uninitialized"
    lexical_backend: str = "uninitialized"
    dense_available: bool = False
    lexical_available: bool = False
    sqlitevec_version: Optional[str] = None
    fallback_reason: Optional[str] = None
    dimension: Optional[int] = None
    canonical_chunks: int = 0
    dense_rows: int = 0
    lexical_rows: int = 0

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-safe representation.

        Returns:
            Status fields keyed by their public snake-case names.
        """
        return asdict(self)


@dataclass(frozen=True)
class IndexChanges:
    """Observed or applied reconciliation changes."""

    canonical_chunks: int = 0
    dense_rows: int = 0
    lexical_rows: int = 0
    dense_missing: int = 0
    dense_stale: int = 0
    lexical_missing: int = 0
    lexical_stale: int = 0
    added: int = 0
    updated: int = 0
    removed: int = 0
    dimension_mismatch: int = 0
    dry_run: bool = False
    active_backend: str = "uninitialized"
    fallback_reason: Optional[str] = None

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-safe representation.

        Returns:
            Change fields keyed by their public snake-case names.
        """
        return asdict(self)


class RetrievalIndex:
    """Own sqlite-vec, FTS5, and explicit fallback retrieval paths."""

    def __init__(self, scope_batch_size: int = SCOPE_BATCH_SIZE) -> None:
        """Initialize per-process backend diagnostics.

        Args:
            scope_batch_size: Maximum document ids bound in one candidate query.

        Returns:
            None.
        """
        if scope_batch_size < 1:
            raise ValueError("scope_batch_size must be positive")
        self.scope_batch_size = scope_batch_size
        self._dense_backend = "uninitialized"
        self._lexical_backend = "uninitialized"
        self._dense_available = False
        self._lexical_available = False
        self._fallback_reasons: list[str] = []
        self._sqlitevec_version: Optional[str] = None
        self._dimension: Optional[int] = None
        self._configured_dense_backend = get_settings().emb_backend.lower()

    def ensure_schema(self, db: Session, dimension: Optional[int] = None) -> IndexStatus:
        """Ensure persistent index storage exists.

        Args:
            db: Database session.
            dimension: Optional dense-vector dimension.

        Returns:
            Current index status.
        """
        if dimension is not None and dimension < 1:
            raise ValueError("dimension must be positive")

        # This is a new table, so create_all handles normal app startup. The
        # explicit check also makes the service safe for scripts that construct
        # a session without calling init_db first.
        RetrievalIndexEntry.__table__.create(bind=db.connection(), checkfirst=True)

        if self._configured_dense_backend != "sqlitevec":
            self._dense_backend = "brute"
            self._dense_available = True
            self._dimension = dimension or self._dimension
            self._sqlitevec_version = None
            self._remember_fallback(
                "configured dense backend '%s' is unsupported by the persistent index"
                % self._configured_dense_backend
            )
        else:
            try:
                self._load_vector_extension(db)
            except _VectorExtensionUnavailable as error:
                self._dense_backend = "brute"
                self._dense_available = True
                self._dimension = dimension or self._dimension
                self._sqlitevec_version = None
                self._remember_fallback(str(error))
            else:
                existing_dimension = self._vector_dimension(db)
                if (
                    dimension is not None
                    and existing_dimension is not None
                    and existing_dimension != dimension
                ):
                    raise RetrievalIndexDimensionError(
                        "sqlite-vec dimension is %d but received %d; run the "
                        "retrieval reindex command to rebuild the index"
                        % (existing_dimension, dimension)
                    )
                if existing_dimension is None and dimension is not None:
                    db.execute(
                        text(
                            "CREATE VIRTUAL TABLE %s USING vec0("
                            "entry_id INTEGER PRIMARY KEY, "
                            "embedding FLOAT[%d] distance_metric=cosine, "
                            "document_id TEXT PARTITION KEY, "
                            "searchable INTEGER)" % (VECTOR_TABLE, dimension)
                        )
                    )
                    existing_dimension = dimension
                self._dimension = existing_dimension
                self._dense_backend = "sqlitevec"
                self._dense_available = existing_dimension is not None

        try:
            db.execute(
                text(
                    "CREATE VIRTUAL TABLE IF NOT EXISTS %s USING fts5("
                    "lexical_text, content='retrieval_index_entries', "
                    "content_rowid='id', tokenize='unicode61')" % FTS_TABLE
                )
            )
        except OperationalError as error:
            if "no such module: fts5" not in str(error).lower():
                raise
            self._lexical_backend = "python-bm25"
            self._lexical_available = True
            self._remember_fallback("FTS5 unavailable (OperationalError)")
        else:
            self._lexical_backend = "fts5"
            self._lexical_available = True

        return self.status(db)

    def upsert_chunks(self, db: Session, chunks: Sequence[IndexedChunk]) -> IndexChanges:
        """Insert or update canonical chunks in both indexes.

        Args:
            db: Database session.
            chunks: Canonical chunk records.

        Returns:
            Applied index changes.
        """
        chunks = list(chunks)
        if not chunks:
            current = self.status(db)
            return IndexChanges(
                active_backend=current.active_backend,
                fallback_reason=current.fallback_reason,
            )

        dimensions = {len(chunk.vector) for chunk in chunks}
        if 0 in dimensions:
            raise ValueError("indexed vectors must not be empty")
        if len(dimensions) != 1:
            raise ValueError("one upsert batch must use one vector dimension")
        dimension = dimensions.pop()
        self.ensure_schema(db, dimension)

        chunk_ids = [chunk.chunk_id for chunk in chunks]
        if len(set(chunk_ids)) != len(chunk_ids):
            raise ValueError("one upsert batch cannot repeat a chunk id")

        existing: dict[str, RetrievalIndexEntry] = {}
        for batch in self._batches(chunk_ids):
            existing.update(
                {
                    entry.chunk_id: entry
                    for entry in db.query(RetrievalIndexEntry)
                    .filter(RetrievalIndexEntry.chunk_id.in_(batch))
                    .all()
                }
            )

        added = 0
        updated = 0
        for chunk in chunks:
            vector = self._serialize_vector(chunk.vector)
            lexical_text = self._lexical_text(chunk)
            searchable = bool(chunk.searchable)
            source_hash = self._source_hash(chunk, vector, lexical_text)
            dense_hash = self._dense_source_hash(chunk, vector)
            lexical_hash = self._lexical_source_hash(chunk, lexical_text)
            entry = existing.get(chunk.chunk_id)
            old_lexical_text = entry.lexical_text if entry is not None else None
            is_new = entry is None
            changed = is_new

            if is_new:
                entry = RetrievalIndexEntry(
                    chunk_id=chunk.chunk_id,
                    document_id=chunk.document_id,
                    vector=vector,
                    model_name=chunk.model_name,
                    dimension=dimension,
                    source_hash=source_hash,
                    dense_hash=None,
                    lexical_hash=None,
                    lexical_text=lexical_text,
                    searchable=searchable,
                )
                db.add(entry)
                db.flush()
                added += 1
            else:
                changed = any(
                    (
                        entry.document_id != chunk.document_id,
                        entry.vector != vector,
                        entry.model_name != chunk.model_name,
                        entry.dimension != dimension,
                        entry.source_hash != source_hash,
                        entry.lexical_text != lexical_text,
                        entry.searchable != searchable,
                    )
                )
                entry.document_id = chunk.document_id
                entry.vector = vector
                entry.model_name = chunk.model_name
                entry.dimension = dimension
                entry.source_hash = source_hash
                entry.lexical_text = lexical_text
                entry.searchable = searchable
                db.flush()
                updated += int(changed)

            if self._dense_backend == "sqlitevec":
                if entry.dense_hash != dense_hash:
                    self._replace_vector_row(db, entry)
                    entry.dense_hash = dense_hash

            if self._lexical_backend == "fts5":
                if entry.lexical_hash != lexical_hash and entry.lexical_hash is not None:
                    self._delete_fts_row(db, entry.id, old_lexical_text or "")
                if entry.lexical_hash != lexical_hash:
                    self._insert_fts_row(db, entry.id, entry.lexical_text)
                    entry.lexical_hash = lexical_hash

            db.flush()

        current = self.status(db)
        return IndexChanges(
            canonical_chunks=len(chunks),
            dense_rows=current.dense_rows,
            lexical_rows=current.lexical_rows,
            added=added,
            updated=updated,
            active_backend=current.active_backend,
            fallback_reason=current.fallback_reason,
        )

    def delete_document(self, db: Session, document_id: str) -> int:
        """Delete every index row for a document.

        Args:
            db: Database session.
            document_id: Document whose rows must be removed.

        Returns:
            Number of mapping rows removed.
        """
        entries = (
            db.query(RetrievalIndexEntry)
            .filter(RetrievalIndexEntry.document_id == document_id)
            .all()
        )
        if not entries:
            return 0
        for entry in entries:
            if self._table_exists(db, VECTOR_TABLE):
                try:
                    self._load_vector_extension(db)
                except _VectorExtensionUnavailable:
                    # The stable mapping is authoritative. Removing it makes an
                    # orphan virtual row unreachable through every search join;
                    # a later backfill clears the orphan after the extension is
                    # available again.
                    pass
                else:
                    db.execute(
                        text("DELETE FROM %s WHERE entry_id = :entry_id" % VECTOR_TABLE),
                        {"entry_id": entry.id},
                    )
            if self._table_exists(db, FTS_TABLE):
                self._delete_fts_row(db, entry.id, entry.lexical_text)
            db.delete(entry)
        db.flush()
        return len(entries)

    def dense_search(
        self,
        db: Session,
        query_vector: Sequence[float],
        document_ids: Optional[Sequence[str]] = None,
        top_k: int = 5,
        threshold: float = 0,
    ) -> list[RetrievalCandidate]:
        """Return dense candidates from the active backend.

        Args:
            db: Database session.
            query_vector: Query vector.
            document_ids: Optional document scope; an empty scope matches none.
            top_k: Maximum candidates.
            threshold: Minimum cosine similarity.

        Returns:
            Candidates ordered by descending similarity.
        """
        if top_k <= 0 or len(query_vector) == 0:
            return []
        if document_ids is not None and not document_ids:
            return []

        query_bytes = self._serialize_vector(query_vector)
        self.ensure_schema(db, len(query_vector))
        if self._dense_backend == "brute":
            return self._brute_dense_search(
                db,
                query_vector,
                document_ids=document_ids,
                top_k=top_k,
                threshold=threshold,
            )

        scopes: Iterable[Optional[Sequence[str]]]
        if document_ids is None:
            scopes = [None]
        else:
            scopes = self._batches(list(dict.fromkeys(document_ids)))

        candidates: dict[str, RetrievalCandidate] = {}
        for scope in scopes:
            parameters: dict[str, Any] = {
                "embedding": query_bytes,
                "candidate_k": top_k,
            }
            scope_clause = ""
            if scope is not None:
                placeholders = []
                for index, document_id in enumerate(scope):
                    key = "document_%d" % index
                    placeholders.append(":" + key)
                    parameters[key] = document_id
                scope_clause = " AND v.document_id IN (%s)" % ", ".join(placeholders)

            rows = db.execute(
                text(
                    "SELECT e.chunk_id, e.document_id, v.distance "
                    "FROM %s AS v "
                    "JOIN retrieval_index_entries AS e ON e.id = v.entry_id "
                    "WHERE v.embedding MATCH :embedding "
                    "AND k = :candidate_k AND v.searchable = 1%s "
                    "ORDER BY v.distance, e.chunk_id" % (VECTOR_TABLE, scope_clause)
                ),
                parameters,
            ).all()
            for chunk_id, document_id, distance in rows:
                score = 1.0 - float(distance)
                if score < threshold:
                    continue
                candidate = RetrievalCandidate(chunk_id, document_id, score)
                previous = candidates.get(chunk_id)
                if previous is None or candidate.score > previous.score:
                    candidates[chunk_id] = candidate

        return sorted(
            candidates.values(),
            key=lambda item: (-item.score, item.chunk_id),
        )[:top_k]

    def lexical_search(
        self,
        db: Session,
        query: str,
        document_ids: Optional[Sequence[str]] = None,
        top_k: int = 5,
    ) -> list[RetrievalCandidate]:
        """Return persistent BM25 candidates.

        Args:
            db: Database session.
            query: User query.
            document_ids: Optional document scope; an empty scope matches none.
            top_k: Maximum candidates.

        Returns:
            Candidates ordered by descending lexical score.
        """
        if top_k <= 0:
            return []
        if document_ids is not None and not document_ids:
            return []
        query_tokens = retrieval.tokenize(query)
        if not query_tokens:
            return []

        self.ensure_schema(db)
        if self._lexical_backend == "python-bm25":
            return self._python_bm25_search(
                db,
                query_tokens,
                document_ids=document_ids,
                top_k=top_k,
            )

        match_query = " OR ".join(
            '"%s"' % token.replace('"', '""')
            for token in dict.fromkeys(query_tokens)
        )
        scopes: Iterable[Optional[Sequence[str]]]
        if document_ids is None:
            scopes = [None]
        else:
            scopes = self._batches(list(dict.fromkeys(document_ids)))

        candidates: dict[str, RetrievalCandidate] = {}
        for scope in scopes:
            parameters: dict[str, Any] = {
                "match_query": match_query,
                "candidate_k": top_k,
            }
            scope_clause = ""
            if scope is not None:
                placeholders = []
                for index, document_id in enumerate(scope):
                    key = "document_%d" % index
                    placeholders.append(":" + key)
                    parameters[key] = document_id
                scope_clause = " AND e.document_id IN (%s)" % ", ".join(placeholders)

            rows = db.execute(
                text(
                    "SELECT e.chunk_id, e.document_id, -bm25(%s) AS score "
                    "FROM %s "
                    "JOIN retrieval_index_entries AS e ON e.id = %s.rowid "
                    "WHERE %s MATCH :match_query AND e.searchable = 1%s "
                    "ORDER BY bm25(%s), e.chunk_id LIMIT :candidate_k"
                    % (
                        FTS_TABLE,
                        FTS_TABLE,
                        FTS_TABLE,
                        FTS_TABLE,
                        scope_clause,
                        FTS_TABLE,
                    )
                ),
                parameters,
            ).all()
            for chunk_id, document_id, score in rows:
                candidate = RetrievalCandidate(chunk_id, document_id, float(score))
                previous = candidates.get(chunk_id)
                if previous is None or candidate.score > previous.score:
                    candidates[chunk_id] = candidate

        return sorted(
            candidates.values(),
            key=lambda item: (-item.score, item.chunk_id),
        )[:top_k]

    def hydrate(self, db: Session, candidate_ids: Sequence[str]) -> list[dict[str, Any]]:
        """Fetch bounded candidate metadata in one joined query.

        Args:
            db: Database session.
            candidate_ids: Chunk ids in desired result order.

        Returns:
            Candidate payloads in the requested order.
        """
        ordered_ids = list(dict.fromkeys(candidate_ids))
        if not ordered_ids:
            return []
        if len(ordered_ids) > self.scope_batch_size:
            raise ValueError(
                "candidate hydration is bounded to %d ids" % self.scope_batch_size
            )

        rows = (
            db.query(Chunk, Document.title)
            .join(Document, Document.id == Chunk.document_id)
            .filter(Chunk.id.in_(ordered_ids))
            .all()
        )
        payloads = {
            chunk.id: {
                "chunk_id": chunk.id,
                "document_id": chunk.document_id,
                "document_title": document_title or "Unknown",
                "text": chunk.text,
                "metadata": {
                    "page_num": chunk.page_num,
                    "timestamp": chunk.ts_start,
                    "section": (
                        chunk.meta_json.get("section") if chunk.meta_json else None
                    ),
                    "heading_path": chunk.heading_path,
                },
            }
            for chunk, document_title in rows
        }
        return [payloads[chunk_id] for chunk_id in ordered_ids if chunk_id in payloads]

    def backfill(
        self,
        db: Session,
        dry_run: bool = False,
        document_ids: Optional[Sequence[str]] = None,
    ) -> IndexChanges:
        """Reconcile indexes with canonical chunk embeddings.

        Args:
            db: Database session.
            dry_run: Report differences without writing.
            document_ids: Optional document scope.

        Returns:
            Observed or applied reconciliation changes.
        """
        if document_ids is not None and not document_ids:
            current = self.status(db)
            return IndexChanges(
                dry_run=dry_run,
                active_backend=current.active_backend,
                fallback_reason=current.fallback_reason,
            )

        canonical = self._canonical_chunks(db, document_ids)
        canonical_by_id = {chunk.chunk_id: chunk for chunk in canonical}
        mapping_exists = self._table_exists(db, "retrieval_index_entries")
        entries: dict[str, RetrievalIndexEntry] = {}
        if mapping_exists:
            entry_query = db.query(RetrievalIndexEntry)
            if document_ids is not None:
                scoped_entries = []
                for scope in self._batches(list(dict.fromkeys(document_ids))):
                    scoped_entries.extend(
                        entry_query.filter(
                            RetrievalIndexEntry.document_id.in_(scope)
                        ).all()
                    )
                entries = {entry.chunk_id: entry for entry in scoped_entries}
            else:
                entries = {entry.chunk_id: entry for entry in entry_query.all()}

        vector_dimension = (
            self._vector_dimension(db) if self._table_exists(db, VECTOR_TABLE) else None
        )
        vector_ids: set[int] = set()
        if vector_dimension is not None:
            try:
                self._load_vector_extension(db)
            except _VectorExtensionUnavailable as error:
                self._dense_backend = "brute"
                self._dense_available = True
                self._remember_fallback(str(error))
            else:
                vector_ids = {
                    int(value)
                    for value in db.execute(
                        text("SELECT entry_id FROM %s" % VECTOR_TABLE)
                    ).scalars()
                }

        added = 0
        updated = 0
        dense_missing = 0
        dense_stale = 0
        lexical_missing = 0
        lexical_stale = 0
        dimension_mismatch = 0
        for chunk in canonical:
            entry = entries.get(chunk.chunk_id)
            vector = self._serialize_vector(chunk.vector)
            lexical_text = self._lexical_text(chunk)
            source_hash = self._source_hash(chunk, vector, lexical_text)
            dense_hash = self._dense_source_hash(chunk, vector)
            lexical_hash = self._lexical_source_hash(chunk, lexical_text)
            if entry is None:
                added += 1
                if chunk.searchable:
                    dense_missing += 1
                    if lexical_text:
                        lexical_missing += 1
            else:
                updated += int(entry.source_hash != source_hash)
                if chunk.searchable:
                    if entry.dense_hash is None or (
                        vector_ids and entry.id not in vector_ids
                    ):
                        dense_missing += 1
                    elif entry.dense_hash != dense_hash:
                        dense_stale += 1
                    if lexical_text:
                        if entry.lexical_hash is None or not self._fts_row_indexed(
                            db, entry.id, lexical_text
                        ):
                            lexical_missing += 1
                        elif entry.lexical_hash != lexical_hash:
                            lexical_stale += 1
                elif entry.searchable:
                    dense_stale += 1
                    lexical_stale += int(bool(entry.lexical_text))
            if (
                chunk.searchable
                and vector_dimension is not None
                and len(chunk.vector) != vector_dimension
            ):
                dimension_mismatch += 1

        removed_ids = set(entries) - set(canonical_by_id)
        current = self.status(db)
        changes = IndexChanges(
            canonical_chunks=sum(chunk.searchable for chunk in canonical),
            dense_rows=current.dense_rows,
            lexical_rows=current.lexical_rows,
            dense_missing=dense_missing,
            dense_stale=dense_stale,
            lexical_missing=lexical_missing,
            lexical_stale=lexical_stale,
            added=added,
            updated=updated,
            removed=len(removed_ids),
            dimension_mismatch=dimension_mismatch,
            dry_run=dry_run,
            active_backend=current.active_backend,
            fallback_reason=current.fallback_reason,
        )
        if dry_run:
            return changes

        dimensions = Counter(len(chunk.vector) for chunk in canonical)
        if len(dimensions) > 1:
            raise RetrievalIndexDimensionError(
                "canonical embeddings contain mixed dimensions; regenerate them before reindexing"
            )
        target_dimension = next(iter(dimensions), None)
        if (
            target_dimension is not None
            and vector_dimension is not None
            and target_dimension != vector_dimension
        ):
            self._load_vector_extension(db)
            db.execute(text("DROP TABLE %s" % VECTOR_TABLE))
            if mapping_exists:
                db.query(RetrievalIndexEntry).update(
                    {RetrievalIndexEntry.dense_hash: None},
                    synchronize_session=False,
                )
            self._dimension = None

        self.ensure_schema(db, target_dimension)
        for chunk_id in removed_ids:
            self._delete_entry(db, entries[chunk_id])
        if canonical:
            self.upsert_chunks(db, canonical)
        return changes

    def status(self, db: Optional[Session] = None) -> IndexStatus:
        """Return availability, backend, and row-count diagnostics.

        Args:
            db: Optional database session.

        Returns:
            Current index status.
        """
        canonical_chunks = 0
        dense_rows = 0
        lexical_rows = 0
        dimension = self._dimension
        if db is not None:
            canonical_chunks = (
                db.query(Embedding)
                .join(Chunk, Chunk.id == Embedding.chunk_id)
                .join(Document, Document.id == Chunk.document_id)
                .filter(Document.status == "ready")
                .count()
            )
            if self._table_exists(db, VECTOR_TABLE):
                try:
                    self._load_vector_extension(db)
                except _VectorExtensionUnavailable as error:
                    self._dense_backend = "brute"
                    self._dense_available = True
                    self._remember_fallback(str(error))
                else:
                    dimension = self._vector_dimension(db)
                    self._dimension = dimension
                    self._dense_backend = "sqlitevec"
                    self._dense_available = dimension is not None
                    dense_rows = int(
                        db.execute(
                            text(
                                "SELECT COUNT(*) FROM %s WHERE searchable = 1"
                                % VECTOR_TABLE
                            )
                        ).scalar_one()
                    )
            elif self._dense_backend == "uninitialized":
                self._dense_available = False

            if self._table_exists(db, FTS_TABLE):
                lexical_rows = int(
                    db.execute(
                        text(
                            "SELECT COUNT(*) FROM %s AS f "
                            "JOIN retrieval_index_entries AS e ON e.id = f.rowid "
                            "WHERE e.searchable = 1" % FTS_TABLE
                        )
                    ).scalar_one()
                )
                self._lexical_backend = "fts5"
                self._lexical_available = True

        active_backend = "%s+%s" % (self._dense_backend, self._lexical_backend)
        configured_backend = "%s+fts5" % self._configured_dense_backend
        return IndexStatus(
            requested_backend=configured_backend,
            configured_backend=configured_backend,
            active_backend=active_backend,
            dense_backend=self._dense_backend,
            lexical_backend=self._lexical_backend,
            dense_available=self._dense_available,
            lexical_available=self._lexical_available,
            sqlitevec_version=self._sqlitevec_version,
            fallback_reason="; ".join(self._fallback_reasons) or None,
            dimension=dimension,
            canonical_chunks=canonical_chunks,
            dense_rows=dense_rows,
            lexical_rows=lexical_rows,
        )

    def _batches(self, values: Sequence[str]):
        """Yield bounded slices from a sequence.

        Args:
            values: Values to batch.

        Returns:
            Iterator of bounded list slices.
        """
        for start in range(0, len(values), self.scope_batch_size):
            yield list(values[start:start + self.scope_batch_size])

    def _load_vector_extension(self, db: Session) -> None:
        """Load sqlite-vec on the session's concrete DB-API connection.

        Args:
            db: Database session.

        Returns:
            None.

        Raises:
            _VectorExtensionUnavailable: if import or extension load is unavailable.
        """
        if db.get_bind().dialect.name != "sqlite":
            raise _VectorExtensionUnavailable(
                "sqlite-vec unavailable (database dialect is not SQLite)"
            )
        try:
            sqlite_vec = importlib.import_module("sqlite_vec")
        except ImportError as error:
            raise _VectorExtensionUnavailable(
                "sqlite-vec extension unavailable (ImportError)"
            ) from error

        raw_connection = db.connection().connection.driver_connection
        try:
            raw_connection.enable_load_extension(True)
            sqlite_vec.load(raw_connection)
        except (AttributeError, OSError, sqlite3.OperationalError) as error:
            raise _VectorExtensionUnavailable(
                "sqlite-vec extension unavailable (%s)" % type(error).__name__
            ) from error
        finally:
            try:
                raw_connection.enable_load_extension(False)
            except (AttributeError, sqlite3.OperationalError):
                pass

        self._sqlitevec_version = str(
            db.execute(text("SELECT vec_version()"), {}).scalar_one()
        )

    @staticmethod
    def _table_exists(db: Session, table_name: str) -> bool:
        """Return whether a SQLite table exists without creating it.

        Args:
            db: Database session.
            table_name: Exact internal table name.

        Returns:
            True when sqlite_master contains the table.
        """
        return db.execute(
            text("SELECT 1 FROM sqlite_master WHERE name = :name LIMIT 1"),
            {"name": table_name},
        ).first() is not None

    def _vector_dimension(self, db: Session) -> Optional[int]:
        """Read the vec0 dimension from its persisted CREATE statement.

        Args:
            db: Database session.

        Returns:
            Stored dimension, or None when the virtual table does not exist.
        """
        row = db.execute(
            text("SELECT sql FROM sqlite_master WHERE name = :name"),
            {"name": VECTOR_TABLE},
        ).first()
        if row is None or not row[0]:
            return None
        match = VECTOR_DIMENSION_PATTERN.search(row[0])
        if match is None:
            raise RetrievalIndexError(
                "cannot determine sqlite-vec dimension; run the retrieval reindex command"
            )
        return int(match.group(1))

    @staticmethod
    def _serialize_vector(vector: Sequence[float]) -> bytes:
        """Serialize finite floats in sqlite-vec's raw float32 format.

        Args:
            vector: Numeric vector.

        Returns:
            Native-endian float32 bytes.
        """
        values = [float(value) for value in vector]
        if not values:
            raise ValueError("vectors must not be empty")
        if not all(math.isfinite(value) for value in values):
            raise ValueError("vectors must contain only finite values")
        return struct.pack("%sf" % len(values), *values)

    @staticmethod
    def _deserialize_vector(value: bytes, dimension: int) -> tuple[float, ...]:
        """Decode raw float32 fallback storage.

        Args:
            value: Raw vector bytes.
            dimension: Expected element count.

        Returns:
            Vector values.
        """
        expected = struct.calcsize("%sf" % dimension)
        if len(value) != expected:
            raise RetrievalIndexDimensionError(
                "stored fallback vector has an invalid size; run the retrieval reindex command"
            )
        return struct.unpack("%sf" % dimension, value)

    @staticmethod
    def _lexical_text(chunk: IndexedChunk) -> str:
        """Pretokenize heading and body with the shared mixed-language tokenizer.

        Args:
            chunk: Canonical chunk.

        Returns:
            Space-separated lexical tokens.
        """
        source = " ".join(part for part in (chunk.heading_path, chunk.text) if part)
        return " ".join(retrieval.tokenize(source))

    @staticmethod
    def _source_hash(chunk: IndexedChunk, vector: bytes, lexical_text: str) -> str:
        """Hash every canonical value that changes an index row.

        Args:
            chunk: Canonical chunk.
            vector: Serialized float32 vector.
            lexical_text: Pretokenized lexical text.

        Returns:
            Stable SHA-256 hex digest.
        """
        digest = hashlib.sha256()
        for value in (
            chunk.chunk_id,
            chunk.document_id,
            chunk.model_name or "",
            lexical_text,
            "1" if chunk.searchable else "0",
        ):
            encoded = value.encode("utf-8")
            digest.update(struct.pack("!I", len(encoded)))
            digest.update(encoded)
        digest.update(vector)
        return digest.hexdigest()

    @staticmethod
    def _dense_source_hash(chunk: IndexedChunk, vector: bytes) -> str:
        """Hash values represented in the vec0 row.

        Args:
            chunk: Canonical chunk.
            vector: Serialized float32 vector.

        Returns:
            Stable SHA-256 hex digest.
        """
        digest = hashlib.sha256()
        digest.update(chunk.chunk_id.encode("utf-8"))
        digest.update(b"\0")
        digest.update(chunk.document_id.encode("utf-8"))
        digest.update(b"\0")
        digest.update(b"1" if chunk.searchable else b"0")
        digest.update(vector)
        return digest.hexdigest()

    @staticmethod
    def _lexical_source_hash(chunk: IndexedChunk, lexical_text: str) -> str:
        """Hash values represented in the persistent FTS row.

        Args:
            chunk: Canonical chunk.
            lexical_text: Pretokenized lexical text.

        Returns:
            Stable SHA-256 hex digest.
        """
        digest = hashlib.sha256()
        for value in (
            chunk.chunk_id,
            chunk.document_id,
            lexical_text,
            "1" if chunk.searchable else "0",
        ):
            digest.update(value.encode("utf-8"))
            digest.update(b"\0")
        return digest.hexdigest()

    @staticmethod
    def _replace_vector_row(db: Session, entry: RetrievalIndexEntry) -> None:
        """Replace one vec0 row without unsupported UPSERT/REPLACE syntax.

        Args:
            db: Database session.
            entry: Flushed stable mapping entry.

        Returns:
            None.
        """
        db.execute(
            text("DELETE FROM %s WHERE entry_id = :entry_id" % VECTOR_TABLE),
            {"entry_id": entry.id},
        )
        db.execute(
            text(
                "INSERT INTO %s(entry_id, embedding, document_id, searchable) "
                "VALUES (:entry_id, :embedding, :document_id, :searchable)"
                % VECTOR_TABLE
            ),
            {
                "entry_id": entry.id,
                "embedding": entry.vector,
                "document_id": entry.document_id,
                "searchable": int(entry.searchable),
            },
        )

    @staticmethod
    def _insert_fts_row(db: Session, entry_id: int, lexical_text: str) -> None:
        """Insert one external-content FTS row.

        Args:
            db: Database session.
            entry_id: Stable mapping row id.
            lexical_text: Pretokenized searchable text.

        Returns:
            None.
        """
        db.execute(
            text(
                "INSERT INTO %s(rowid, lexical_text) "
                "VALUES (:entry_id, :lexical_text)" % FTS_TABLE
            ),
            {"entry_id": entry_id, "lexical_text": lexical_text},
        )

    @staticmethod
    def _delete_fts_row(db: Session, entry_id: int, lexical_text: str) -> None:
        """Delete one external-content FTS row with its previous tokens.

        Args:
            db: Database session.
            entry_id: Stable mapping row id.
            lexical_text: Tokens currently stored in the FTS index.

        Returns:
            None.
        """
        db.execute(
            text(
                "INSERT INTO %s(%s, rowid, lexical_text) "
                "VALUES ('delete', :entry_id, :lexical_text)"
                % (FTS_TABLE, FTS_TABLE)
            ),
            {"entry_id": entry_id, "lexical_text": lexical_text},
        )

    def _brute_dense_search(
        self,
        db: Session,
        query_vector: Sequence[float],
        document_ids: Optional[Sequence[str]],
        top_k: int,
        threshold: float,
    ) -> list[RetrievalCandidate]:
        """Run the explicitly disclosed dense fallback over raw float32 rows.

        Args:
            db: Database session.
            query_vector: Query vector.
            document_ids: Optional document scope.
            top_k: Maximum candidates.
            threshold: Minimum cosine similarity.

        Returns:
            Ranked fallback candidates.
        """
        query_values = tuple(float(value) for value in query_vector)
        query_norm = math.sqrt(sum(value * value for value in query_values))
        if query_norm == 0:
            return []

        scopes: Iterable[Optional[Sequence[str]]]
        if document_ids is None:
            scopes = [None]
        else:
            scopes = self._batches(list(dict.fromkeys(document_ids)))

        candidates: dict[str, RetrievalCandidate] = {}
        for scope in scopes:
            row_query = db.query(RetrievalIndexEntry).filter(
                RetrievalIndexEntry.searchable.is_(True),
                RetrievalIndexEntry.dimension == len(query_vector),
            )
            if scope is not None:
                row_query = row_query.filter(
                    RetrievalIndexEntry.document_id.in_(scope)
                )
            for entry in row_query.all():
                stored = self._deserialize_vector(entry.vector, entry.dimension)
                stored_norm = math.sqrt(sum(value * value for value in stored))
                if stored_norm == 0:
                    continue
                score = sum(
                    left * right for left, right in zip(query_values, stored)
                ) / (query_norm * stored_norm)
                if score >= threshold:
                    candidates[entry.chunk_id] = RetrievalCandidate(
                        entry.chunk_id,
                        entry.document_id,
                        float(score),
                    )
        return sorted(
            candidates.values(), key=lambda item: (-item.score, item.chunk_id)
        )[:top_k]

    def _python_bm25_search(
        self,
        db: Session,
        query_tokens: Sequence[str],
        document_ids: Optional[Sequence[str]],
        top_k: int,
    ) -> list[RetrievalCandidate]:
        """Run the explicitly disclosed lexical fallback over mapping rows.

        Args:
            db: Database session.
            query_tokens: Pretokenized query.
            document_ids: Optional document scope.
            top_k: Maximum candidates.

        Returns:
            Ranked fallback candidates.
        """
        scopes: Iterable[Optional[Sequence[str]]]
        if document_ids is None:
            scopes = [None]
        else:
            scopes = self._batches(list(dict.fromkeys(document_ids)))

        rows: dict[str, RetrievalIndexEntry] = {}
        for scope in scopes:
            query = db.query(RetrievalIndexEntry).filter(
                RetrievalIndexEntry.searchable.is_(True)
            )
            if scope is not None:
                query = query.filter(RetrievalIndexEntry.document_id.in_(scope))
            rows.update({entry.chunk_id: entry for entry in query.all()})

        entries = sorted(rows.values(), key=lambda entry: entry.chunk_id)
        scores = retrieval.bm25_scores(
            query_tokens,
            [entry.lexical_text.split() for entry in entries],
        )
        candidates = [
            RetrievalCandidate(entry.chunk_id, entry.document_id, float(score))
            for entry, score in zip(entries, scores)
            if score > 0
        ]
        return sorted(candidates, key=lambda item: (-item.score, item.chunk_id))[:top_k]

    def _canonical_chunks(
        self,
        db: Session,
        document_ids: Optional[Sequence[str]],
    ) -> list[IndexedChunk]:
        """Load canonical embedding rows without importing the model service.

        Args:
            db: Database session.
            document_ids: Optional document scope.

        Returns:
            Canonical chunks, with ready state translated to publication state.
        """
        scopes: Iterable[Optional[Sequence[str]]]
        if document_ids is None:
            scopes = [None]
        else:
            scopes = self._batches(list(dict.fromkeys(document_ids)))

        canonical: dict[str, IndexedChunk] = {}
        for scope in scopes:
            query = (
                db.query(Chunk, Embedding, Document.status)
                .join(Embedding, Embedding.chunk_id == Chunk.id)
                .join(Document, Document.id == Chunk.document_id)
            )
            if scope is not None:
                query = query.filter(Chunk.document_id.in_(scope))
            for chunk, embedding, document_status in query.order_by(Chunk.id).all():
                vector = self._embedding_values(embedding)
                if vector is None:
                    continue
                canonical[chunk.id] = IndexedChunk(
                    chunk_id=chunk.id,
                    document_id=chunk.document_id,
                    text=chunk.text,
                    vector=vector,
                    model_name=embedding.model_name,
                    heading_path=chunk.heading_path,
                    searchable=document_status == "ready",
                )
        return [canonical[chunk_id] for chunk_id in sorted(canonical)]

    @staticmethod
    def _embedding_values(embedding: Embedding) -> Optional[Sequence[float]]:
        """Prefer JSON vectors and decode legacy pickle only when necessary.

        Args:
            embedding: Canonical embedding row.

        Returns:
            Numeric vector, or None when neither representation exists.
        """
        if embedding.vector_json is not None:
            return embedding.vector_json
        if embedding.vector is None:
            return None
        value = pickle.loads(embedding.vector)
        if hasattr(value, "tolist"):
            value = value.tolist()
        return value

    def _fts_row_indexed(
        self,
        db: Session,
        entry_id: int,
        lexical_text: str,
    ) -> bool:
        """Check actual FTS postings rather than external-content visibility.

        Args:
            db: Database session.
            entry_id: Stable mapping row id.
            lexical_text: Pretokenized text expected in the index.

        Returns:
            True when at least one expected token has a posting for this row.
        """
        if not lexical_text or not self._table_exists(db, FTS_TABLE):
            return False
        token = lexical_text.split()[0]
        match_query = '"%s"' % token.replace('"', '""')
        return db.execute(
            text(
                "SELECT 1 FROM %s WHERE %s MATCH :match_query "
                "AND rowid = :entry_id LIMIT 1" % (FTS_TABLE, FTS_TABLE)
            ),
            {"match_query": match_query, "entry_id": entry_id},
        ).first() is not None

    def _delete_entry(self, db: Session, entry: RetrievalIndexEntry) -> None:
        """Delete one mapping and any reachable virtual rows atomically.

        Args:
            db: Database session.
            entry: Mapping entry to remove.

        Returns:
            None.
        """
        if self._table_exists(db, VECTOR_TABLE):
            try:
                self._load_vector_extension(db)
            except _VectorExtensionUnavailable:
                pass
            else:
                db.execute(
                    text("DELETE FROM %s WHERE entry_id = :entry_id" % VECTOR_TABLE),
                    {"entry_id": entry.id},
                )
        if self._table_exists(db, FTS_TABLE) and entry.lexical_hash is not None:
            self._delete_fts_row(db, entry.id, entry.lexical_text)
        db.delete(entry)
        db.flush()

    def _remember_fallback(self, reason: str) -> None:
        """Record one safe, deduplicated fallback reason.

        Args:
            reason: Sanitized fallback summary.

        Returns:
            None.
        """
        if reason not in self._fallback_reasons:
            self._fallback_reasons.append(reason)


_retrieval_index = RetrievalIndex()


def get_retrieval_index() -> RetrievalIndex:
    """Return the process-wide retrieval index service.

    Returns:
        Shared retrieval index service.
    """
    return _retrieval_index

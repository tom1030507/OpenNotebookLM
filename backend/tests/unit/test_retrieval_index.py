"""Persistent dense and lexical retrieval index coverage."""
import pytest
import numpy as np
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import Base, Chunk, Document, Embedding
from app.services import retrieval_index as retrieval_index_module
from app.services.retrieval_index import (
    IndexedChunk,
    IndexStatus,
    RetrievalIndex,
    RetrievalIndexDimensionError,
    RetrievalIndexError,
)


@pytest.fixture
def db():
    """Create one shared in-memory SQLite session with canonical chunks."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add_all(
        [
            Document(id="doc-a", title="A", source_type="url", status="ready"),
            Document(id="doc-b", title="B", source_type="url", status="ready"),
            Document(
                id="doc-processing",
                title="Processing",
                source_type="url",
                status="processing",
            ),
            Chunk(id="a-best", document_id="doc-a", text="alpha"),
            Chunk(id="a-second", document_id="doc-a", text="alpha beta"),
            Chunk(id="b-best", document_id="doc-b", text="beta"),
            Chunk(
                id="processing-best",
                document_id="doc-processing",
                text="not published",
            ),
        ]
    )
    session.commit()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _indexed_chunks() -> list[IndexedChunk]:
    """Return literal vectors with a hand-checkable cosine order."""
    return [
        IndexedChunk("a-best", "doc-a", "alpha", [1.0, 0.0], searchable=True),
        IndexedChunk(
            "a-second",
            "doc-a",
            "alpha beta",
            [0.8, 0.2],
            searchable=True,
        ),
        IndexedChunk("b-best", "doc-b", "beta", [0.0, 1.0], searchable=True),
    ]


def test_status_discloses_each_active_backend_and_extension_version() -> None:
    """Health consumers can distinguish one fallback from a healthy peer index."""
    payload = IndexStatus(
        configured_backend="sqlitevec+fts5",
        active_backend="brute+fts5",
        dense_backend="brute",
        lexical_backend="fts5",
        sqlitevec_version=None,
        fallback_reason="sqlite-vec extension unavailable (ImportError)",
    ).as_dict()

    assert payload["configured_backend"] == "sqlitevec+fts5"
    assert payload["dense_backend"] == "brute"
    assert payload["lexical_backend"] == "fts5"
    assert payload["sqlitevec_version"] is None


def test_dense_search_applies_document_scope_before_database_top_k(db) -> None:
    """An out-of-scope nearest vector cannot consume a scoped result slot."""
    index = RetrievalIndex()
    index.upsert_chunks(db, _indexed_chunks())

    results = index.dense_search(
        db,
        [1.0, 0.0],
        document_ids=["doc-b"],
        top_k=1,
    )

    assert [(item.chunk_id, item.document_id) for item in results] == [
        ("b-best", "doc-b")
    ]


def test_dense_search_treats_an_empty_scope_as_no_documents(db) -> None:
    """An explicit empty ownership scope must never become an unscoped search."""
    index = RetrievalIndex()
    index.upsert_chunks(db, _indexed_chunks())

    assert index.dense_search(db, [1.0, 0.0], document_ids=[]) == []


def test_dense_search_converts_cosine_distance_and_applies_threshold(db) -> None:
    """A cosine threshold excludes a weaker vector before returning top-k."""
    index = RetrievalIndex()
    index.upsert_chunks(db, _indexed_chunks())

    results = index.dense_search(db, [1.0, 0.0], top_k=3, threshold=0.99)

    assert [(item.chunk_id, item.score) for item in results] == [
        ("a-best", pytest.approx(1.0))
    ]


def test_dense_search_batches_a_large_document_scope(db) -> None:
    """More scope ids than one SQL parameter batch still produce global top-k."""
    index = RetrievalIndex()
    index.upsert_chunks(db, _indexed_chunks())
    scope = [f"missing-{number}" for number in range(1001)] + ["doc-a", "doc-b"]

    results = index.dense_search(db, [1.0, 0.0], document_ids=scope, top_k=2)

    assert [item.chunk_id for item in results] == ["a-best", "a-second"]


def test_dense_search_does_not_publish_a_processing_document(db) -> None:
    """Committed embedding batches stay hidden until their document is ready."""
    index = RetrievalIndex()
    index.upsert_chunks(
        db,
        [
            IndexedChunk(
                "processing-best",
                "doc-processing",
                "not published",
                [1.0, 0.0],
            )
        ],
    )

    assert index.dense_search(db, [1.0, 0.0], top_k=1) == []


def test_dense_search_publishes_only_an_explicitly_searchable_payload(db) -> None:
    """The final ready transaction controls publication without a status reread."""
    index = RetrievalIndex()
    hidden = IndexedChunk("a-best", "doc-a", "alpha", [1.0, 0.0])
    index.upsert_chunks(db, [hidden])
    assert index.dense_search(db, [1.0, 0.0], top_k=1) == []

    published = IndexedChunk(
        "a-best",
        "doc-a",
        "alpha",
        [1.0, 0.0],
        searchable=True,
    )
    index.upsert_chunks(db, [published])

    assert [item.chunk_id for item in index.dense_search(db, [1.0, 0.0])] == [
        "a-best"
    ]


def test_lexical_search_ranks_english_and_quotes_special_query_syntax(db) -> None:
    """FTS BM25 ranks literal tokens without exposing MATCH operators."""
    index = RetrievalIndex()
    index.upsert_chunks(db, _indexed_chunks())

    results = index.lexical_search(db, 'alpha" OR * -', top_k=2)

    assert [item.chunk_id for item in results] == ["a-best", "a-second"]
    assert all(item.score > 0 for item in results)


def test_lexical_search_uses_shared_cjk_bigrams_and_heading_text(db) -> None:
    """Pretokenized CJK headings remain searchable through persistent FTS."""
    db.add(Chunk(id="cjk", document_id="doc-a", text="路由架構"))
    db.flush()
    index = RetrievalIndex()
    index.upsert_chunks(
        db,
        [
            IndexedChunk(
                "cjk",
                "doc-a",
                "路由架構",
                [0.5, 0.5],
                heading_path="專家混合",
                searchable=True,
            )
        ],
    )

    results = index.lexical_search(db, "什麼是專家混合？")

    assert [item.chunk_id for item in results] == ["cjk"]


def test_lexical_update_removes_old_terms_and_keeps_stable_mapping_id(db) -> None:
    """Updating one chunk cannot leave stale FTS terms or replace its stable id."""
    index = RetrievalIndex()
    index.upsert_chunks(db, [_indexed_chunks()[0]])
    before_id = db.execute(
        text("SELECT id FROM retrieval_index_entries WHERE chunk_id = 'a-best'")
    ).scalar_one()

    index.upsert_chunks(
        db,
        [IndexedChunk("a-best", "doc-a", "gamma", [1.0, 0.0], searchable=True)],
    )
    after_id = db.execute(
        text("SELECT id FROM retrieval_index_entries WHERE chunk_id = 'a-best'")
    ).scalar_one()

    assert index.lexical_search(db, "alpha") == []
    assert [item.chunk_id for item in index.lexical_search(db, "gamma")] == ["a-best"]
    assert after_id == before_id


def test_delete_document_removes_dense_lexical_and_mapping_rows(db) -> None:
    """A lifecycle delete cannot leave either candidate index searchable."""
    index = RetrievalIndex()
    index.upsert_chunks(db, _indexed_chunks())

    assert index.delete_document(db, "doc-a") == 2

    assert [
        item.chunk_id for item in index.dense_search(db, [1.0, 0.0], top_k=3)
    ] == ["b-best"]
    assert index.lexical_search(db, "alpha") == []
    assert db.execute(
        text("SELECT COUNT(*) FROM retrieval_index_entries WHERE document_id = 'doc-a'")
    ).scalar_one() == 0


def test_lexical_search_batches_scope_and_treats_empty_as_none(db) -> None:
    """Lexical scope is bounded and an explicit empty scope cannot leak rows."""
    index = RetrievalIndex(scope_batch_size=2)
    index.upsert_chunks(db, _indexed_chunks())
    scope = [f"missing-{number}" for number in range(1001)] + ["doc-a", "doc-b"]

    assert index.lexical_search(db, "alpha", document_ids=[]) == []
    assert [
        item.chunk_id
        for item in index.lexical_search(db, "alpha", document_ids=scope, top_k=2)
    ] == ["a-best", "a-second"]


def test_dense_search_accepts_numpy_and_hidden_nearest_does_not_consume_top_k(db) -> None:
    """Vec metadata filtering happens before KNN k, including NumPy queries."""
    index = RetrievalIndex()
    index.upsert_chunks(
        db,
        [
            IndexedChunk("a-best", "doc-a", "alpha", [0.8, 0.2], searchable=True),
            IndexedChunk(
                "processing-best",
                "doc-processing",
                "hidden",
                [1.0, 0.0],
            ),
        ],
    )

    results = index.dense_search(db, np.array([1.0, 0.0], dtype=np.float32), top_k=1)

    assert [item.chunk_id for item in results] == ["a-best"]


def test_hydrate_fetches_ordered_metadata_with_one_joined_select(db) -> None:
    """Candidate hydration cannot regress to chunk/document N+1 queries."""
    statements = []

    def record_select(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(db.get_bind(), "before_cursor_execute", record_select)
    try:
        payloads = RetrievalIndex().hydrate(db, ["b-best", "a-best"])
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", record_select)

    assert [payload["chunk_id"] for payload in payloads] == ["b-best", "a-best"]
    assert [payload["document_title"] for payload in payloads] == ["B", "A"]
    assert len(statements) == 1


def test_backfill_dry_run_is_read_only_then_reconciles_idempotently(db) -> None:
    """Dry-run reports missing rows; apply fills them; a second run is a no-op."""
    db.add_all(
        [
            Embedding(
                id="embedding-a",
                chunk_id="a-best",
                vector_json=[1.0, 0.0],
                model_name="test-model",
            ),
            Embedding(
                id="embedding-b",
                chunk_id="b-best",
                vector_json=[0.0, 1.0],
                model_name="test-model",
            ),
        ]
    )
    db.commit()
    index = RetrievalIndex()
    before = set(db.execute(text("SELECT name FROM sqlite_master")).scalars())

    dry = index.backfill(db, dry_run=True)

    after = set(db.execute(text("SELECT name FROM sqlite_master")).scalars())
    assert dry.dry_run is True
    assert (dry.added, dry.dense_missing, dry.lexical_missing) == (2, 2, 2)
    assert after == before

    applied = index.backfill(db)
    second = index.backfill(db, dry_run=True)

    assert applied.added == 2
    assert [item.chunk_id for item in index.dense_search(db, [1.0, 0.0])] == [
        "a-best",
        "b-best",
    ]
    assert (second.added, second.updated, second.removed) == (0, 0, 0)
    assert (second.dense_missing, second.lexical_missing) == (0, 0)


def test_status_and_dry_backfill_handle_a_prefeature_schema_without_writes(db) -> None:
    """Read-only diagnostics treat absent index tables as missing, not errors."""
    db.add(
        Embedding(
            id="embedding-a",
            chunk_id="a-best",
            vector_json=[1.0, 0.0],
            model_name="test-model",
        )
    )
    db.commit()
    db.execute(text("DROP TABLE retrieval_index_entries"))
    db.commit()
    index = RetrievalIndex()

    status = index.status(db)
    changes = index.backfill(db, dry_run=True)

    assert status.canonical_chunks == 1
    assert changes.added == 1
    names = set(db.execute(text("SELECT name FROM sqlite_master")).scalars())
    assert "retrieval_index_entries" not in names
    assert "retrieval_index_vec" not in names
    assert "retrieval_index_fts" not in names


def test_upsert_virtual_and_mapping_rows_roll_back_together(db) -> None:
    """A caller rollback cannot leave searchable virtual rows behind."""
    index = RetrievalIndex()
    index.upsert_chunks(db, [_indexed_chunks()[0]])

    db.rollback()

    assert db.execute(text("SELECT COUNT(*) FROM retrieval_index_entries")).scalar_one() == 0
    assert index.dense_search(db, [1.0, 0.0]) == []
    assert index.lexical_search(db, "alpha") == []


def test_unchanged_upsert_does_not_rewrite_virtual_rows(db) -> None:
    """Idempotent lifecycle calls preserve stable vec and FTS rows."""
    index = RetrievalIndex()
    chunk = _indexed_chunks()[0]
    index.upsert_chunks(db, [chunk])
    mutations = []

    def record_mutation(_connection, _cursor, statement, _parameters, _context, _many):
        folded = statement.upper()
        if (
            ("RETRIEVAL_INDEX_VEC" in folded or "RETRIEVAL_INDEX_FTS" in folded)
            and (folded.lstrip().startswith("INSERT") or folded.lstrip().startswith("DELETE"))
        ):
            mutations.append(statement)

    event.listen(db.get_bind(), "before_cursor_execute", record_mutation)
    try:
        changes = index.upsert_chunks(db, [chunk])
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", record_mutation)

    assert changes.updated == 0
    assert mutations == []


def test_backfill_detects_and_repairs_missing_virtual_rows(db) -> None:
    """Hash markers cannot hide a deleted vec row or missing FTS posting."""
    db.add(
        Embedding(
            id="embedding-a",
            chunk_id="a-best",
            vector_json=[1.0, 0.0],
            model_name="test-model",
        )
    )
    db.commit()
    index = RetrievalIndex()
    index.backfill(db)
    entry = db.execute(
        text(
            "SELECT id, lexical_text FROM retrieval_index_entries "
            "WHERE chunk_id = 'a-best'"
        )
    ).one()
    db.execute(
        text("DELETE FROM retrieval_index_vec WHERE entry_id = :entry_id"),
        {"entry_id": entry.id},
    )
    db.execute(
        text(
            "INSERT INTO retrieval_index_fts("
            "retrieval_index_fts, rowid, lexical_text) "
            "VALUES ('delete', :entry_id, :lexical_text)"
        ),
        {"entry_id": entry.id, "lexical_text": entry.lexical_text},
    )

    dry = index.backfill(db, dry_run=True)
    index.backfill(db)

    assert (dry.dense_missing, dry.lexical_missing) == (1, 1)
    assert [item.chunk_id for item in index.dense_search(db, [1.0, 0.0])] == [
        "a-best"
    ]
    assert [item.chunk_id for item in index.lexical_search(db, "alpha")] == [
        "a-best"
    ]


def test_backfill_reports_and_rebuilds_a_dimension_change(db) -> None:
    """Only explicit reindexing rebuilds vec0 for a canonical dimension change."""
    index = RetrievalIndex()
    index.ensure_schema(db, 2)
    db.add(
        Embedding(
            id="embedding-a",
            chunk_id="a-best",
            vector_json=[1.0, 0.0, 0.0],
            model_name="new-model",
        )
    )
    db.commit()

    dry = index.backfill(db, dry_run=True)
    with pytest.raises(RetrievalIndexDimensionError, match="run the retrieval reindex"):
        index.dense_search(db, [1.0, 0.0, 0.0])
    index.backfill(db)

    assert dry.dimension_mismatch == 1
    assert index.status(db).dimension == 3
    assert [item.chunk_id for item in index.dense_search(db, [1.0, 0.0, 0.0])] == [
        "a-best"
    ]


def test_scoped_backfill_cannot_rebuild_the_global_vector_dimension(db) -> None:
    """A subset dimension change must preserve every out-of-scope vec row."""
    first = Embedding(
        id="embedding-a",
        chunk_id="a-best",
        vector_json=[1.0, 0.0],
        model_name="old-model",
    )
    second = Embedding(
        id="embedding-b",
        chunk_id="b-best",
        vector_json=[0.0, 1.0],
        model_name="old-model",
    )
    db.add_all([first, second])
    db.commit()
    index = RetrievalIndex()
    index.backfill(db)
    first.vector_json = [1.0, 0.0, 0.0]
    first.model_name = "new-model"
    db.flush()

    with pytest.raises(
        RetrievalIndexDimensionError,
        match="unscoped.*reindex|full.*reindex",
    ):
        index.backfill(db, document_ids=["doc-a"])

    assert db.execute(
        text("SELECT COUNT(*) FROM retrieval_index_vec")
    ).scalar_one() == 2
    assert [
        item.chunk_id
        for item in index.dense_search(
            db,
            [0.0, 1.0],
            document_ids=["doc-b"],
            top_k=1,
        )
    ] == ["b-best"]


def test_backfill_updates_stale_sources_and_removes_deleted_embeddings(db) -> None:
    """Canonical text/vector changes and removals reconcile both indexes."""
    first = Embedding(
        id="embedding-a",
        chunk_id="a-best",
        vector_json=[1.0, 0.0],
        model_name="test-model",
    )
    removed = Embedding(
        id="embedding-b",
        chunk_id="b-best",
        vector_json=[0.0, 1.0],
        model_name="test-model",
    )
    db.add_all([first, removed])
    db.commit()
    index = RetrievalIndex()
    index.backfill(db)

    db.query(Chunk).filter(Chunk.id == "a-best").one().text = "gamma"
    first.vector_json = [0.0, 1.0]
    db.delete(removed)
    db.flush()

    dry = index.backfill(db, dry_run=True)
    index.backfill(db)

    assert (dry.updated, dry.removed) == (1, 1)
    assert (dry.dense_stale, dry.lexical_stale) == (1, 1)
    assert index.lexical_search(db, "alpha") == []
    assert [item.chunk_id for item in index.lexical_search(db, "gamma")] == [
        "a-best"
    ]
    assert db.execute(
        text("SELECT COUNT(*) FROM retrieval_index_entries")
    ).scalar_one() == 1


def test_only_extension_unavailability_activates_dense_fallback(db) -> None:
    """An unavailable load is disclosed, while a broken schema remains an error."""
    class NoExtensionIndex(RetrievalIndex):
        def _load_vector_extension(self, db):
            raise retrieval_index_module._VectorExtensionUnavailable(
                "sqlite-vec extension unavailable (ImportError)"
            )

    fallback = NoExtensionIndex()
    fallback.upsert_chunks(db, [_indexed_chunks()[0]])

    assert [item.chunk_id for item in fallback.dense_search(db, [1.0, 0.0])] == [
        "a-best"
    ]
    status = fallback.status(db)
    assert status.dense_backend == "brute"
    assert status.dimension == 2
    assert "ImportError" in status.fallback_reason

    db.rollback()
    normal = RetrievalIndex()
    normal.ensure_schema(db, 2)
    db.execute(text("DROP TABLE retrieval_index_vec"))
    db.execute(text("CREATE TABLE retrieval_index_vec (broken INTEGER)"))
    with pytest.raises(RetrievalIndexError, match="cannot determine"):
        normal.dense_search(db, [1.0, 0.0])
    assert normal.status().dense_backend != "brute"


def test_dense_fallback_preserves_empty_and_scoped_top_k_semantics(db) -> None:
    """Brute mode applies the same ownership scope before global top-k."""
    class NoExtensionIndex(RetrievalIndex):
        def _load_vector_extension(self, db):
            raise retrieval_index_module._VectorExtensionUnavailable(
                "sqlite-vec extension unavailable (ImportError)"
            )

    index = NoExtensionIndex(scope_batch_size=2)
    index.upsert_chunks(db, _indexed_chunks())

    assert index.dense_search(db, [1.0, 0.0], document_ids=[]) == []
    assert [
        item.chunk_id
        for item in index.dense_search(
            db,
            [1.0, 0.0],
            document_ids=["missing", "doc-b"],
            top_k=1,
        )
    ] == ["b-best"]


def test_dense_index_path_never_unpickles_or_scans_canonical_embeddings(
    db,
    monkeypatch,
) -> None:
    """Normal KNN reads vec0 candidates rather than legacy embedding blobs."""
    index = RetrievalIndex()
    index.upsert_chunks(db, _indexed_chunks())
    statements = []
    monkeypatch.setattr(
        retrieval_index_module.pickle,
        "loads",
        lambda _value: pytest.fail("indexed search unpickled a legacy vector"),
    )

    def record_select(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement.lower())

    event.listen(db.get_bind(), "before_cursor_execute", record_select)
    try:
        results = index.dense_search(db, [1.0, 0.0], top_k=1)
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", record_select)

    assert [item.chunk_id for item in results] == ["a-best"]
    assert any("embedding match" in statement and " k = " in statement for statement in statements)
    assert all(" from embeddings" not in statement for statement in statements)

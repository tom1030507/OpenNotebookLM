"""Live chunk materialization tests for the document resource ceiling."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import Base, Chunk, Document, Embedding
from app.services.chunking import ChunkingService
from app.services.documents import DocumentService


DOCUMENT_ID = "ceiling-document"


class RejectingEmbedder:
    """Record any embedding call, which over-limit inputs must never reach."""

    def __init__(self) -> None:
        self.calls = 0

    def embed_chunks(self, _db, _document_id: str):
        """Reject embedding work for an over-limit document.

        Args:
            _db: Unused database session.
            _document_id: Unused document id.

        Returns:
            Never returns because this path is forbidden.
        """
        self.calls += 1
        raise AssertionError("over-limit chunks reached embedding")


class RecordingCeilingChunker(ChunkingService):
    """Record ceilings received by the shared text splitting path."""

    def __init__(self) -> None:
        super().__init__(chunk_size=100, chunk_overlap=0)
        self.received_limits = []

    def _chunk_text_content(
        self,
        text: str,
        metadata=None,
        max_chunks=None,
    ):
        """Delegate to real text splitting after recording its ceiling.

        Args:
            text: Extracted source text.
            metadata: Optional source metadata.
            max_chunks: Inclusive planned-chunk ceiling.

        Returns:
            Real planned chunk dictionaries.
        """
        self.received_limits.append(max_chunks)
        return super()._chunk_text_content(
            text,
            metadata=metadata,
            max_chunks=max_chunks,
        )


class CountingSegments(list):
    """List-compatible transcript segments that count iteration work."""

    def __init__(self, values) -> None:
        super().__init__(values)
        self.consumed = 0

    def __iter__(self):
        """Yield segments while recording how far the live loop advances.

        Args:
            None.

        Returns:
            Iterator over stored transcript segments.
        """
        for value in super().__iter__():
            self.consumed += 1
            yield value


class SplitRejectingText(str):
    """Text that rejects eager line-list materialization."""

    def split(self, *args, **kwargs):
        """Reject eager ``str.split`` calls.

        Args:
            *args: Positional split arguments.
            **kwargs: Keyword split arguments.

        Returns:
            Never returns because line iteration must be lazy.
        """
        raise AssertionError("live block generation eagerly split every line")


class LazyFragmentChunker(ChunkingService):
    """Expose whether the live path consumes a bounded fragment iterator."""

    def __init__(self) -> None:
        super().__init__(chunk_size=100, chunk_overlap=0)
        self.fragments_generated = 0

    def _split_sentences(self, _text: str):
        """Reject the compatibility list wrapper on the live path.

        Args:
            _text: Unused source text.

        Returns:
            Never returns because the live path must use ``_iter_sentences``.
        """
        raise AssertionError("live fitting materialized the complete sentence list")

    def _iter_bounded_fragments(
        self,
        _text: str,
        start: int = 0,
        stop_at_newline: bool = False,
    ):
        """Yield many bounded fragments while counting consumption.

        Args:
            _text: Unused source text.
            start: Unused source start.
            stop_at_newline: Unused line-boundary mode.

        Returns:
            Iterator of deterministic bounded fragments.
        """
        del start, stop_at_newline
        for index in range(100):
            self.fragments_generated += 1
            yield chr(97 + index % 26) * 100
        return len(_text) + 1


class InstrumentedScannerChunker(ChunkingService):
    """Measure source reads and hard-boundary windows deterministically."""

    def __init__(self) -> None:
        super().__init__(chunk_size=100, chunk_overlap=0)
        self.character_reads = 0
        self.highest_source_index = -1
        self.boundary_windows = []

    def _scan_character(self, text: str, index: int) -> str:
        """Record one production scanner read before returning its character.

        Args:
            text: Source text.
            index: Character index being inspected.

        Returns:
            Character at ``index``.
        """
        self.character_reads += 1
        self.highest_source_index = max(self.highest_source_index, index)
        return super()._scan_character(text, index)

    def _hard_boundary_index(self, text: str, start: int, end: int) -> int:
        """Record the bounded source window searched for a hard split.

        Args:
            text: Source text.
            start: Inclusive source index.
            end: Exclusive source index.

        Returns:
            Boundary selected by the production scanner.
        """
        self.boundary_windows.append((start, end))
        return super()._hard_boundary_index(text, start, end)


class SuffixSliceRejectingText(str):
    """Source that rejects copies extending from a cursor through EOF."""

    def __getitem__(self, key):
        """Reject the quadratic ``remaining = remaining[cut:]`` pattern.

        Args:
            key: Integer or slice requested by the scanner.

        Returns:
            Requested character or explicitly bounded slice.
        """
        if (
            isinstance(key, slice)
            and key.start not in (None, 0)
            and key.stop is None
        ):
            raise AssertionError("scanner copied the complete remaining suffix")
        return super().__getitem__(key)


class GuardedScannerText(str):
    """Huge source that rejects reads beyond the expected ceiling window."""

    max_read_index = 399

    def __getitem__(self, key):
        """Reject character reads and slices reaching the protected suffix.

        Args:
            key: Integer or slice requested by production code.

        Returns:
            Requested character or bounded slice.
        """
        if isinstance(key, int) and key > self.max_read_index:
            raise AssertionError("scanner read beyond the bounded prefix")
        if isinstance(key, slice) and (
            key.stop is None or key.stop > self.max_read_index + 1
        ):
            raise AssertionError("scanner copied the protected source suffix")
        return super().__getitem__(key)

    def find(self, sub, start=None, end=None):
        """Reject unbounded forward searches.

        Args:
            sub: Substring to locate.
            start: Optional inclusive search start.
            end: Optional exclusive search end.

        Returns:
            Matching index from the bounded search.
        """
        if end is None or end > self.max_read_index + 1:
            raise AssertionError("scanner searched the complete source suffix")
        return super().find(sub, start, end)

    def rfind(self, sub, start=None, end=None):
        """Reject unbounded reverse searches.

        Args:
            sub: Substring to locate.
            start: Optional inclusive search start.
            end: Optional exclusive search end.

        Returns:
            Matching index from the bounded search.
        """
        if end is None or end > self.max_read_index + 1:
            raise AssertionError("scanner searched the complete source suffix")
        return super().rfind(sub, start, end)

    def strip(self, chars=None):
        """Reject stripping the complete protected source.

        Args:
            chars: Optional characters to remove.

        Returns:
            Stripped text only when the receiver itself is bounded.
        """
        if len(self) > self.max_read_index + 1:
            raise AssertionError("scanner stripped the complete source")
        return super().strip(chars)


@pytest.fixture
def db():
    """Return an isolated database session."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session = sessionmaker(autocommit=False, autoflush=False, bind=engine)()
    Base.metadata.create_all(bind=engine)

    yield session

    session.close()
    engine.dispose()


def sectioned_content(count: int) -> str:
    """Build content that produces exactly one non-runt chunk per section.

    Args:
        count: Number of independent sections.

    Returns:
        Extracted text for the live text/PDF/URL chunking paths.
    """
    return "\n".join(
        f"# Section {index}\n" + (chr(97 + index % 26) * 80)
        for index in range(count)
    )


def add_document(db, source_type: str, chunk_count: int) -> Document:
    """Persist one source that the live chunker will split predictably.

    Args:
        db: Database session.
        source_type: PDF, URL, YouTube, or generic text source.
        chunk_count: Number of chunks the source should produce.

    Returns:
        Persisted document row.
    """
    content = sectioned_content(chunk_count)
    meta_json = {}
    if source_type == "youtube":
        meta_json = {
            "segments": [
                {
                    "text": chr(97 + index % 26) * 80,
                    "start": float(index),
                    "end": float(index + 1),
                }
                for index in range(chunk_count)
            ],
        }
    document = Document(
        id=DOCUMENT_ID,
        title="Ceiling source",
        source_type=source_type,
        content=content,
        status="processing",
        meta_json=meta_json,
    )
    db.add(document)
    db.commit()
    return document


@pytest.mark.parametrize("source_type", ["pdf", "url", "youtube", "text"])
def test_live_paths_stop_before_any_chunk_orm_write(
    db,
    monkeypatch,
    source_type: str,
) -> None:
    """Every live source path detects limit+1 before add, flush, or commit."""
    add_document(db, source_type, chunk_count=3)
    service = ChunkingService(chunk_size=100, chunk_overlap=0)
    chunk_adds = []
    real_add = db.add
    flush = Mock(wraps=db.flush)
    commit = Mock(wraps=db.commit)

    def record_add(instance) -> None:
        if isinstance(instance, Chunk):
            chunk_adds.append(instance)
        real_add(instance)

    monkeypatch.setattr(db, "add", record_add)
    monkeypatch.setattr(db, "flush", flush)
    monkeypatch.setattr(db, "commit", commit)

    with pytest.raises(ValueError) as raised:
        service.chunk_document(db, DOCUMENT_ID, max_chunks=2)

    assert type(raised.value).__name__ == "ChunkLimitExceededError"
    assert raised.value.chunk_count == 3
    assert raised.value.max_chunks == 2
    assert chunk_adds == []
    flush.assert_not_called()
    commit.assert_not_called()
    assert db.query(Chunk).count() == 0


def test_live_chunker_accepts_exactly_one_thousand_chunks(db) -> None:
    """The configured ceiling is inclusive on the real materialization path."""
    add_document(db, "text", chunk_count=1_000)
    service = ChunkingService(chunk_size=100, chunk_overlap=0)

    chunks = service.chunk_document(db, DOCUMENT_ID, max_chunks=1_000)

    assert len(chunks) == 1_000
    assert db.query(Chunk).filter(Chunk.document_id == DOCUMENT_ID).count() == 1_000


def test_live_one_thousand_and_one_stops_before_chunk_inserts(
    db,
    monkeypatch,
) -> None:
    """A real 1001-chunk input creates no Chunk ORM objects or transaction."""
    add_document(db, "text", chunk_count=1_001)
    service = ChunkingService(chunk_size=100, chunk_overlap=0)
    real_add = db.add
    chunk_adds = []
    commit = Mock(wraps=db.commit)

    def record_add(instance) -> None:
        if isinstance(instance, Chunk):
            chunk_adds.append(instance)
        real_add(instance)

    monkeypatch.setattr(db, "add", record_add)
    monkeypatch.setattr(db, "commit", commit)

    with pytest.raises(ValueError) as raised:
        service.chunk_document(db, DOCUMENT_ID, max_chunks=1_000)

    assert raised.value.chunk_count == 1_001
    assert chunk_adds == []
    commit.assert_not_called()
    assert db.query(Chunk).count() == 0


def test_first_no_punctuation_fragment_reads_only_one_bounded_window() -> None:
    """Calling next cannot scan a huge block before producing useful text."""
    service = InstrumentedScannerChunker()
    text = "x" * 1_000_000

    first = next(service._iter_sentences(text))

    assert first == "x" * service.chunk_size
    assert 0 < service.character_reads <= service.chunk_size
    assert service.highest_source_index < service.chunk_size
    assert service.boundary_windows == [(0, service.chunk_size)]


def test_ceiling_stops_scanner_after_limit_plus_one_windows() -> None:
    """Final N+1 detection never reads the remainder of a huge source."""
    service = InstrumentedScannerChunker()
    text = GuardedScannerText("x" * 1_000_000)

    with pytest.raises(ValueError):
        service._chunk_text_content(text, max_chunks=2)

    assert 0 < service.character_reads <= 3 * service.chunk_size + 3
    assert service.highest_source_index < 3 * service.chunk_size
    assert service.boundary_windows == [(0, 100), (100, 200), (200, 300)]


def test_hard_split_never_copies_the_complete_remaining_suffix() -> None:
    """Cursor-based hard splitting only materializes bounded fragments."""
    service = ChunkingService(chunk_size=100, chunk_overlap=0)
    text = SuffixSliceRejectingText("x" * 350)

    fragments = list(service._hard_split(text))

    assert [len(fragment) for fragment in fragments] == [100, 100, 100, 50]


def test_multiline_block_generation_does_not_split_every_line_first() -> None:
    """The live block iterator avoids an eager list of every source line."""
    text = SplitRejectingText(sectioned_content(100))
    service = ChunkingService(chunk_size=100, chunk_overlap=0)

    with pytest.raises(ValueError):
        service._chunk_text_content(text, max_chunks=2)


def test_bounded_fragment_generation_stops_at_limit_plus_one() -> None:
    """The live path never builds or consumes every derived fragment."""
    service = LazyFragmentChunker()

    with pytest.raises(ValueError):
        service._chunk_text_content("unused" * 20, max_chunks=2)

    assert service.fragments_generated == 3


def test_final_ceiling_does_not_reject_a_mergeable_runt() -> None:
    """Raw packed fragments may exceed the limit when final chunks do not."""
    text = "\n".join(("a" * 80, "b" * 80, "c" * 19))
    service = ChunkingService(chunk_size=100, chunk_overlap=0)

    chunks = service._chunk_text_content(text, max_chunks=2)

    assert len(chunks) == 2
    assert chunks[-1]["text"].endswith("c" * 19)
    assert all(chunk["metadata"]["total_chunks"] == 2 for chunk in chunks)


def test_final_ceiling_counts_after_backward_runt_merge() -> None:
    """A trailing runt folded backward does not create a false N+1 failure."""
    service = ChunkingService(chunk_size=100, chunk_overlap=0)
    packed = [
        ("a" * 100, 0, 100, "section"),
        ("b" * 89, 101, 190, "section"),
        ("c" * 10, 191, 201, "section"),
    ]

    chunks = service._merge_runts(iter(packed), max_chunks=2)

    assert chunks == [packed[0], ("b" * 89 + "\n" + "c" * 10, 101, 201, "section")]


def test_final_ceiling_counts_after_forward_runt_merge() -> None:
    """A leading runt folded forward remains one final planned chunk."""
    service = ChunkingService(chunk_size=100, chunk_overlap=0)
    packed = [
        ("a" * 10, 0, 10, "section"),
        ("b" * 89, 11, 100, "section"),
    ]

    chunks = service._merge_runts(iter(packed), max_chunks=1)

    assert chunks == [("a" * 10 + "\n" + "b" * 89, 0, 100, "section")]


def test_heading_flush_never_carries_overlap_into_next_section() -> None:
    """Only size-driven splits may seed overlap into their successor."""
    service = ChunkingService(chunk_size=100, chunk_overlap=20)
    text = "# Alpha\n" + "a" * 100 + "\n# Beta\n" + "b" * 80

    chunks = service._chunk_text_content(text, max_chunks=2)

    assert [chunk["metadata"]["heading_path"] for chunk in chunks] == [
        "Alpha",
        "Beta",
    ]
    assert chunks[1]["text"] == "b" * 80


@pytest.mark.parametrize("source_type", ["pdf", "url", "text"])
def test_text_based_live_wrappers_forward_the_ceiling(
    db,
    source_type: str,
) -> None:
    """PDF, URL, and generic text share the bounded packing pipeline."""
    add_document(db, source_type, chunk_count=3)
    service = RecordingCeilingChunker()

    with pytest.raises(ValueError):
        service.chunk_document(db, DOCUMENT_ID, max_chunks=2)

    assert service.received_limits == [2]


def test_youtube_segment_loop_stops_consuming_at_limit_plus_one() -> None:
    """Transcript expansion stops without walking unrelated later segments."""
    segments = CountingSegments([
        {
            "text": chr(97 + index % 26) * 80,
            "start": float(index),
            "end": float(index + 1),
        }
        for index in range(100)
    ])
    document = SimpleNamespace(
        content="unused",
        meta_json={"segments": segments},
    )
    service = ChunkingService(chunk_size=100, chunk_overlap=0)

    with pytest.raises(ValueError):
        service._chunk_youtube_content(document, max_chunks=2)

    assert segments.consumed == 3


def test_document_service_records_live_ceiling_and_cleans_old_index(
    db,
    monkeypatch,
) -> None:
    """Early failure reuses atomic metadata cleanup without new chunk writes."""
    add_document(db, "url", chunk_count=3)
    old_chunk = Chunk(
        id="old-chunk",
        document_id=DOCUMENT_ID,
        text="old",
        start_offset=0,
        end_offset=3,
        meta_json={},
    )
    db.add(old_chunk)
    db.add(Embedding(
        id="old-embedding",
        chunk_id=old_chunk.id,
        vector_json=[1.0],
        model_name="old",
    ))
    db.commit()
    real_add = db.add
    new_chunk_adds = []

    def record_add(instance) -> None:
        if isinstance(instance, Chunk):
            new_chunk_adds.append(instance)
        real_add(instance)

    monkeypatch.setattr(db, "add", record_add)
    embedder = RejectingEmbedder()
    service = DocumentService(
        chunking_service=ChunkingService(chunk_size=100, chunk_overlap=0),
        embedding_service=embedder,
        max_chunks_per_doc=2,
    )

    try:
        status = service._index_document(db, DOCUMENT_ID, "URL")
    finally:
        service.executor.shutdown(wait=True)

    db.expire_all()
    document = db.query(Document).filter(Document.id == DOCUMENT_ID).one()
    assert status == document.status == "error"
    assert document.meta_json["indexing_failure"] == {
        "code": "chunk_limit_exceeded",
        "chunk_count": 3,
        "max_chunks": 2,
        "action": "Reduce the source size or increase CHUNK_SIZE before retrying.",
    }
    assert new_chunk_adds == []
    assert embedder.calls == 0
    assert db.query(Chunk).filter(Chunk.document_id == DOCUMENT_ID).count() == 0
    assert db.query(Embedding).count() == 0

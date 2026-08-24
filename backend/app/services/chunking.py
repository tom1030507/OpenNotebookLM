"""Document chunking service."""
import uuid
from typing import Any, Dict, Generator, Iterable, Iterator, List, Optional, Tuple
from dataclasses import dataclass, asdict
import structlog
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import Document, Chunk
from app.utils.text import PAGE_SEPARATOR

logger = structlog.get_logger()
settings = get_settings()

# Sentence terminators. The CJK set matters as much as the Latin one: the
# previous splitter required `[.!?]` followed by whitespace and an ASCII capital,
# so a Chinese page produced no boundaries at all and became a single chunk —
# unsearchable at passage level, and directly at odds with the multilingual
# embedding model this project deliberately uses.
CJK_TERMINATORS = "。！？；…"
LATIN_TERMINATORS = ".!?"
CLOSING_MARKS = "」』）〉》”’\"')]"

# Abbreviations whose trailing dot must not end a sentence.
ABBREVIATIONS = ("Dr", "Mr", "Mrs", "Ms", "Prof", "Sr", "Jr", "St", "vs",
                 "Fig", "No", "Vol", "Inc", "Ltd", "Approx", "cf")

# Chunks below this are too small to answer anything on their own; they are
# merged into a neighbour rather than indexed as their own vector.
MIN_CHUNK_CHARS = 80

# Blocks are rejoined one per line, so a chunk keeps the paragraph structure the
# extractor produced.
LINE_JOIN = "\n"

# One character may be inspected by the sentence scanner, local period
# lookback, a bounded newline probe, and three hard-boundary searches. Keeping
# sixteen units per allowed output character covers those constant passes while
# preventing whitespace or metadata-only input from bypassing the chunk limit.
SOURCE_SCAN_BUDGET_FACTOR = 16


class ChunkLimitExceededError(ValueError):
    """Raised before ORM rows are created for an over-limit chunk plan."""

    def __init__(self, chunk_count: int, max_chunks: int) -> None:
        """Record the first observed count beyond the configured ceiling.

        Args:
            chunk_count: Number of planned chunks observed when stopping.
            max_chunks: Inclusive configured ceiling.

        Returns:
            None.
        """
        self.chunk_count = chunk_count
        self.max_chunks = max_chunks
        super().__init__(
            f"Document produced at least {chunk_count} chunks, exceeding "
            f"the limit of {max_chunks}"
        )


@dataclass
class _SourceScanBudget:
    """Per-call work budget shared by every source scanner in one plan."""

    remaining: int
    max_chunks: int

    def consume(self, amount: int = 1) -> None:
        """Charge bounded scanner work or stop the over-limit plan.

        Args:
            amount: Number of constant-time source inspections to charge.

        Returns:
            None.
        """
        if amount < 0:
            raise ValueError("scan budget charge must not be negative")
        if amount > self.remaining:
            self.remaining = 0
            raise ChunkLimitExceededError(
                chunk_count=self.max_chunks + 1,
                max_chunks=self.max_chunks,
            )
        self.remaining -= amount


@dataclass
class ChunkMetadata:
    """Metadata for a document chunk."""
    chunk_index: int
    total_chunks: int
    start_char: int
    end_char: int
    page_num: Optional[int] = None
    section: Optional[str] = None
    heading_path: Optional[str] = None
    timestamp_start: Optional[float] = None
    timestamp_end: Optional[float] = None


@dataclass
class _Block:
    """One line of extracted content, with where it came from."""
    text: str
    start: int
    end: int
    heading_path: str


@dataclass(frozen=True)
class _Fragment:
    """One bounded output value and its exact source span."""

    text: str
    start: int
    end: int


class ChunkingService:
    """Service for splitting documents into chunks."""

    def __init__(
        self,
        chunk_size: int = None,
        chunk_overlap: int = None,
    ):
        """Initialize chunking service.

        Args:
            chunk_size: Maximum size of each chunk in characters
            chunk_overlap: Number of overlapping characters between chunks

        Returns:
            None.
        """
        self.chunk_size = settings.chunk_size if chunk_size is None else chunk_size
        if self.chunk_size <= 0:
            raise ValueError("chunk_size must be greater than zero")
        self.chunk_overlap = chunk_overlap if chunk_overlap is not None else settings.chunk_overlap

    def chunk_document(
        self,
        db: Session,
        document_id: str,
        max_chunks: Optional[int] = None,
    ) -> List[Chunk]:
        """Chunk a document and save chunks to database.

        Args:
            db: Database session
            document_id: Document ID to chunk
            max_chunks: Inclusive ceiling checked before any Chunk ORM rows or
                chunk transaction are created.

        Returns:
            List of created chunks
        """
        # Get document
        document = db.query(Document).filter(Document.id == document_id).first()
        if not document:
            raise ValueError(f"Document {document_id} not found")

        if not document.content:
            logger.warning("Document has no content to chunk", document_id=document_id)
            return []

        if max_chunks is not None and max_chunks < 1:
            raise ValueError("max_chunks must be at least 1")

        # Create chunks based on document type
        if document.source_type == "pdf":
            chunks_data = self._chunk_pdf_content(
                document,
                max_chunks=max_chunks,
            )
        elif document.source_type == "url":
            chunks_data = self._chunk_url_content(
                document,
                max_chunks=max_chunks,
            )
        elif document.source_type == "youtube":
            chunks_data = self._chunk_youtube_content(
                document,
                max_chunks=max_chunks,
            )
        else:
            chunks_data = self._chunk_text_content(
                document.content,
                max_chunks=max_chunks,
            )

        # Only a validated plan may mutate the index. A bulk `.delete()` would
        # bypass the cascade on Chunk.embedding and leave orphan embeddings.
        for existing in db.query(Chunk).filter(Chunk.document_id == document_id).all():
            db.delete(existing)
        db.flush()

        # Save chunks to database
        chunks = []
        for chunk_data in chunks_data:
            chunk = Chunk(
                id=str(uuid.uuid4()),
                document_id=document_id,
                text=chunk_data["text"],
                start_offset=chunk_data["metadata"]["start_char"],
                end_offset=chunk_data["metadata"]["end_char"],
                page_num=chunk_data["metadata"].get("page_num"),
                heading_path=chunk_data["metadata"].get("heading_path"),
                ts_start=chunk_data["metadata"].get("timestamp_start"),
                ts_end=chunk_data["metadata"].get("timestamp_end"),
                meta_json={
                    "chunk_index": chunk_data["metadata"]["chunk_index"],
                    "total_chunks": chunk_data["metadata"]["total_chunks"],
                    "section": chunk_data["metadata"].get("section"),
                }
            )
            db.add(chunk)
            chunks.append(chunk)

        db.commit()

        logger.info(
            "Document chunked successfully",
            document_id=document_id,
            num_chunks=len(chunks)
        )

        return chunks

    def _chunk_text_content(
        self,
        text: str,
        metadata: Dict[str, Any] = None,
        max_chunks: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Chunk text, respecting section headings and sentence boundaries.

        Extraction emits `## Heading` lines, so a chunk never straddles a section
        and every chunk knows the section path it came from.

        Args:
            text: Text to chunk
            metadata: Optional metadata
            max_chunks: Inclusive planned-chunk ceiling.

        Returns:
            List of chunks with metadata
        """
        if max_chunks is not None and max_chunks < 1:
            raise ValueError("max_chunks must be at least 1")
        scan_budget = (
            _SourceScanBudget(
                remaining=(
                    max_chunks
                    * self.chunk_size
                    * SOURCE_SCAN_BUDGET_FACTOR
                ),
                max_chunks=max_chunks,
            )
            if max_chunks is not None
            else None
        )
        blocks = self._to_blocks(text, scan_budget=scan_budget)
        packed = self._merge_runts(
            self._pack(blocks),
            max_chunks=max_chunks,
        )

        chunks = []
        for index, (chunk_text, start, end, heading_path) in enumerate(packed):
            chunks.append({
                "text": chunk_text,
                "metadata": ChunkMetadata(
                    chunk_index=index,
                    total_chunks=len(packed),
                    start_char=start,
                    end_char=end,
                    heading_path=heading_path or None,
                    section=heading_path.split(" > ")[-1] if heading_path else None,
                ),
            })

        for chunk in chunks:
            chunk["metadata"] = asdict(chunk["metadata"])

        return chunks

    def _to_blocks(
        self,
        text: str,
        scan_budget: Optional[_SourceScanBudget] = None,
    ) -> Iterator[_Block]:
        """Stream bounded content blocks while tracking the heading stack.

        Args:
            text: Extracted document text.
            scan_budget: Per-plan source-work budget, when a ceiling applies.

        Returns:
            Iterator of content blocks in document order.
        """
        stack: List[Tuple[int, str]] = []
        offset = 0
        length = len(text)

        while offset < length:
            content_start = offset
            while content_start < length:
                char = self._scan_character(
                    text,
                    content_start,
                    scan_budget=scan_budget,
                )
                if char == "\n":
                    offset = content_start + 1
                    break
                if not char.isspace():
                    break
                content_start += 1
            else:
                return

            if offset > content_start:
                continue

            # Only bounded, ordinary headings become metadata. Treating an
            # attacker-sized `# ...` line as content avoids copying its full
            # title before the document ceiling can stop the scanner.
            hash_end = content_start
            if char == "#":
                while (
                    hash_end < length
                    and hash_end - content_start < 7
                    and self._scan_character(
                        text,
                        hash_end,
                        scan_budget=scan_budget,
                    ) == "#"
                ):
                    hash_end += 1
            heading_level = hash_end - content_start
            heading_handled = False
            if 1 <= heading_level <= 6 and hash_end < length:
                separator = self._scan_character(
                    text,
                    hash_end,
                    scan_budget=scan_budget,
                )
                if separator.isspace() and separator != "\n":
                    title_start = hash_end + 1
                    while title_start < length:
                        char = self._scan_character(
                            text,
                            title_start,
                            scan_budget=scan_budget,
                        )
                        if char == "\n" or not char.isspace():
                            break
                        title_start += 1

                    title_limit = min(title_start + self.chunk_size, length)
                    search_end = min(title_limit + 1, length)
                    newline = self._find_in_window(
                        text,
                        "\n",
                        title_start,
                        search_end,
                        scan_budget=scan_budget,
                    )
                    if newline >= 0 or title_limit == length:
                        line_end = newline if newline >= 0 else length
                        title = text[title_start:line_end].strip()
                        if title:
                            while stack and stack[-1][0] >= heading_level:
                                stack.pop()
                            stack.append((heading_level, title))
                            offset = line_end + 1
                            heading_handled = True

            if heading_handled:
                continue

            # Preserve the historical short-line contract exactly. Sentence
            # streaming is only needed when a line extends beyond one bounded
            # window; splitting short lines changes their text separators and
            # makes offsets drift from the source.
            line_probe_end = min(content_start + self.chunk_size + 1, length)
            newline = self._find_in_window(
                text,
                "\n",
                content_start,
                line_probe_end,
                scan_budget=scan_budget,
            )
            short_line_end: Optional[int] = None
            if newline >= 0:
                short_line_end = newline
            elif length - content_start <= self.chunk_size:
                short_line_end = length
            if short_line_end is not None:
                fragment = self._fragment_from_bounds(
                    text,
                    content_start,
                    short_line_end,
                    scan_budget=scan_budget,
                )
                if fragment is not None:
                    yield _Block(
                        text=fragment.text,
                        start=fragment.start,
                        end=fragment.end,
                        heading_path=" > ".join(title for _, title in stack),
                    )
                offset = short_line_end + 1
                continue

            fragments = self._iter_bounded_fragments(
                text,
                start=content_start,
                stop_at_newline=True,
                scan_budget=scan_budget,
            )
            while True:
                try:
                    fragment = next(fragments)
                except StopIteration as stopped:
                    offset = stopped.value
                    break
                yield _Block(
                    text=fragment.text,
                    start=fragment.start,
                    end=fragment.end,
                    heading_path=" > ".join(title for _, title in stack),
                )

    def _pack(
        self,
        blocks: Iterable[_Block],
    ) -> Iterator[Tuple[str, int, int, str]]:
        """Group blocks into chunks of at most `chunk_size` characters.

        A block longer than the limit is split on sentence boundaries, and a
        sentence longer than the limit is cut at a word boundary near it — the
        previous implementation let an oversized sentence through whole, which is
        how a 4968-character chunk ended up in the index.

        Args:
            blocks: Content blocks in document order.

        Returns:
            Iterator of (text, start_offset, end_offset, heading_path) tuples.
        """
        current: List[_Block] = []
        current_len = 0
        pending_overlap: Optional[Tuple[str, int, int, str]] = None

        def flush() -> Optional[Tuple[str, int, int, str]]:
            nonlocal current, current_len
            if not current:
                return None
            text = LINE_JOIN.join(block.text for block in current)
            completed = (
                text,
                current[0].start,
                current[-1].end,
                current[0].heading_path,
            )
            current = []
            current_len = 0
            return completed

        for block in blocks:
            if current and block.heading_path != current[0].heading_path:
                completed = flush()
                if completed is not None:
                    # Heading boundaries are semantic boundaries. Overlap is
                    # only carried after a size-driven split in one section.
                    pending_overlap = None
                    yield completed
            elif pending_overlap and block.heading_path != pending_overlap[3]:
                pending_overlap = None

            for piece in self._fit(block):
                piece_len = len(piece.text)

                if not current and pending_overlap is not None:
                    overlap = self._overlap_block(pending_overlap)
                    pending_overlap = None
                    if (
                        overlap is not None
                        and overlap.heading_path == piece.heading_path
                        and len(overlap.text) + piece_len + 1 <= self.chunk_size
                    ):
                        current = [overlap]
                        current_len = len(overlap.text)

                separator_len = 1 if current else 0
                if current and current_len + separator_len + piece_len > self.chunk_size:
                    completed = flush()
                    if completed is not None:
                        yield completed
                        overlap = self._overlap_block(completed)
                        if (
                            overlap is not None
                            and overlap.heading_path == piece.heading_path
                            and len(overlap.text) + piece_len + 1 <= self.chunk_size
                        ):
                            current = [overlap]
                            current_len = len(overlap.text)

                separator_len = 1 if current else 0
                current.append(piece)
                current_len += separator_len + piece_len

                # Yield a full chunk immediately. Waiting for the following
                # piece would needlessly materialize arbitrarily large source
                # expansions before the final ceiling can stop iteration.
                if current_len >= self.chunk_size:
                    completed = flush()
                    if completed is not None:
                        pending_overlap = completed
                        yield completed

        completed = flush()
        if completed is not None:
            yield completed

    def _fit(self, block: _Block) -> Iterator[_Block]:
        """Break a block down until every piece fits the chunk size.

        Args:
            block: One content block.

        Returns:
            Iterator of blocks no longer than `chunk_size`, in order.
        """
        if len(block.text) <= self.chunk_size:
            yield block
            return

        cursor = block.start
        yielded = False
        for sentence in self._iter_sentences(block.text):
            for fragment in self._hard_split(sentence):
                yielded = True
                yield _Block(
                    text=fragment,
                    start=cursor,
                    end=cursor + len(fragment),
                    heading_path=block.heading_path,
                )
                cursor += len(fragment)
        if not yielded:
            yield block

    def _hard_split(self, sentence: str) -> Iterator[str]:
        """Cut an over-long sentence with a bounded cursor scanner.

        Args:
            sentence: A single sentence.

        Returns:
            Iterator of fragments no longer than `chunk_size`.
        """
        start = 0
        length = len(sentence)

        while length - start > self.chunk_size:
            window_end = start + self.chunk_size
            cut = self._hard_boundary_index(sentence, start, window_end)
            if cut <= start or cut - start < self.chunk_size // 2:
                cut = window_end
            fragment = sentence[start:cut].strip()
            if fragment:
                yield fragment
            start = self._skip_whitespace(sentence, cut)

        fragment = sentence[start:length].strip()
        if fragment:
            yield fragment

    def _scan_character(
        self,
        text: str,
        index: int,
        scan_budget: Optional[_SourceScanBudget] = None,
    ) -> str:
        """Read one source character through an instrumentable boundary.

        Args:
            text: Source text.
            index: Character index to inspect.
            scan_budget: Per-plan source-work budget, when one applies.

        Returns:
            Character at ``index``.
        """
        if scan_budget is not None:
            scan_budget.consume()
        return text[index]

    def _find_in_window(
        self,
        text: str,
        value: str,
        start: int,
        end: int,
        scan_budget: Optional[_SourceScanBudget] = None,
    ) -> int:
        """Find a value while charging only one explicitly bounded window.

        Args:
            text: Source text.
            value: Value to locate.
            start: Inclusive bounded search start.
            end: Exclusive bounded search end.
            scan_budget: Per-plan source-work budget, when one applies.

        Returns:
            Matching source index, or ``-1``.
        """
        if scan_budget is not None:
            scan_budget.consume(max(0, end - start))
        return text.find(value, start, end)

    def _hard_boundary_index(
        self,
        text: str,
        start: int,
        end: int,
        scan_budget: Optional[_SourceScanBudget] = None,
    ) -> int:
        """Find the last word or comma boundary in one bounded window.

        Args:
            text: Source text.
            start: Inclusive window start.
            end: Exclusive window end, at most one chunk after ``start``.
            scan_budget: Per-plan source-work budget, when one applies.

        Returns:
            Absolute boundary index, or ``-1`` when the window has none.
        """
        if scan_budget is not None:
            scan_budget.consume(3 * max(0, end - start))
        return max(
            text.rfind(" ", start, end),
            text.rfind("，", start, end),
            text.rfind(",", start, end),
        )

    def _skip_whitespace(
        self,
        text: str,
        start: int,
        scan_budget: Optional[_SourceScanBudget] = None,
    ) -> int:
        """Advance a cursor past whitespace without copying its suffix.

        Args:
            text: Source text.
            start: Cursor to advance.
            scan_budget: Per-plan source-work budget, when one applies.

        Returns:
            First non-whitespace index, or the text length.
        """
        length = len(text)
        while start < length and self._scan_character(
            text,
            start,
            scan_budget=scan_budget,
        ).isspace():
            start += 1
        return start

    def _fragment_from_bounds(
        self,
        text: str,
        start: int,
        end: int,
        scan_budget: Optional[_SourceScanBudget] = None,
    ) -> Optional[_Fragment]:
        """Trim one bounded range and retain its exact source coordinates.

        Args:
            text: Original source text.
            start: Inclusive raw range start.
            end: Exclusive raw range end.
            scan_budget: Per-plan source-work budget, when one applies.

        Returns:
            Exact non-whitespace fragment, or None for an empty range.
        """
        raw = text[start:end]
        if scan_budget is not None:
            # Both trim passes are confined to this one chunk-sized copy. Charge
            # them explicitly without re-reading the source through the scanner.
            scan_budget.consume(2 * len(raw))
        left_trimmed = raw.lstrip()
        exact_text = left_trimmed.rstrip()
        if not exact_text:
            return None
        exact_start = start + len(raw) - len(left_trimmed)
        exact_end = exact_start + len(exact_text)
        return _Fragment(
            text=exact_text,
            start=exact_start,
            end=exact_end,
        )

    @staticmethod
    def _is_word_character(char: str) -> bool:
        """Return whether a character participates in a regex-style word.

        Args:
            char: One source character.

        Returns:
            True for alphanumeric characters and underscore.
        """
        return char.isalnum() or char == "_"

    def _is_protected_period(
        self,
        text: str,
        index: int,
        scan_budget: Optional[_SourceScanBudget] = None,
    ) -> bool:
        """Recognize abbreviation and uppercase-initial periods locally.

        Args:
            text: Source text.
            index: Index of the period under consideration.
            scan_budget: Per-plan source-work budget, when one applies.

        Returns:
            True when the period must not terminate a sentence.
        """
        max_abbreviation_length = max(len(value) for value in ABBREVIATIONS)
        word_start = index
        while (
            word_start > 0
            and index - word_start < max_abbreviation_length
        ):
            previous = self._scan_character(
                text,
                word_start - 1,
                scan_budget=scan_budget,
            )
            if not self._is_word_character(previous):
                break
            word_start -= 1
        abbreviation = text[word_start:index]
        if (
            abbreviation in ABBREVIATIONS
            and (
                word_start == 0
                or not self._is_word_character(
                    self._scan_character(
                        text,
                        word_start - 1,
                        scan_budget=scan_budget,
                    )
                )
            )
        ):
            return True

        letter_index = index - 1
        if letter_index < 0:
            return False
        letter = self._scan_character(
            text,
            letter_index,
            scan_budget=scan_budget,
        )
        if letter not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            return False
        return letter_index == 0 or not self._is_word_character(
            self._scan_character(
                text,
                letter_index - 1,
                scan_budget=scan_budget,
            )
        )

    def _sentence_end_index(
        self,
        text: str,
        index: int,
        fragment_start: int,
        char: str,
        scan_budget: Optional[_SourceScanBudget] = None,
    ) -> Optional[int]:
        """Find a sentence end using only constant local lookaround.

        Args:
            text: Source text.
            index: Index of the already-read character.
            fragment_start: Start of the current bounded fragment.
            char: Character at ``index``.
            scan_budget: Per-plan source-work budget, when one applies.

        Returns:
            Exclusive sentence-end index, or None when scanning should continue.
        """
        length = len(text)
        if char in CJK_TERMINATORS:
            end = index + 1
            fragment_limit = min(fragment_start + self.chunk_size, length)
            while end < fragment_limit:
                if self._scan_character(
                    text,
                    end,
                    scan_budget=scan_budget,
                ) not in CLOSING_MARKS:
                    break
                end += 1
            return end

        if char not in LATIN_TERMINATORS:
            return None
        if char == "." and self._is_protected_period(
            text,
            index,
            scan_budget=scan_budget,
        ):
            return None

        following_index = index + 1
        if following_index >= length:
            return following_index
        if self._scan_character(
            text,
            following_index,
            scan_budget=scan_budget,
        ).isspace():
            return following_index
        return None

    def _overlap_block(self, chunk: Tuple[str, int, int, str]) -> Optional[_Block]:
        """Build the overlap carried into the next chunk.

        Honours the configured `chunk_overlap` in characters. The previous
        implementation only tested it for being non-zero and then carried exactly
        one sentence, so the number in the config had no effect at all.

        Args:
            chunk: The chunk just flushed.

        Returns:
            A block holding the overlap text, or None when overlap is disabled.
        """
        if self.chunk_overlap <= 0:
            return None

        text, _, end, heading_path = chunk
        tail = text[-self.chunk_overlap:]
        if len(tail) < len(text):
            # Start the overlap at a boundary so it does not open mid-word.
            boundary = max(tail.find(" "), tail.find("\n"))
            if 0 <= boundary < len(tail) - 1:
                tail = tail[boundary + 1:]
        tail = tail.strip()
        if not tail:
            return None

        return _Block(text=tail, start=max(0, end - len(tail)), end=end,
                      heading_path=heading_path)

    def _merge_runts(
        self,
        chunks: Iterable[Tuple[str, int, int, str]],
        max_chunks: Optional[int] = None,
    ) -> List[Tuple[str, int, int, str]]:
        """Fold chunks too small to stand alone into a neighbour.

        Merging never crosses a section and never breaks the size limit. Both
        matter: a merged chunk that outgrew `chunk_size` would be truncated by the
        embedding model's sequence limit — for CJK text, where a character is
        roughly a token, that truncation starts almost immediately — and merging
        across a heading would file the result under the wrong section.

        A runt that fits nowhere is kept as it is; that is better than either
        violating the size contract or mislabelling the passage.

        Args:
            chunks: Packed chunks.
            max_chunks: Inclusive final-chunk ceiling.

        Returns:
            Chunks with runts merged.
        """
        merged: List[Tuple[str, int, int, str]] = []
        iterator = iter(chunks)
        sentinel = object()
        current = next(iterator, sentinel)

        def append_final(chunk: Tuple[str, int, int, str]) -> None:
            if max_chunks is not None and len(merged) >= max_chunks:
                raise ChunkLimitExceededError(
                    chunk_count=max_chunks + 1,
                    max_chunks=max_chunks,
                )
            merged.append(chunk)

        while current is not sentinel:
            text, start, end, heading_path = current

            if len(text) >= MIN_CHUNK_CHARS:
                append_final(current)
                current = next(iterator, sentinel)
                continue

            if (
                merged
                and merged[-1][3] == heading_path
                and len(merged[-1][0]) + len(text) + 1 <= self.chunk_size
            ):
                previous = merged.pop()
                merged.append((
                    previous[0] + LINE_JOIN + text, previous[1], end, heading_path,
                ))
                current = next(iterator, sentinel)
                continue

            following = next(iterator, sentinel)
            if (
                following is not sentinel
                and following[3] == heading_path
                and len(text) + len(following[0]) + 1 <= self.chunk_size
            ):
                current = (
                    text + LINE_JOIN + following[0], start, following[2], heading_path,
                )
                continue

            append_final(current)
            current = following

        return merged

    def _chunk_pdf_content(
        self,
        document: Document,
        max_chunks: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Chunk PDF content, preserving page information.

        Args:
            document: Document object
            max_chunks: Inclusive planned-chunk ceiling.

        Returns:
            List of chunks with metadata
        """
        chunks = self._chunk_text_content(
            document.content,
            max_chunks=max_chunks,
        )

        pages = (document.meta_json or {}).get("pages") or []
        if not pages:
            return chunks

        # `content` is the pages joined with a blank line, so a chunk's start
        # offset locates its page exactly. The previous code guessed by dividing
        # chunk count by page count, and in practice never ran at all because the
        # pages array was dropped before it reached the database.
        boundaries = []
        cursor = 0
        for page in pages:
            cursor += len(page.get("text", "")) + len(PAGE_SEPARATOR)
            boundaries.append(cursor)

        for chunk in chunks:
            start = chunk["metadata"]["start_char"]
            page_num = len(pages)
            for index, boundary in enumerate(boundaries, start=1):
                if start < boundary:
                    page_num = index
                    break
            chunk["metadata"]["page_num"] = page_num

        return chunks

    def _chunk_url_content(
        self,
        document: Document,
        max_chunks: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Chunk URL content, preserving structure information.

        Args:
            document: Document object
            max_chunks: Inclusive planned-chunk ceiling.

        Returns:
            List of chunks with metadata
        """
        chunks = self._chunk_text_content(
            document.content,
            max_chunks=max_chunks,
        )

        # Fall back to the page title when a chunk sits above the first heading,
        # so a citation always has something to show. Chunks inside a section
        # keep the real heading path built by `_to_blocks`.
        title = (document.meta_json or {}).get("metadata", {}).get("title") or document.title
        for chunk in chunks:
            if not chunk["metadata"].get("heading_path") and title:
                chunk["metadata"]["heading_path"] = title

        return chunks

    def _chunk_youtube_content(
        self,
        document: Document,
        max_chunks: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Chunk YouTube transcript, preserving timestamps.

        Args:
            document: Document object
            max_chunks: Inclusive planned-chunk ceiling.

        Returns:
            List of chunks with metadata
        """
        chunks = []

        # Check if we have segments in metadata
        if document.meta_json and "segments" in document.meta_json:
            segments = document.meta_json["segments"]

            # Group segments into chunks
            current_chunk_text = []
            current_chunk_segments = []
            current_length = 0
            chunk_index = 0

            for segment in segments:
                segment_text = segment.get("text", "")
                segment_length = len(segment_text)

                if current_length + segment_length > self.chunk_size and current_chunk_text:
                    # Save current chunk
                    chunk_text = " ".join(current_chunk_text)

                    chunks.append({
                        "text": chunk_text,
                        "metadata": {
                            "chunk_index": chunk_index,
                            "total_chunks": 0,
                            "start_char": current_chunk_segments[0].get("start", 0),
                            "end_char": current_chunk_segments[-1].get("end", 0),
                            "timestamp_start": current_chunk_segments[0].get("start", 0),
                            "timestamp_end": current_chunk_segments[-1].get("end", 0),
                        }
                    })

                    # Reset for next chunk
                    current_chunk_text = []
                    current_chunk_segments = []
                    current_length = 0
                    chunk_index += 1

                if (
                    not current_chunk_text
                    and max_chunks is not None
                    and len(chunks) >= max_chunks
                ):
                    raise ChunkLimitExceededError(
                        chunk_count=max_chunks + 1,
                        max_chunks=max_chunks,
                    )

                current_chunk_text.append(segment_text)
                current_chunk_segments.append(segment)
                current_length += segment_length + 1

            # Add remaining chunk
            if current_chunk_text:
                chunk_text = " ".join(current_chunk_text)

                chunks.append({
                    "text": chunk_text,
                    "metadata": {
                        "chunk_index": chunk_index,
                        "total_chunks": len(chunks) + 1,
                        "start_char": current_chunk_segments[0].get("start", 0),
                        "end_char": current_chunk_segments[-1].get("end", 0),
                        "timestamp_start": current_chunk_segments[0].get("start", 0),
                        "timestamp_end": current_chunk_segments[-1].get("end", 0),
                    }
                })

            # Update total chunks
            for chunk in chunks:
                chunk["metadata"]["total_chunks"] = len(chunks)
        else:
            # Fallback to text chunking
            chunks = self._chunk_text_content(
                document.content,
                max_chunks=max_chunks,
            )

            # Add estimated timestamps
            if document.meta_json and "duration" in document.meta_json:
                duration = document.meta_json["duration"]
                time_per_chunk = duration / len(chunks) if chunks else 0

                for i, chunk in enumerate(chunks):
                    chunk["metadata"]["timestamp_start"] = i * time_per_chunk
                    chunk["metadata"]["timestamp_end"] = (i + 1) * time_per_chunk

        return chunks

    def _iter_bounded_fragments(
        self,
        text: str,
        start: int = 0,
        stop_at_newline: bool = False,
        scan_budget: Optional[_SourceScanBudget] = None,
    ) -> Generator[_Fragment, None, int]:
        """Yield bounded sentence-aligned fragments from the original source.

        A sentence longer than ``chunk_size`` is emitted incrementally at the
        same word/comma boundary used by ``_hard_split``. This keeps the live
        path from materializing an attacker-sized sentence before its first
        chunk reaches the resource ceiling.

        Args:
            text: Original source text.
            start: Source index at which scanning begins.
            stop_at_newline: Whether a newline ends this generator.
            scan_budget: Per-plan source-work budget, when a ceiling applies.

        Returns:
            Iterator of exact source fragments no longer than ``chunk_size``.
            Its terminal value is the first source index after the line or input.
        """
        length = len(text)
        cjk_closing_pending = False

        while start < length:
            if cjk_closing_pending:
                closing_start = start
                closing_end = start
                closing_limit = min(start + self.chunk_size, length)
                while closing_end < closing_limit:
                    if self._scan_character(
                        text,
                        closing_end,
                        scan_budget=scan_budget,
                    ) not in CLOSING_MARKS:
                        break
                    closing_end += 1

                if closing_end > closing_start:
                    yield _Fragment(
                        text=text[closing_start:closing_end],
                        start=closing_start,
                        end=closing_end,
                    )
                    start = closing_end
                    if start >= length:
                        return length + 1
                    if closing_end == closing_limit:
                        continue

                cjk_closing_pending = False
                while start < length:
                    char = self._scan_character(
                        text,
                        start,
                        scan_budget=scan_budget,
                    )
                    if stop_at_newline and char == "\n":
                        return start + 1
                    if not char.isspace():
                        break
                    start += 1

            window_end = min(start + self.chunk_size, length)
            index = start

            while index < window_end:
                char = self._scan_character(
                    text,
                    index,
                    scan_budget=scan_budget,
                )
                if stop_at_newline and char == "\n":
                    fragment = self._fragment_from_bounds(
                        text,
                        start,
                        index,
                        scan_budget=scan_budget,
                    )
                    if fragment is not None:
                        yield fragment
                    return index + 1
                sentence_end = self._sentence_end_index(
                    text,
                    index,
                    start,
                    char,
                    scan_budget=scan_budget,
                )
                if sentence_end is not None:
                    closing_crosses_window = (
                        char in CJK_TERMINATORS
                        and sentence_end == window_end
                        and sentence_end < length
                    )
                    fragment = self._fragment_from_bounds(
                        text,
                        start,
                        sentence_end,
                        scan_budget=scan_budget,
                    )
                    if fragment is not None:
                        yield fragment
                    start = sentence_end
                    if closing_crosses_window:
                        cjk_closing_pending = True
                        break
                    while start < length:
                        char = self._scan_character(
                            text,
                            start,
                            scan_budget=scan_budget,
                        )
                        if stop_at_newline and char == "\n":
                            return start + 1
                        if not char.isspace():
                            break
                        start += 1
                    break
                index += 1
            else:
                if window_end == length:
                    fragment = self._fragment_from_bounds(
                        text,
                        start,
                        window_end,
                        scan_budget=scan_budget,
                    )
                    if fragment is not None:
                        yield fragment
                    return length + 1

                cut = self._hard_boundary_index(
                    text,
                    start,
                    window_end,
                    scan_budget=scan_budget,
                )
                if cut <= start or cut - start < self.chunk_size // 2:
                    cut = window_end
                fragment = self._fragment_from_bounds(
                    text,
                    start,
                    cut,
                    scan_budget=scan_budget,
                )
                if fragment is not None:
                    yield fragment
                start = cut
                while start < length:
                    char = self._scan_character(
                        text,
                        start,
                        scan_budget=scan_budget,
                    )
                    if stop_at_newline and char == "\n":
                        return start + 1
                    if not char.isspace():
                        break
                    start += 1

        return length + 1

    def _iter_sentences(self, text: str) -> Iterator[str]:
        """Yield bounded sentence-aligned fragments for compatibility.

        Args:
            text: Text to scan.

        Returns:
            Iterator of fragments no longer than ``chunk_size``.
        """
        for fragment in self._iter_bounded_fragments(text):
            yield fragment.text

    def _split_sentences(self, text: str) -> List[str]:
        """Return the sentence iterator as a compatibility list.

        Args:
            text: Text to split.

        Returns:
            List of sentences.
        """
        return list(self._iter_sentences(text))

    def get_document_chunks(
        self,
        db: Session,
        document_id: str
    ) -> List[Chunk]:
        """Get all chunks for a document, in document order.

        Args:
            db: Database session
            document_id: Document ID

        Returns:
            List of chunks
        """
        # Ordering by id would order by random UUID; offsets are monotonic.
        return db.query(Chunk).filter(
            Chunk.document_id == document_id
        ).order_by(Chunk.start_offset, Chunk.id).all()

    def search_chunks(
        self,
        db: Session,
        query: str,
        document_ids: List[str] = None,
        limit: int = 10
    ) -> List[Chunk]:
        """Search chunks by keyword.

        Args:
            db: Database session
            query: Search query
            document_ids: Optional list of document IDs to search within
            limit: Maximum number of results

        Returns:
            List of matching chunks
        """
        query_obj = db.query(Chunk)

        if document_ids:
            query_obj = query_obj.filter(Chunk.document_id.in_(document_ids))

        # Simple keyword search (can be improved with full-text search)
        query_obj = query_obj.filter(Chunk.text.contains(query))

        return query_obj.limit(limit).all()

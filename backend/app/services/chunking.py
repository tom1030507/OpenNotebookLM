"""Document chunking service."""
import re
import uuid
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple
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

DOT_PLACEHOLDER = "\x00DOT\x00"

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")

# Chunks below this are too small to answer anything on their own; they are
# merged into a neighbour rather than indexed as their own vector.
MIN_CHUNK_CHARS = 80

# Blocks are rejoined one per line, so a chunk keeps the paragraph structure the
# extractor produced.
LINE_JOIN = "\n"


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
        """
        self.chunk_size = chunk_size or settings.chunk_size
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
        blocks = self._to_blocks(text)
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

    def _to_blocks(self, text: str) -> Iterator[_Block]:
        """Split text into content lines, tracking the heading stack.

        Args:
            text: Extracted document text.

        Returns:
            Iterator of content blocks in document order.
        """
        stack: List[Tuple[int, str]] = []
        offset = 0

        while offset <= len(text):
            newline = text.find("\n", offset)
            if newline < 0:
                line = text[offset:]
                next_offset = len(text) + 1
            else:
                line = text[offset:newline]
                next_offset = newline + 1

            stripped = line.strip()
            if not stripped:
                pass
            elif heading := HEADING_RE.match(stripped):
                level = len(heading.group(1))
                while stack and stack[-1][0] >= level:
                    stack.pop()
                stack.append((level, heading.group(2)))
            else:
                start = offset + (len(line) - len(line.lstrip()))
                yield _Block(
                    text=stripped,
                    start=start,
                    end=start + len(stripped),
                    heading_path=" > ".join(title for _, title in stack),
                )

            if newline < 0:
                break
            offset = next_offset

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
        """Cut an over-long sentence near a word boundary.

        Args:
            sentence: A single sentence.

        Returns:
            Iterator of fragments no longer than `chunk_size`.
        """
        if len(sentence) <= self.chunk_size:
            yield sentence
            return

        remaining = sentence
        while len(remaining) > self.chunk_size:
            window = remaining[:self.chunk_size]
            cut = max(window.rfind(" "), window.rfind("，"), window.rfind(","))
            if cut < self.chunk_size // 2:
                cut = self.chunk_size
            fragment = remaining[:cut].strip()
            if fragment:
                yield fragment
            remaining = remaining[cut:].strip()
        if remaining:
            yield remaining

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

    def _iter_sentences(self, text: str) -> Iterator[str]:
        """Yield sentences in any of the languages this app indexes.

        Args:
            text: Text to split

        Returns:
            Iterator of sentences.
        """
        guarded = text
        for abbreviation in ABBREVIATIONS:
            guarded = re.sub(
                r"\b(%s)\." % abbreviation, r"\1" + DOT_PLACEHOLDER, guarded
            )
        # Initials such as "U.S." must not break either.
        guarded = re.sub(r"\b([A-Z])\.", r"\1" + DOT_PLACEHOLDER, guarded)

        buffer: List[str] = []
        index = 0
        length = len(guarded)

        while index < length:
            char = guarded[index]
            buffer.append(char)

            if char in CJK_TERMINATORS:
                while index + 1 < length and guarded[index + 1] in CLOSING_MARKS:
                    index += 1
                    buffer.append(guarded[index])
                sentence = "".join(buffer).replace(DOT_PLACEHOLDER, ".").strip()
                if sentence:
                    yield sentence
                buffer = []
            elif char in LATIN_TERMINATORS:
                following = guarded[index + 1:index + 2]
                if following == "" or following.isspace():
                    sentence = "".join(buffer).replace(DOT_PLACEHOLDER, ".").strip()
                    if sentence:
                        yield sentence
                    buffer = []

            index += 1

        if buffer:
            sentence = "".join(buffer).replace(DOT_PLACEHOLDER, ".").strip()
            if sentence:
                yield sentence

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

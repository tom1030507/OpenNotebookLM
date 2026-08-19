"""Document chunking service."""
import re
import uuid
from typing import List, Dict, Any, Optional, Tuple
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
        document_id: str
    ) -> List[Chunk]:
        """Chunk a document and save chunks to database.

        Args:
            db: Database session
            document_id: Document ID to chunk

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

        # Delete existing chunks through the ORM. A bulk `.delete()` bypasses the
        # cascade on Chunk.embedding and leaves embedding rows pointing at chunk
        # ids that no longer exist.
        for existing in db.query(Chunk).filter(Chunk.document_id == document_id).all():
            db.delete(existing)
        db.flush()

        # Create chunks based on document type
        if document.source_type == "pdf":
            chunks_data = self._chunk_pdf_content(document)
        elif document.source_type == "url":
            chunks_data = self._chunk_url_content(document)
        elif document.source_type == "youtube":
            chunks_data = self._chunk_youtube_content(document)
        else:
            chunks_data = self._chunk_text_content(document.content)

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
        metadata: Dict[str, Any] = None
    ) -> List[Dict[str, Any]]:
        """Chunk text, respecting section headings and sentence boundaries.

        Extraction emits `## Heading` lines, so a chunk never straddles a section
        and every chunk knows the section path it came from.

        Args:
            text: Text to chunk
            metadata: Optional metadata

        Returns:
            List of chunks with metadata
        """
        blocks = self._to_blocks(text)
        if not blocks:
            return []

        packed = self._pack(blocks)
        packed = self._merge_runts(packed)

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

    def _to_blocks(self, text: str) -> List[_Block]:
        """Split text into content lines, tracking the heading stack.

        Args:
            text: Extracted document text.

        Returns:
            Content blocks in document order.
        """
        blocks: List[_Block] = []
        stack: List[Tuple[int, str]] = []
        offset = 0

        for line in text.split("\n"):
            stripped = line.strip()
            if not stripped:
                offset += len(line) + 1
                continue

            heading = HEADING_RE.match(stripped)
            if heading:
                level = len(heading.group(1))
                while stack and stack[-1][0] >= level:
                    stack.pop()
                stack.append((level, heading.group(2)))
                offset += len(line) + 1
                continue

            start = offset + (len(line) - len(line.lstrip()))
            blocks.append(_Block(
                text=stripped,
                start=start,
                end=start + len(stripped),
                heading_path=" > ".join(title for _, title in stack),
            ))
            offset += len(line) + 1

        return blocks

    def _pack(self, blocks: List[_Block]) -> List[Tuple[str, int, int, str]]:
        """Group blocks into chunks of at most `chunk_size` characters.

        A block longer than the limit is split on sentence boundaries, and a
        sentence longer than the limit is cut at a word boundary near it — the
        previous implementation let an oversized sentence through whole, which is
        how a 4968-character chunk ended up in the index.

        Args:
            blocks: Content blocks in document order.

        Returns:
            Tuples of (text, start_offset, end_offset, heading_path).
        """
        chunks: List[Tuple[str, int, int, str]] = []
        current: List[_Block] = []
        current_len = 0

        def flush():
            nonlocal current, current_len
            if not current:
                return
            text = LINE_JOIN.join(block.text for block in current)
            chunks.append((text, current[0].start, current[-1].end, current[0].heading_path))
            current = []
            current_len = 0

        for block in blocks:
            if current and block.heading_path != current[0].heading_path:
                flush()

            for piece in self._fit(block):
                piece_len = len(piece.text)
                if current and current_len + piece_len + 1 > self.chunk_size:
                    flush()
                    # Seed the next chunk with the overlap only when the piece
                    # that triggered the flush still fits alongside it. Seeding
                    # unconditionally pushed the chunk to chunk_overlap over the
                    # limit, and an oversized chunk is silently truncated by the
                    # encoder's sequence limit -- for CJK, almost immediately.
                    overlap = self._overlap_block(chunks[-1]) if chunks else None
                    if overlap is not None and len(overlap.text) + piece_len + 1 <= self.chunk_size:
                        current = [overlap]
                        current_len = len(overlap.text)
                current.append(piece)
                current_len += piece_len + 1

        flush()
        return chunks

    def _fit(self, block: _Block) -> List[_Block]:
        """Break a block down until every piece fits the chunk size.

        Args:
            block: One content block.

        Returns:
            Blocks no longer than `chunk_size`, in order.
        """
        if len(block.text) <= self.chunk_size:
            return [block]

        pieces: List[_Block] = []
        cursor = block.start
        for sentence in self._split_sentences(block.text):
            for fragment in self._hard_split(sentence):
                pieces.append(_Block(
                    text=fragment,
                    start=cursor,
                    end=cursor + len(fragment),
                    heading_path=block.heading_path,
                ))
                cursor += len(fragment)
        return pieces or [block]

    def _hard_split(self, sentence: str) -> List[str]:
        """Cut an over-long sentence near a word boundary.

        Args:
            sentence: A single sentence.

        Returns:
            Fragments no longer than `chunk_size`.
        """
        if len(sentence) <= self.chunk_size:
            return [sentence]

        fragments = []
        remaining = sentence
        while len(remaining) > self.chunk_size:
            window = remaining[:self.chunk_size]
            cut = max(window.rfind(" "), window.rfind("，"), window.rfind(","))
            if cut < self.chunk_size // 2:
                cut = self.chunk_size
            fragments.append(remaining[:cut].strip())
            remaining = remaining[cut:].strip()
        if remaining:
            fragments.append(remaining)
        return [fragment for fragment in fragments if fragment]

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

    def _merge_runts(self, chunks: List[Tuple[str, int, int, str]]):
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

        Returns:
            Chunks with runts merged.
        """
        if len(chunks) <= 1:
            return chunks

        pending = list(chunks)
        merged: List[Tuple[str, int, int, str]] = []

        index = 0
        while index < len(pending):
            text, start, end, heading_path = pending[index]

            if len(text) >= MIN_CHUNK_CHARS:
                merged.append(pending[index])
                index += 1
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
                index += 1
                continue

            following = pending[index + 1] if index + 1 < len(pending) else None
            if (
                following
                and following[3] == heading_path
                and len(text) + len(following[0]) + 1 <= self.chunk_size
            ):
                pending[index + 1] = (
                    text + LINE_JOIN + following[0], start, following[2], heading_path,
                )
                index += 1
                continue

            merged.append(pending[index])
            index += 1

        return merged

    def _chunk_pdf_content(self, document: Document) -> List[Dict[str, Any]]:
        """Chunk PDF content, preserving page information.

        Args:
            document: Document object

        Returns:
            List of chunks with metadata
        """
        chunks = self._chunk_text_content(document.content)

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

    def _chunk_url_content(self, document: Document) -> List[Dict[str, Any]]:
        """Chunk URL content, preserving structure information.

        Args:
            document: Document object

        Returns:
            List of chunks with metadata
        """
        chunks = self._chunk_text_content(document.content)

        # Fall back to the page title when a chunk sits above the first heading,
        # so a citation always has something to show. Chunks inside a section
        # keep the real heading path built by `_to_blocks`.
        title = (document.meta_json or {}).get("metadata", {}).get("title") or document.title
        for chunk in chunks:
            if not chunk["metadata"].get("heading_path") and title:
                chunk["metadata"]["heading_path"] = title

        return chunks

    def _chunk_youtube_content(self, document: Document) -> List[Dict[str, Any]]:
        """Chunk YouTube transcript, preserving timestamps.

        Args:
            document: Document object

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
            chunks = self._chunk_text_content(document.content)

            # Add estimated timestamps
            if document.meta_json and "duration" in document.meta_json:
                duration = document.meta_json["duration"]
                time_per_chunk = duration / len(chunks) if chunks else 0

                for i, chunk in enumerate(chunks):
                    chunk["metadata"]["timestamp_start"] = i * time_per_chunk
                    chunk["metadata"]["timestamp_end"] = (i + 1) * time_per_chunk

        return chunks

    def _split_sentences(self, text: str) -> List[str]:
        """Split text into sentences, in any of the languages this app indexes.

        Args:
            text: Text to split

        Returns:
            List of sentences
        """
        guarded = text
        for abbreviation in ABBREVIATIONS:
            guarded = re.sub(
                r"\b(%s)\." % abbreviation, r"\1" + DOT_PLACEHOLDER, guarded
            )
        # Initials such as "U.S." must not break either.
        guarded = re.sub(r"\b([A-Z])\.", r"\1" + DOT_PLACEHOLDER, guarded)

        sentences: List[str] = []
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
                sentences.append("".join(buffer))
                buffer = []
            elif char in LATIN_TERMINATORS:
                following = guarded[index + 1:index + 2]
                if following == "" or following.isspace():
                    sentences.append("".join(buffer))
                    buffer = []

            index += 1

        if buffer:
            sentences.append("".join(buffer))

        return [
            sentence.replace(DOT_PLACEHOLDER, ".").strip()
            for sentence in sentences
            if sentence.strip()
        ]

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

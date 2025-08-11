"""Document chunking service."""
import re
import uuid
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, asdict
import structlog
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import Document, Chunk

logger = structlog.get_logger()
settings = get_settings()


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
        self.chunk_overlap = chunk_overlap or settings.chunk_overlap
    
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
        
        # Delete existing chunks
        db.query(Chunk).filter(Chunk.document_id == document_id).delete()
        
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
        """Chunk plain text using sentence boundaries.
        
        Args:
            text: Text to chunk
            metadata: Optional metadata
            
        Returns:
            List of chunks with metadata
        """
        chunks = []
        
        # Split into sentences
        sentences = self._split_sentences(text)
        
        if not sentences:
            return []
        
        current_chunk = []
        current_length = 0
        chunk_index = 0
        char_position = 0
        
        for sentence in sentences:
            sentence_length = len(sentence)
            
            # If adding this sentence exceeds chunk size, save current chunk
            if current_length + sentence_length > self.chunk_size and current_chunk:
                chunk_text = " ".join(current_chunk)
                chunk_start = char_position - current_length
                
                chunks.append({
                    "text": chunk_text,
                    "metadata": ChunkMetadata(
                        chunk_index=chunk_index,
                        total_chunks=0,  # Will be updated later
                        start_char=chunk_start,
                        end_char=char_position
                    )
                })
                
                # Handle overlap
                if self.chunk_overlap > 0 and len(current_chunk) > 1:
                    # Keep last sentence for overlap
                    overlap_sentence = current_chunk[-1]
                    current_chunk = [overlap_sentence]
                    current_length = len(overlap_sentence)
                else:
                    current_chunk = []
                    current_length = 0
                
                chunk_index += 1
            
            current_chunk.append(sentence)
            current_length += sentence_length + 1  # +1 for space
            char_position += sentence_length + 1
        
        # Add remaining chunk
        if current_chunk:
            chunk_text = " ".join(current_chunk)
            chunk_start = char_position - current_length
            
            chunks.append({
                "text": chunk_text,
                "metadata": ChunkMetadata(
                    chunk_index=chunk_index,
                    total_chunks=0,
                    start_char=chunk_start,
                    end_char=char_position
                )
            })
        
        # Update total chunks count and convert metadata to dict
        for chunk in chunks:
            chunk["metadata"].total_chunks = len(chunks)
            chunk["metadata"] = asdict(chunk["metadata"])
        
        return chunks
    
    def _chunk_pdf_content(self, document: Document) -> List[Dict[str, Any]]:
        """Chunk PDF content, preserving page information.
        
        Args:
            document: Document object
            
        Returns:
            List of chunks with metadata
        """
        chunks = self._chunk_text_content(document.content)
        
        # Add PDF-specific metadata from document meta_json
        if document.meta_json and "pages" in document.meta_json:
            pages = document.meta_json["pages"]
            if pages:
                # Simple distribution of chunks across pages
                total_pages = len(pages)
                chunks_per_page = max(1, len(chunks) // total_pages)
                
                for i, chunk in enumerate(chunks):
                    page_num = min(i // chunks_per_page + 1, total_pages)
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
        
        # Add URL-specific metadata
        if document.meta_json:
            for chunk in chunks:
                if "headings" in document.meta_json:
                    # Could implement heading-aware chunking here
                    chunk["metadata"]["section"] = "content"
                if "title" in document.meta_json:
                    chunk["metadata"]["heading_path"] = document.meta_json.get("title", "")
        
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
        """Split text into sentences.
        
        Args:
            text: Text to split
            
        Returns:
            List of sentences
        """
        # Handle common abbreviations
        text = re.sub(r'\b(Dr|Mr|Mrs|Ms|Prof|Sr|Jr)\.\s*', r'\1<DOT> ', text)
        
        # Split on sentence boundaries
        sentences = re.split(r'(?<=[.!?])\s+(?=[A-Z])', text)
        
        # Restore dots
        sentences = [s.replace('<DOT>', '.') for s in sentences]
        
        # Filter out empty sentences and clean up
        sentences = [s.strip() for s in sentences if s.strip()]
        
        return sentences
    
    def get_document_chunks(
        self,
        db: Session,
        document_id: str
    ) -> List[Chunk]:
        """Get all chunks for a document.
        
        Args:
            db: Database session
            document_id: Document ID
            
        Returns:
            List of chunks
        """
        return db.query(Chunk).filter(
            Chunk.document_id == document_id
        ).order_by(Chunk.id).all()
    
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

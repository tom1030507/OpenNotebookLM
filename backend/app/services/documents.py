"""Document ingestion service."""
import uuid
import os
from typing import Dict, Optional, BinaryIO
from pathlib import Path
import asyncio
from concurrent.futures import ThreadPoolExecutor
import structlog
from sqlalchemy.orm import Session

from app.db.models import Document, Project, ProjectDocument
from app.schemas import DocumentCreate
from app.adapters import PDFAdapter, URLAdapter, YouTubeAdapter
from app.config import get_settings
from app.services.chunking import ChunkingService
from app.services.document_files import UPLOAD_DIR
from app.services.embeddings import EmbeddingService
from app.utils.time import utc_now_iso

logger = structlog.get_logger()
settings = get_settings()


class DocumentService:
    """Service for document ingestion and processing."""
    
    def __init__(self, chunking_service=None, embedding_service=None):
        """Initialize document service.

        Args:
            chunking_service: Optional chunking service, mainly so tests can
                run without the embedding model
            embedding_service: Optional embedding service, same reason
        """
        self.pdf_adapter = PDFAdapter(use_pymupdf=False)  # Use pdfminer for now
        self.url_adapter = URLAdapter()
        self.youtube_adapter = None  # Initialize only if needed
        self.executor = ThreadPoolExecutor(max_workers=4)
        self.chunking_service = chunking_service or ChunkingService()
        self.embedding_service = embedding_service or EmbeddingService()

    def _index_document(self, db: Session, doc_id: str, source_label: str) -> str:
        """Chunk and embed a document, then mark it ready.

        "ready" is what the UI trusts before it lets anyone query a source, so
        it is only committed once the chunks and their embeddings exist.
        Committing it any earlier leaves a window where the composer is enabled
        but every question is answered from nothing.

        Args:
            db: Database session
            doc_id: Document ID
            source_label: Source kind, used in log messages

        Returns:
            The status the document ended up in
        """
        try:
            chunks = self.chunking_service.chunk_document(db, doc_id)
            logger.info(f"Created {len(chunks)} chunks for {source_label} document {doc_id}")

            embeddings = self.embedding_service.embed_chunks(db, doc_id)
            logger.info(f"Generated {len(embeddings)} embeddings for {source_label} document {doc_id}")
        except Exception as e:
            logger.error(f"Failed to chunk/embed {source_label} document: {e}")
            return self._mark_failed(db, doc_id, f"Indexing failed: {e}")

        # Without embeddings the source is not searchable, so calling it ready
        # would be the same lie in a different place.
        if not embeddings:
            return self._mark_failed(
                db,
                doc_id,
                "No searchable text could be extracted, so this source cannot be queried."
            )

        doc = db.query(Document).filter(Document.id == doc_id).first()
        if doc:
            doc.status = "ready"
            doc.error_message = None
            db.commit()

        return "ready"

    def _mark_failed(self, db: Session, doc_id: str, message: str) -> str:
        """Record that a document cannot be used, discarding partial work.

        Args:
            db: Database session
            doc_id: Document ID
            message: Message to show the user

        Returns:
            The status the document ended up in
        """
        db.rollback()

        doc = db.query(Document).filter(Document.id == doc_id).first()
        if doc:
            doc.status = "error"
            doc.error_message = message
            db.commit()

        return "error"

    async def process_pdf_upload(
        self,
        db: Session,
        project_id: str,
        file: BinaryIO,
        filename: str,
        title: Optional[str] = None
    ) -> Document:
        """Process PDF file upload.
        
        Args:
            db: Database session
            project_id: Project ID
            file: File object
            filename: Original filename
            title: Optional document title
            
        Returns:
            Created document
        """
        try:
            # Generate document ID
            doc_id = str(uuid.uuid4())
            
            # Save file to disk
            file_path = UPLOAD_DIR / f"{doc_id}_{filename}"
            content = file.read()  # BinaryIO is not async
            
            with open(file_path, "wb") as f:
                f.write(content)
            
            # Create document record with queued status
            document = Document(
                id=doc_id,
                title=title or filename,
                source_type="pdf",
                source_url=str(file_path),
                status="queued",
                meta_json={
                    "filename": filename,
                    "file_size": len(content),
                    "upload_time": utc_now_iso(),
                }
            )
            
            db.add(document)
            
            # Link to project
            project_doc = ProjectDocument(
                project_id=project_id,
                document_id=doc_id
            )
            db.add(project_doc)
            
            db.commit()
            db.refresh(document)
            
            # Process asynchronously
            asyncio.create_task(self._process_pdf_async(db, doc_id, file_path))
            
            logger.info("PDF upload initiated", 
                       doc_id=doc_id, 
                       filename=filename,
                       project_id=project_id)
            
            return document
            
        except Exception as e:
            logger.error("Failed to process PDF upload", 
                        filename=filename, 
                        error=str(e))
            raise
    
    async def _process_pdf_async(self, db: Session, doc_id: str, file_path: Path):
        """Process PDF file asynchronously.
        
        Args:
            db: Database session
            doc_id: Document ID
            file_path: Path to PDF file
        """
        try:
            # Update status to processing
            doc = db.query(Document).filter(Document.id == doc_id).first()
            if doc:
                doc.status = "processing"
                db.commit()
            
            # Extract text in thread pool
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                self.executor,
                self.pdf_adapter.extract_text_from_file,
                str(file_path)
            )
            
            # Store the extracted content, staying in "processing": the source
            # is not usable until it has been indexed below.
            doc = db.query(Document).filter(Document.id == doc_id).first()
            if doc:
                doc.content = result["text"]
                # Reassign rather than mutate: meta_json is a plain JSON
                # column, so an in-place update is invisible to SQLAlchemy and
                # never reaches the database.
                doc.meta_json = {
                    **(doc.meta_json or {}),
                    "num_pages": result["num_pages"],
                    # Keep the per-page text. Dropping it was the only reason
                    # Chunk.page_num was NULL for every PDF: the chunker has the
                    # code to map offsets to pages, it just never had the pages.
                    "pages": result.get("pages", []),
                    "metadata": result.get("metadata", {}),
                    "processed_at": utc_now_iso(),
                }
                db.commit()

                status = self._index_document(db, doc_id, "PDF")

                logger.info("PDF processing completed",
                           doc_id=doc_id,
                           num_pages=result["num_pages"],
                           status=status)
            
        except Exception as e:
            logger.error("Failed to process PDF",
                        doc_id=doc_id,
                        error=str(e))
            
            # Update status to error
            doc = db.query(Document).filter(Document.id == doc_id).first()
            if doc:
                doc.status = "error"
                doc.error_message = str(e)
                db.commit()
    
    async def process_url(
        self,
        db: Session,
        project_id: str,
        url: str,
        title: Optional[str] = None
    ) -> Document:
        """Process URL content extraction.
        
        Args:
            db: Database session
            project_id: Project ID
            url: URL to extract content from
            title: Optional document title
            
        Returns:
            Created document
        """
        try:
            # Generate document ID
            doc_id = str(uuid.uuid4())
            
            # Create document record with queued status
            document = Document(
                id=doc_id,
                title=title or url,
                source_type="url",
                source_url=url,
                status="queued",
                meta_json={
                    "url": url,
                    "upload_time": utc_now_iso(),
                }
            )
            
            db.add(document)
            
            # Link to project
            project_doc = ProjectDocument(
                project_id=project_id,
                document_id=doc_id
            )
            db.add(project_doc)
            
            db.commit()
            db.refresh(document)
            
            # Process asynchronously
            asyncio.create_task(self._process_url_async(db, doc_id, url))
            
            logger.info("URL processing initiated",
                       doc_id=doc_id,
                       url=url,
                       project_id=project_id)
            
            return document
            
        except Exception as e:
            logger.error("Failed to process URL",
                        url=url,
                        error=str(e))
            raise
    
    async def _process_url_async(self, db: Session, doc_id: str, url: str):
        """Process URL asynchronously.
        
        Args:
            db: Database session
            doc_id: Document ID
            url: URL to process
        """
        try:
            # Update status to processing
            doc = db.query(Document).filter(Document.id == doc_id).first()
            if doc:
                doc.status = "processing"
                db.commit()
            
            # Extract content in thread pool
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                self.executor,
                self.url_adapter.extract_content,
                url
            )
            
            # Store the extracted content, staying in "processing": the source
            # is not usable until it has been indexed below.
            doc = db.query(Document).filter(Document.id == doc_id).first()
            if doc:
                doc.content = result["text"]
                doc.title = result.get("title", url)
                # Reassign rather than mutate: meta_json is a plain JSON
                # column, so an in-place update is invisible to SQLAlchemy and
                # never reaches the database.
                doc.meta_json = {
                    **(doc.meta_json or {}),
                    "metadata": result.get("metadata", {}),
                    "headings": result.get("headings", []),
                    "num_links": len(result.get("links", [])),
                    "processed_at": utc_now_iso(),
                }
                db.commit()

                status = self._index_document(db, doc_id, "URL")

                logger.info("URL processing completed",
                           doc_id=doc_id,
                           url=url,
                           status=status)
            
        except Exception as e:
            logger.error("Failed to process URL",
                        doc_id=doc_id,
                        url=url,
                        error=str(e))
            
            # Update status to error
            doc = db.query(Document).filter(Document.id == doc_id).first()
            if doc:
                doc.status = "error"
                doc.error_message = str(e)
                db.commit()
    
    async def process_youtube(
        self,
        db: Session,
        project_id: str,
        youtube_url: str,
        title: Optional[str] = None
    ) -> Document:
        """Process YouTube video transcript.
        
        Args:
            db: Database session
            project_id: Project ID
            youtube_url: YouTube video URL
            title: Optional document title
            
        Returns:
            Created document
        """
        try:
            # Initialize YouTube adapter if needed
            if not self.youtube_adapter:
                self.youtube_adapter = YouTubeAdapter()
            
            # Generate document ID
            doc_id = str(uuid.uuid4())
            
            # Create document record with queued status
            document = Document(
                id=doc_id,
                title=title or youtube_url,
                source_type="youtube",
                source_url=youtube_url,
                status="queued",
                meta_json={
                    "youtube_url": youtube_url,
                    "upload_time": utc_now_iso(),
                }
            )
            
            db.add(document)
            
            # Link to project
            project_doc = ProjectDocument(
                project_id=project_id,
                document_id=doc_id
            )
            db.add(project_doc)
            
            db.commit()
            db.refresh(document)
            
            # Process asynchronously
            asyncio.create_task(self._process_youtube_async(db, doc_id, youtube_url))
            
            logger.info("YouTube processing initiated",
                       doc_id=doc_id,
                       youtube_url=youtube_url,
                       project_id=project_id)
            
            return document
            
        except Exception as e:
            logger.error("Failed to process YouTube URL",
                        youtube_url=youtube_url,
                        error=str(e))
            raise
    
    async def _process_youtube_async(self, db: Session, doc_id: str, youtube_url: str):
        """Process YouTube video asynchronously.
        
        Args:
            db: Database session
            doc_id: Document ID
            youtube_url: YouTube URL
        """
        try:
            # Update status to processing
            doc = db.query(Document).filter(Document.id == doc_id).first()
            if doc:
                doc.status = "processing"
                db.commit()
            
            # Extract transcript in thread pool
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                self.executor,
                self.youtube_adapter.extract_transcript,
                youtube_url
            )
            
            # Store the extracted content, staying in "processing": the source
            # is not usable until it has been indexed below.
            doc = db.query(Document).filter(Document.id == doc_id).first()
            if doc:
                doc.content = result["text"]
                doc.title = f"YouTube: {result.get('video_id', youtube_url)}"
                # Reassign rather than mutate: meta_json is a plain JSON
                # column, so an in-place update is invisible to SQLAlchemy and
                # never reaches the database.
                doc.meta_json = {
                    **(doc.meta_json or {}),
                    "video_id": result.get("video_id"),
                    "duration": result.get("duration", 0),
                    "language": result.get("language", "unknown"),
                    "metadata": result.get("metadata", {}),
                    "num_segments": len(result.get("segments", [])),
                    "processed_at": utc_now_iso(),
                }
                db.commit()

                status = self._index_document(db, doc_id, "YouTube")

                logger.info("YouTube processing completed",
                           doc_id=doc_id,
                           video_id=result.get("video_id"),
                           status=status)
            
        except Exception as e:
            logger.error("Failed to process YouTube video",
                        doc_id=doc_id,
                        youtube_url=youtube_url,
                        error_type=type(e).__name__,
                        error=str(e))
            
            # Update status to error
            doc = db.query(Document).filter(Document.id == doc_id).first()
            if doc:
                doc.status = "error"
                doc.error_message = str(e)
                db.commit()
    
    def get_document_status(self, db: Session, doc_id: str) -> Optional[Document]:
        """Get document processing status.
        
        Args:
            db: Database session
            doc_id: Document ID
            
        Returns:
            Document or None
        """
        return db.query(Document).filter(Document.id == doc_id).first()
    
    def delete_document(self, db: Session, doc_id: str) -> bool:
        """Delete a document.
        
        Args:
            db: Database session
            doc_id: Document ID
            
        Returns:
            True if deleted, False if not found
        """
        doc = db.query(Document).filter(Document.id == doc_id).first()
        
        if not doc:
            return False
        
        # Delete file if it's a PDF
        if doc.source_type == "pdf" and doc.source_url:
            file_path = Path(doc.source_url)
            if file_path.exists():
                try:
                    file_path.unlink()
                except Exception as e:
                    logger.warning("Failed to delete file",
                                 file_path=str(file_path),
                                 error=str(e))
        
        # Delete from database (cascade will handle related records)
        db.delete(doc)
        db.commit()
        
        logger.info("Document deleted", doc_id=doc_id)
        return True

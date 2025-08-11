"""Document ingestion service."""
import uuid
import os
from typing import Dict, Optional, BinaryIO
from pathlib import Path
from datetime import datetime
import asyncio
from concurrent.futures import ThreadPoolExecutor
import structlog
from sqlalchemy.orm import Session

from app.db.models import Document, Project, ProjectDocument
from app.schemas import DocumentCreate
from app.adapters import PDFAdapter, URLAdapter, YouTubeAdapter
from app.config import get_settings
from app.services.chunking import ChunkingService
from app.services.embeddings import EmbeddingService

logger = structlog.get_logger()
settings = get_settings()

# Create uploads directory if it doesn't exist
UPLOAD_DIR = Path("./uploads")
UPLOAD_DIR.mkdir(exist_ok=True)


class DocumentService:
    """Service for document ingestion and processing."""
    
    def __init__(self):
        """Initialize document service."""
        self.pdf_adapter = PDFAdapter(use_pymupdf=False)  # Use pdfminer for now
        self.url_adapter = URLAdapter()
        self.youtube_adapter = None  # Initialize only if needed
        self.executor = ThreadPoolExecutor(max_workers=4)
        self.chunking_service = ChunkingService()
        self.embedding_service = EmbeddingService()
    
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
                    "upload_time": datetime.utcnow().isoformat(),
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
            
            # Update document with extracted content
            doc = db.query(Document).filter(Document.id == doc_id).first()
            if doc:
                doc.content = result["text"]
                doc.status = "ready"
                doc.meta_json.update({
                    "num_pages": result["num_pages"],
                    "metadata": result.get("metadata", {}),
                    "processed_at": datetime.utcnow().isoformat(),
                })
                db.commit()
                
                # Create chunks
                try:
                    chunks = self.chunking_service.chunk_document(db, doc_id)
                    logger.info(f"Created {len(chunks)} chunks for PDF document {doc_id}")
                    
                    # Generate embeddings
                    embeddings = self.embedding_service.embed_chunks(db, doc_id)
                    logger.info(f"Generated {len(embeddings)} embeddings for PDF document {doc_id}")
                except Exception as e:
                    logger.error(f"Failed to chunk/embed PDF document: {e}")
                
                logger.info("PDF processing completed",
                           doc_id=doc_id,
                           num_pages=result["num_pages"])
            
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
                    "upload_time": datetime.utcnow().isoformat(),
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
            
            # Update document with extracted content
            doc = db.query(Document).filter(Document.id == doc_id).first()
            if doc:
                doc.content = result["text"]
                doc.title = result.get("title", url)
                doc.status = "ready"
                doc.meta_json.update({
                    "metadata": result.get("metadata", {}),
                    "headings": result.get("headings", []),
                    "num_links": len(result.get("links", [])),
                    "processed_at": datetime.utcnow().isoformat(),
                })
                db.commit()
                
                # Create chunks
                try:
                    chunks = self.chunking_service.chunk_document(db, doc_id)
                    logger.info(f"Created {len(chunks)} chunks for URL document {doc_id}")
                    
                    # Generate embeddings
                    embeddings = self.embedding_service.embed_chunks(db, doc_id)
                    logger.info(f"Generated {len(embeddings)} embeddings for URL document {doc_id}")
                except Exception as e:
                    logger.error(f"Failed to chunk/embed URL document: {e}")
                
                logger.info("URL processing completed",
                           doc_id=doc_id,
                           url=url)
            
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
                    "upload_time": datetime.utcnow().isoformat(),
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
            
            # Update document with extracted content
            doc = db.query(Document).filter(Document.id == doc_id).first()
            if doc:
                doc.content = result["text"]
                doc.title = f"YouTube: {result.get('video_id', youtube_url)}"
                doc.status = "ready"
                doc.meta_json.update({
                    "video_id": result.get("video_id"),
                    "duration": result.get("duration", 0),
                    "language": result.get("language", "unknown"),
                    "metadata": result.get("metadata", {}),
                    "num_segments": len(result.get("segments", [])),
                    "processed_at": datetime.utcnow().isoformat(),
                })
                db.commit()
                
                # Create chunks
                try:
                    chunks = self.chunking_service.chunk_document(db, doc_id)
                    logger.info(f"Created {len(chunks)} chunks for YouTube document {doc_id}")
                    
                    # Generate embeddings
                    embeddings = self.embedding_service.embed_chunks(db, doc_id)
                    logger.info(f"Generated {len(embeddings)} embeddings for YouTube document {doc_id}")
                except Exception as e:
                    logger.error(f"Failed to chunk/embed YouTube document: {e}")
                
                logger.info("YouTube processing completed",
                           doc_id=doc_id,
                           video_id=result.get("video_id"))
            
        except Exception as e:
            logger.error("Failed to process YouTube video",
                        doc_id=doc_id,
                        youtube_url=youtube_url,
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

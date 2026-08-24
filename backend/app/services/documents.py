"""Document ingestion service."""
import uuid
import os
from typing import BinaryIO, Dict, Optional
from pathlib import Path
import asyncio
from concurrent.futures import ThreadPoolExecutor
import structlog
from sqlalchemy.orm import Session

from app.db.models import Chunk, Document, Project, ProjectDocument
from app.schemas import DocumentCreate
from app.adapters import PDFAdapter, URLAdapter, YouTubeAdapter
from app.config import get_settings
from app.services.chunking import ChunkingService
from app.services.document_files import UPLOAD_DIR
from app.services.embeddings import EmbeddingService
from app.services.rate_limit import OperationLease, UnlimitedConcurrencyLease
from app.utils.time import utc_now_iso

logger = structlog.get_logger()
PDF_UPLOAD_BLOCK_BYTES = 1024 * 1024
CHUNK_LIMIT_CLEANUP_ATTEMPTS = 2


class UploadTooLargeError(ValueError):
    """Raised when an upload crosses the configured byte limit."""


class ChunkLimitPersistenceError(RuntimeError):
    """Raised when an over-limit chunk set cannot be atomically cleaned up."""


def _operation_lease(lease: Optional[OperationLease]) -> OperationLease:
    """Return a concrete operation ownership handle."""
    return lease if lease is not None else UnlimitedConcurrencyLease()


class DocumentService:
    """Service for document ingestion and processing."""
    
    def __init__(
        self,
        chunking_service=None,
        embedding_service=None,
        max_chunks_per_doc: Optional[int] = None,
    ):
        """Initialize document service.

        Args:
            chunking_service: Optional chunking service, mainly so tests can
                run without the embedding model
            embedding_service: Optional embedding service, same reason
            max_chunks_per_doc: Optional hard ceiling override. The application
                setting defaults to exactly 1000.

        Returns:
            None.
        """
        self.settings = get_settings()
        self.pdf_adapter = PDFAdapter(use_pymupdf=False)  # Use pdfminer for now
        self.url_adapter = URLAdapter(
            timeout=self.settings.url_read_timeout_seconds,
            connect_timeout=self.settings.url_connect_timeout_seconds,
            max_download_bytes=self.settings.max_url_download_mb * 1024 * 1024,
            max_redirects=self.settings.max_url_redirects,
            max_download_seconds=self.settings.url_download_timeout_seconds,
        )
        self.youtube_adapter = None  # Initialize only if needed
        self.executor = ThreadPoolExecutor(max_workers=4)
        self.chunking_service = chunking_service or ChunkingService()
        self.embedding_service = embedding_service or EmbeddingService()
        self.max_chunks_per_doc = (
            max_chunks_per_doc
            if max_chunks_per_doc is not None
            else self.settings.max_chunks_per_doc
        )

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

            if len(chunks) > self.max_chunks_per_doc:
                return self._mark_chunk_limit_failed(db, doc_id, len(chunks))

            embeddings = self.embedding_service.embed_chunks(db, doc_id)
            logger.info(f"Generated {len(embeddings)} embeddings for {source_label} document {doc_id}")
        except ChunkLimitPersistenceError:
            # A status-only fallback would retain the already committed chunk
            # rows. Preserve the dedicated failure so the caller can surface a
            # database incident without pretending cleanup succeeded.
            raise
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

    def _mark_chunk_limit_failed(
        self,
        db: Session,
        doc_id: str,
        chunk_count: int,
    ) -> str:
        """Remove committed over-limit chunks and atomically record the failure.

        The chunking service owns its own commit, so a rollback here cannot
        remove its rows. Deleting them in the same transaction that updates the
        document prevents a failed source from retaining an attacker-sized
        chunk set or exposing a failed status without its actionable metadata.

        Args:
            db: Database session.
            doc_id: Document id that exceeded the ceiling.
            chunk_count: Number of chunks the chunker committed.

        Returns:
            The status the document ended up in.
        """
        action = "Reduce the source size or increase CHUNK_SIZE before retrying."
        message = (
            f"Document produced {chunk_count} chunks, exceeding the limit of "
            f"{self.max_chunks_per_doc}. {action}"
        )

        last_error = None
        for attempt in range(1, CHUNK_LIMIT_CLEANUP_ATTEMPTS + 1):
            try:
                # Re-read and re-delete on every attempt. A rollback after a
                # failed commit restores both the rows and the document, so
                # retrying only commit would falsely report a clean database.
                for chunk in (
                    db.query(Chunk)
                    .filter(Chunk.document_id == doc_id)
                    .all()
                ):
                    db.delete(chunk)

                doc = db.query(Document).filter(Document.id == doc_id).first()
                if doc:
                    doc.status = "error"
                    doc.error_message = message
                    # SQLAlchemy cannot detect an in-place mutation of this
                    # plain JSON column, which would commit the status without
                    # the actionable reason.
                    doc.meta_json = {
                        **(doc.meta_json or {}),
                        "indexing_failure": {
                            "code": "chunk_limit_exceeded",
                            "chunk_count": chunk_count,
                            "max_chunks": self.max_chunks_per_doc,
                            "action": action,
                        },
                    }
                db.commit()
                break
            except Exception as error:
                last_error = error
                try:
                    db.rollback()
                except Exception as rollback_error:
                    # A failed rollback leaves transaction state unknown. Any
                    # retry or status-only fallback could commit only part of
                    # the cleanup, so normalize immediately to the dedicated
                    # path that every caller already treats as non-recoverable.
                    logger.error(
                        "Failed to rollback chunk-limit cleanup",
                        document_id=doc_id,
                        commit_error=str(error),
                        rollback_error=str(rollback_error),
                    )
                    raise ChunkLimitPersistenceError(
                        "Could not safely rollback over-limit cleanup for "
                        f"document {doc_id} after persistence failure: {error}"
                    ) from rollback_error
                logger.warning(
                    "Failed to persist chunk-limit cleanup",
                    document_id=doc_id,
                    attempt=attempt,
                    max_attempts=CHUNK_LIMIT_CLEANUP_ATTEMPTS,
                    error=str(error),
                )
        else:
            raise ChunkLimitPersistenceError(
                f"Could not persist over-limit cleanup for document {doc_id} "
                f"after {CHUNK_LIMIT_CLEANUP_ATTEMPTS} attempts"
            ) from last_error

        logger.warning(
            "Document exceeded chunk limit",
            document_id=doc_id,
            chunk_count=chunk_count,
            max_chunks=self.max_chunks_per_doc,
        )
        return "error"

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
        user_id: str,
        file: BinaryIO,
        filename: str,
        title: Optional[str] = None,
        operation_lease: Optional[OperationLease] = None,
    ) -> Document:
        """Process PDF file upload.
        
        Args:
            db: Database session
            project_id: Project ID
            user_id: Account that will own the document
            file: File object
            filename: Original filename
            title: Optional document title
            operation_lease: Explicit quota ownership transferred to this
                service until background extraction/indexing really finishes.
            
        Returns:
            Created document
        """
        lease = _operation_lease(operation_lease)
        file_path = None
        retained = False
        try:
            # Generate document ID
            doc_id = str(uuid.uuid4())
            
            # Save file to disk. Reading without a size would duplicate the
            # entire multipart spool in RAM before the limit could be checked.
            file_path = UPLOAD_DIR / f"{doc_id}_{filename}"
            with open(file_path, "wb") as f:
                file_size = 0
                while True:
                    block = file.read(PDF_UPLOAD_BLOCK_BYTES)
                    if not block:
                        break
                    if file_size + len(block) > self.settings.max_file_size_bytes:
                        raise UploadTooLargeError(
                            "File size exceeds maximum of %sMB"
                            % self.settings.max_file_size_mb
                        )
                    f.write(block)
                    file_size += len(block)
            
            # Create document record with queued status
            document = Document(
                id=doc_id,
                user_id=user_id,
                title=title or filename,
                source_type="pdf",
                source_url=str(file_path),
                status="queued",
                meta_json={
                    "filename": filename,
                    "file_size": file_size,
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
            retained = True
            
            # Process asynchronously
            task = asyncio.create_task(self._process_pdf_async(
                db,
                doc_id,
                file_path,
                operation_lease=lease,
            ))
            # A task cancelled before its coroutine ever starts cannot execute
            # its finally block, so the submitted task is also an owner edge.
            task.add_done_callback(lambda _task: lease.release())
            
            logger.info("PDF upload initiated", 
                       doc_id=doc_id, 
                       filename=filename,
                       project_id=project_id)
            
            return document
            
        except Exception as e:
            lease.release()
            if file_path is not None and not retained:
                file_path.unlink(missing_ok=True)
            logger.error("Failed to process PDF upload", 
                        filename=filename, 
                        error=str(e))
            raise
    
    async def _process_pdf_async(
        self,
        db: Session,
        doc_id: str,
        file_path: Path,
        operation_lease: Optional[OperationLease] = None,
    ):
        """Process PDF file asynchronously.
        
        Args:
            db: Database session
            doc_id: Document ID
            file_path: Path to PDF file
            operation_lease: Quota ownership released only after this task and
                any uncancellable executor work finish.
        """
        lease = _operation_lease(operation_lease)
        extraction_future = None
        try:
            # Update status to processing
            doc = db.query(Document).filter(Document.id == doc_id).first()
            if doc:
                doc.status = "processing"
                db.commit()
            
            # Extract text in thread pool
            extraction_future = self.executor.submit(
                self.pdf_adapter.extract_text_from_file,
                str(file_path)
            )
            try:
                result = await asyncio.shield(
                    asyncio.wrap_future(extraction_future)
                )
            except asyncio.CancelledError:
                lease.defer_release_until(extraction_future)
                raise
            
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
            
        except asyncio.CancelledError:
            raise
        except ChunkLimitPersistenceError:
            logger.critical(
                "PDF chunk-limit cleanup could not be persisted",
                doc_id=doc_id,
            )
            raise
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
        finally:
            lease.release()
    
    async def process_url(
        self,
        db: Session,
        project_id: str,
        user_id: str,
        url: str,
        title: Optional[str] = None,
        operation_lease: Optional[OperationLease] = None,
    ) -> Document:
        """Process URL content extraction.
        
        Args:
            db: Database session
            project_id: Project ID
            user_id: Account that will own the document
            url: URL to extract content from
            title: Optional document title
            operation_lease: Explicit quota ownership transferred to this
                service through fetch and background indexing completion.
            
        Returns:
            Created document
        """
        lease = _operation_lease(operation_lease)
        extraction_future = None
        try:
            # Fetch before creating a database row so SSRF/content/size
            # refusals reach the HTTP caller as 4xx instead of becoming an
            # orphaned queued document whose background task later fails.
            if hasattr(self.url_adapter, "start_extract_content"):
                operation = self.url_adapter.start_extract_content(url)
                extraction_future = operation.future
                extracted = await operation.wait()
            else:
                # Non-network test/recovery adapters retain the same ownership
                # semantics even though production uses URLFetchOperation.
                extraction_future = self.executor.submit(
                    self.url_adapter.extract_content,
                    url,
                )
                extracted = await asyncio.shield(
                    asyncio.wrap_future(extraction_future)
                )

            # Generate document ID
            doc_id = str(uuid.uuid4())
            
            # Create document record with queued status
            document = Document(
                id=doc_id,
                user_id=user_id,
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
            task = asyncio.create_task(
                self._process_url_async(
                    db,
                    doc_id,
                    url,
                    extracted=extracted,
                    operation_lease=lease,
                )
            )
            task.add_done_callback(lambda _task: lease.release())
            
            logger.info("URL processing initiated",
                       doc_id=doc_id,
                       url=url,
                       project_id=project_id)
            
            return document
            
        except asyncio.CancelledError:
            if extraction_future is not None:
                lease.defer_release_until(extraction_future)
            lease.release()
            raise
        except Exception as e:
            if extraction_future is not None and not extraction_future.done():
                lease.defer_release_until(extraction_future)
            lease.release()
            logger.error("Failed to process URL",
                        url=url,
                        error=str(e))
            raise
    
    async def _process_url_async(
        self,
        db: Session,
        doc_id: str,
        url: str,
        extracted: Optional[Dict] = None,
        operation_lease: Optional[OperationLease] = None,
    ):
        """Process URL asynchronously.
        
        Args:
            db: Database session
            doc_id: Document ID
            url: URL to process
            extracted: Content already fetched at the request boundary. Tests
                and recovery callers may omit it to perform extraction here.
            operation_lease: Quota ownership released only after this task and
                any uncancellable executor work finish.
        """
        lease = _operation_lease(operation_lease)
        extraction_future = None
        try:
            # Update status to processing
            doc = db.query(Document).filter(Document.id == doc_id).first()
            if doc:
                doc.status = "processing"
                db.commit()
            
            result = extracted
            if result is None:
                if hasattr(self.url_adapter, "start_extract_content"):
                    operation = self.url_adapter.start_extract_content(url)
                    extraction_future = operation.future
                    wait_for_extraction = operation.wait()
                else:
                    extraction_future = self.executor.submit(
                        self.url_adapter.extract_content,
                        url,
                    )
                    wait_for_extraction = asyncio.shield(
                        asyncio.wrap_future(extraction_future)
                    )
                try:
                    result = await wait_for_extraction
                except asyncio.CancelledError:
                    lease.defer_release_until(extraction_future)
                    raise
            
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
            
        except asyncio.CancelledError:
            raise
        except ChunkLimitPersistenceError:
            logger.critical(
                "URL chunk-limit cleanup could not be persisted",
                doc_id=doc_id,
            )
            raise
        except Exception as e:
            if extraction_future is not None and not extraction_future.done():
                lease.defer_release_until(extraction_future)
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
        finally:
            lease.release()
    
    async def process_youtube(
        self,
        db: Session,
        project_id: str,
        user_id: str,
        youtube_url: str,
        title: Optional[str] = None,
        operation_lease: Optional[OperationLease] = None,
    ) -> Document:
        """Process YouTube video transcript.
        
        Args:
            db: Database session
            project_id: Project ID
            user_id: Account that will own the document
            youtube_url: YouTube video URL
            title: Optional document title
            operation_lease: Explicit quota ownership transferred to this
                service until background extraction/indexing really finishes.
            
        Returns:
            Created document
        """
        lease = _operation_lease(operation_lease)
        try:
            # Initialize YouTube adapter if needed
            if not self.youtube_adapter:
                self.youtube_adapter = YouTubeAdapter()
            
            # Generate document ID
            doc_id = str(uuid.uuid4())
            
            # Create document record with queued status
            document = Document(
                id=doc_id,
                user_id=user_id,
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
            task = asyncio.create_task(self._process_youtube_async(
                db,
                doc_id,
                youtube_url,
                operation_lease=lease,
            ))
            task.add_done_callback(lambda _task: lease.release())
            
            logger.info("YouTube processing initiated",
                       doc_id=doc_id,
                       youtube_url=youtube_url,
                       project_id=project_id)
            
            return document
            
        except Exception as e:
            lease.release()
            logger.error("Failed to process YouTube URL",
                        youtube_url=youtube_url,
                        error=str(e))
            raise
    
    async def _process_youtube_async(
        self,
        db: Session,
        doc_id: str,
        youtube_url: str,
        operation_lease: Optional[OperationLease] = None,
    ):
        """Process YouTube video asynchronously.
        
        Args:
            db: Database session
            doc_id: Document ID
            youtube_url: YouTube URL
            operation_lease: Quota ownership released only after this task and
                any uncancellable executor work finish.
        """
        lease = _operation_lease(operation_lease)
        extraction_future = None
        try:
            # Update status to processing
            doc = db.query(Document).filter(Document.id == doc_id).first()
            if doc:
                doc.status = "processing"
                db.commit()
            
            # Extract transcript in thread pool
            extraction_future = self.executor.submit(
                self.youtube_adapter.extract_transcript,
                youtube_url
            )
            try:
                result = await asyncio.shield(
                    asyncio.wrap_future(extraction_future)
                )
            except asyncio.CancelledError:
                lease.defer_release_until(extraction_future)
                raise
            
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
            
        except asyncio.CancelledError:
            raise
        except ChunkLimitPersistenceError:
            logger.critical(
                "YouTube chunk-limit cleanup could not be persisted",
                doc_id=doc_id,
            )
            raise
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
        finally:
            lease.release()
    
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

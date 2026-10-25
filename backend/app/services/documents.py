"""Document ingestion service."""
import hashlib
import uuid
import os
from typing import Any, BinaryIO, Callable, ContextManager, Dict, Optional
from pathlib import Path
import asyncio
from concurrent.futures import ThreadPoolExecutor
import structlog
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.db.models import (
    Chunk,
    Conversation,
    Document,
    IngestionJob,
    Message,
    Project,
    ProjectDocument,
)
from app.db.database import get_db_context
from app.schemas import DocumentCreate
from app.adapters import OfficeAdapter, PDFAdapter, URLAdapter, YouTubeAdapter
from app.adapters.office import (
    InvalidOfficeFileError,
    SUPPORTED_AUDIO_EXTENSIONS,
    SUPPORTED_IMAGE_EXTENSIONS,
    SUPPORTED_FILE_EXTENSIONS,
    SUPPORTED_UPLOAD_EXTENSIONS,
)
from app.adapters.audio import AudioAdapter, InvalidAudioFileError
from app.adapters.ocr import InvalidImageError, OCRAdapter
from app.config import get_settings
from app.services.chunking import (
    CHUNK_LIMIT_ACTION,
    ChunkingService,
    ChunkLimitExceededError,
)
from app.services.document_files import UPLOAD_DIR
from app.services.retrieval_index import get_retrieval_index
from app.services.ingestion_jobs import (
    enqueue_ingestion_job_with_result,
    notify_ingestion_worker,
    release_operation_lease,
    retain_enqueued_operation_lease,
)
from app.services.rate_limit import OperationLease, UnlimitedConcurrencyLease
from app.services.source_digest import invalidate_source_guide
from app.utils.time import utc_now, utc_now_iso

logger = structlog.get_logger()
PDF_UPLOAD_BLOCK_BYTES = 1024 * 1024
CHUNK_LIMIT_CLEANUP_ATTEMPTS = 2


class UploadTooLargeError(ValueError):
    """Raised when an upload crosses the configured byte limit."""


class TextSourceBusyError(ValueError):
    """Raised when a text source is already being processed."""


class InvalidUploadFileError(ValueError):
    """Raised when an upload's extension or file contents are unsupported."""


class ChunkLimitPersistenceError(RuntimeError):
    """Raised when an over-limit chunk set cannot be atomically cleaned up."""


class EnqueueCommitUncertainError(RuntimeError):
    """Raised when durable enqueue state cannot be safely reconciled."""


def _commit_ingestion_enqueue(
    db: Session,
    document_id: str,
    project_id: str,
    job_id: str,
    job_type: str,
    payload: dict,
) -> None:
    """Commit an enqueue, accepting a lost acknowledgement of exact state."""
    try:
        db.commit()
        return
    except Exception as commit_error:
        try:
            db.rollback()
        except Exception as rollback_error:
            raise EnqueueCommitUncertainError(
                "Could not reconcile enqueue commit for job %s" % job_id
            ) from rollback_error

        try:
            with Session(bind=db.get_bind()) as verification_db:
                document = verification_db.get(Document, document_id)
                job = verification_db.get(IngestionJob, job_id)
                project_document = verification_db.get(
                    ProjectDocument,
                    (project_id, document_id),
                )
                durable_pair_matches = (
                    document is not None
                    and project_document is not None
                    and job is not None
                    and job.document_id == document_id
                    and job.job_type == job_type
                    and job.payload_json == payload
                )
                durable_pair_absent = (
                    document is None
                    and project_document is None
                    and job is None
                )
        except Exception as verification_error:
            # The source and lease must remain recoverable if the durable state
            # cannot be read; destructive request cleanup could orphan a row
            # whose COMMIT was actually accepted by the database.
            raise EnqueueCommitUncertainError(
                "Could not verify enqueue commit for job %s" % job_id
            ) from verification_error

        if durable_pair_matches:
            logger.warning(
                "Ingestion enqueue commit acknowledgement was lost",
                document_id=document_id,
                job_id=job_id,
            )
            return
        if durable_pair_absent:
            raise commit_error
        raise EnqueueCommitUncertainError(
            "Ingestion enqueue commit left inconsistent state for job %s"
            % job_id
        ) from commit_error


def rename_document(db: Session, document: Document, title: str) -> Document:
    """Rename a source, including the title its existing citations show.

    Args:
        db: Database session.
        document: Document the caller is allowed to change.
        title: New title.

    Returns:
        The renamed document.
    """
    title_changed = document.title != title
    document.title = title
    # Answers keep a copy of each cited source's title. Left alone, every
    # earlier answer and its exports would go on citing the old name.
    messages = (
        db.query(Message)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .join(
            ProjectDocument,
            ProjectDocument.project_id == Conversation.project_id,
        )
        .filter(
            ProjectDocument.document_id == document.id,
            Message.role == "assistant",
        )
        .all()
    )
    for message in messages:
        citations = message.citations_json or []
        if any(c.get("document_id") == document.id for c in citations):
            # Reassigned rather than mutated: SQLAlchemy cannot see an
            # in-place change to a JSON column and would not save it.
            message.citations_json = [
                {**c, "document_title": title}
                if c.get("document_id") == document.id else c
                for c in citations
            ]
    enqueue_reindex = title_changed and document.status == "ready"
    if enqueue_reindex:
        invalidate_source_guide(document)
        enqueue_ingestion_job_with_result(
            db,
            document_id=document.id,
            job_type="reindex",
            payload={"requested_title": title},
        )
    # Title, stored citations, and the refresh request must share a transaction;
    # a crash between separate commits would leave title-conditioned vectors stale.
    db.commit()
    db.refresh(document)
    if enqueue_reindex:
        notify_ingestion_worker()
    return document


def _operation_lease(lease: Optional[OperationLease]) -> OperationLease:
    """Return a concrete operation ownership handle."""
    return lease if lease is not None else UnlimitedConcurrencyLease()


class DocumentService:
    """Service for document ingestion and processing."""
    
    def __init__(
        self,
        chunking_service: Any | None = None,
        embedding_service: Any | None = None,
        pdf_adapter: Any | None = None,
        office_adapter: Any | None = None,
        url_adapter: Any | None = None,
        youtube_adapter: Any | None = None,
        session_context: Callable[[], ContextManager[Session]] = get_db_context,
        max_chunks_per_doc: Optional[int] = None,
        ocr_adapter: Any | None = None,
        audio_adapter: Any | None = None,
    ):
        """Initialize document processing dependencies.

        Args:
            chunking_service: Optional chunking implementation.
            embedding_service: Optional embedding implementation.
            audio_adapter: Optional local audio validation and transcription.
            pdf_adapter: Optional PDF extraction implementation.
            office_adapter: Optional local file extraction implementation.
            ocr_adapter: Optional local OCR implementation for images and scans.
            url_adapter: Optional URL extraction implementation.
            youtube_adapter: Optional YouTube transcript implementation.
            session_context: Factory that owns each detached worker session.
            max_chunks_per_doc: Optional hard ceiling override. The application
                setting defaults to exactly 1000.

        Returns:
            None.
        """
        if embedding_service is None:
            from app.services.embeddings import EmbeddingService

            embedding_service = EmbeddingService()

        self.settings = get_settings()
        self.ocr_adapter = (
            ocr_adapter
            if ocr_adapter is not None
            else OCRAdapter(self.settings.ocr_model_cache_dir)
        )
        self.pdf_adapter = (
            pdf_adapter
            if pdf_adapter is not None
            else PDFAdapter(
                use_pymupdf=False,
                ocr_adapter=self.ocr_adapter,
                ocr_enabled=self.settings.ocr_enabled,
            )
        )
        self.office_adapter = (
            office_adapter if office_adapter is not None else OfficeAdapter()
        )
        self.audio_adapter = audio_adapter
        self.url_adapter = (
            url_adapter
            if url_adapter is not None
            else URLAdapter(
                timeout=self.settings.url_read_timeout_seconds,
                connect_timeout=self.settings.url_connect_timeout_seconds,
                max_download_bytes=self.settings.max_url_download_mb * 1024 * 1024,
                max_redirects=self.settings.max_url_redirects,
                max_download_seconds=self.settings.url_download_timeout_seconds,
                pdf_adapter=self.pdf_adapter,
            )
        )
        self.youtube_adapter = youtube_adapter
        self.executor = ThreadPoolExecutor(max_workers=4)
        self.chunking_service = (
            chunking_service if chunking_service is not None else ChunkingService()
        )
        self.embedding_service = embedding_service
        self.session_context = session_context
        self.max_chunks_per_doc = (
            max_chunks_per_doc
            if max_chunks_per_doc is not None
            else self.settings.max_chunks_per_doc
        )

    def _get_youtube_adapter(self) -> Any:
        """Return the configured caption adapter and optional audio fallback.

        Returns:
            The process-local YouTube ingestion adapter.
        """
        if self.youtube_adapter is not None:
            return self.youtube_adapter

        audio_transcriber = None
        if self.settings.yt_whisper_fallback_enabled:
            # Import lazily so disabling the fallback keeps Whisper and yt-dlp
            # out of the ordinary caption-only request path.
            from app.adapters.youtube_audio import YouTubeAudioTranscriber

            audio_transcriber = YouTubeAudioTranscriber(
                model_name=self.settings.yt_whisper_model,
                max_duration_seconds=self.settings.yt_max_duration_seconds,
                cache_dir=self.settings.yt_whisper_cache_dir,
            )

        self.youtube_adapter = YouTubeAdapter(
            audio_transcriber=audio_transcriber
        )
        return self.youtube_adapter

    def _get_audio_adapter(self) -> AudioAdapter:
        """Return the process-local adapter for uploaded audio files.

        Returns:
            A lazily configured local audio adapter.
        """
        if self.audio_adapter is None:
            self.audio_adapter = AudioAdapter(
                model_name=self.settings.yt_whisper_model,
                max_duration_seconds=self.settings.audio_max_duration_seconds,
                cache_dir=self.settings.yt_whisper_cache_dir,
            )
        return self.audio_adapter

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
            chunks = self.chunking_service.chunk_document(
                db,
                doc_id,
                max_chunks=self.max_chunks_per_doc,
            )
            logger.info(f"Created {len(chunks)} chunks for {source_label} document {doc_id}")

            if len(chunks) > self.max_chunks_per_doc:
                return self._mark_chunk_limit_failed(db, doc_id, len(chunks))

            embeddings = self.embedding_service.embed_chunks(db, doc_id)
            logger.info(f"Generated {len(embeddings)} embeddings for {source_label} document {doc_id}")
        except ChunkLimitExceededError as error:
            logger.warning(
                "Chunk planning stopped at document limit",
                document_id=doc_id,
                chunk_count=error.chunk_count,
                max_chunks=error.max_chunks,
            )
            return self._mark_chunk_limit_failed(
                db,
                doc_id,
                error.chunk_count,
            )
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
            self._publish_document_index(db, doc_id)
            db.commit()

        return "ready"

    def _publish_document_index(self, db: Session, doc_id: str) -> None:
        """Publish completed vectors through either embedding implementation.

        Args:
            db: Transaction that is changing the document to ``ready``.
            doc_id: Document whose index should become searchable.

        Returns:
            None.
        """
        publisher = getattr(
            self.embedding_service,
            "publish_document_index",
            None,
        )
        if publisher is not None:
            publisher(db, doc_id)
            return

        # Lightweight embedding implementations only promise embed_chunks.
        # Flush the pending ready state so the general reconciliation path can
        # derive searchable=True without requiring a model-service method.
        db.flush()
        get_retrieval_index().backfill(
            db,
            document_ids=[doc_id],
        )

    def _mark_chunk_limit_failed(
        self,
        db: Session,
        doc_id: str,
        chunk_count: int,
    ) -> str:
        """Remove any prior index and atomically record an over-limit failure.

        The live chunker raises before inserting replacement rows, but a retry
        can still begin with an older committed index. Deleting it in the same
        transaction that updates the document prevents failed sources from
        retaining searchable stale data or status without actionable metadata.

        Args:
            db: Database session.
            doc_id: Document id that exceeded the ceiling.
            chunk_count: Number of chunks the chunker committed.

        Returns:
            The status the document ended up in.
        """
        action = CHUNK_LIMIT_ACTION
        message = (
            f"This source produced {chunk_count} chunks, exceeding the "
            "per-source limit of "
            f"{self.max_chunks_per_doc}. {action}"
        )

        last_error = None
        for attempt in range(1, CHUNK_LIMIT_CLEANUP_ATTEMPTS + 1):
            try:
                # Re-read and re-delete on every attempt. A rollback after a
                # failed commit restores both the rows and the document, so
                # retrying only commit would falsely report a clean database.
                get_retrieval_index().delete_document(db, doc_id)
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

        get_retrieval_index().delete_document(db, doc_id)
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
        """Keep the existing PDF upload entry point and durable job type.

        Args:
            db: Database session.
            project_id: Project receiving the PDF.
            user_id: Account that will own the document.
            file: Uploaded PDF stream.
            filename: Original filename.
            title: Optional document title.
            operation_lease: Quota ownership transferred until background work
                finishes.

        Returns:
            The queued PDF document.
        """
        return await self.process_file_upload(
            db=db,
            project_id=project_id,
            user_id=user_id,
            file=file,
            filename=filename,
            file_extension=".pdf",
            title=title,
            operation_lease=operation_lease,
        )

    async def process_file_upload(
        self,
        db: Session,
        project_id: str,
        user_id: str,
        file: BinaryIO,
        filename: str,
        file_extension: str,
        title: Optional[str] = None,
        operation_lease: Optional[OperationLease] = None,
    ) -> Document:
        """Store and queue one supported source file.

        Args:
            db: Database session.
            project_id: Project receiving the file.
            user_id: Account that will own the document.
            file: Uploaded file stream.
            filename: Original filename.
            file_extension: Original extension including its leading dot.
            title: Optional document title.
            operation_lease: Quota ownership transferred until background work
                finishes.

        Returns:
            The queued document.
        """
        lease = _operation_lease(operation_lease)
        file_extension = str(file_extension or "").strip().lower()
        if file_extension not in SUPPORTED_UPLOAD_EXTENSIONS:
            lease.release()
            raise InvalidUploadFileError(
                "Files with the %s extension are not supported" % file_extension
            )
        if file_extension in SUPPORTED_IMAGE_EXTENSIONS and not self.settings.ocr_enabled:
            lease.release()
            raise InvalidUploadFileError("Image uploads are unavailable while OCR is disabled")
        safe_filename = (
            Path(filename.replace("\\", "/")).name
            if isinstance(filename, str)
            else ""
        )
        if not safe_filename or Path(safe_filename).suffix.lower() != file_extension:
            lease.release()
            raise InvalidUploadFileError(
                "The filename extension does not match the uploaded file type"
            )

        file_path = None
        retained = False
        owns_retained_lease = False
        job_id = None
        database_touched = False
        try:
            # Generate document ID
            doc_id = str(uuid.uuid4())
            
            # Save file to disk. Reading without a size would duplicate the
            # entire multipart spool in RAM before the limit could be checked.
            file_path = UPLOAD_DIR / f"{doc_id}_{safe_filename}"
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

            if file_extension in SUPPORTED_IMAGE_EXTENSIONS:
                try:
                    self.ocr_adapter.validate_image_file(str(file_path))
                except InvalidImageError as error:
                    raise InvalidUploadFileError(str(error)) from error
            elif file_extension in SUPPORTED_FILE_EXTENSIONS:
                try:
                    self.office_adapter.validate_file(str(file_path), file_extension)
                except InvalidOfficeFileError as error:
                    raise InvalidUploadFileError(str(error)) from error
            elif file_extension in SUPPORTED_AUDIO_EXTENSIONS:
                try:
                    self._get_audio_adapter().validate_file(str(file_path))
                except InvalidAudioFileError as error:
                    raise InvalidUploadFileError(str(error)) from error

            job_type = "pdf" if file_extension == ".pdf" else "file"
            source_type = "pdf" if file_extension == ".pdf" else file_extension[1:]
            payload = {"file_path": str(file_path)}
            
            # Create document record with queued status
            document = Document(
                id=doc_id,
                user_id=user_id,
                title=title or filename,
                source_type=source_type,
                source_url=str(file_path),
                status="queued",
                meta_json={
                    "filename": filename,
                    "file_extension": file_extension,
                    "file_size": file_size,
                    "upload_time": utc_now_iso(),
                }
            )
            
            database_touched = True
            db.add(document)
            
            # Link to project
            project_doc = ProjectDocument(
                project_id=project_id,
                document_id=doc_id,
                shared_by_user_id=user_id,
            )
            db.add(project_doc)
            enqueue_result = enqueue_ingestion_job_with_result(
                db,
                document_id=doc_id,
                job_type=job_type,
                payload=payload,
            )
            job = enqueue_result.job
            job_id = job.id
            owns_retained_lease = retain_enqueued_operation_lease(
                enqueue_result,
                operation_lease,
            )
            _commit_ingestion_enqueue(
                db,
                document_id=doc_id,
                project_id=project_id,
                job_id=job_id,
                job_type=job_type,
                payload=payload,
            )
            retained = True
            try:
                notify_ingestion_worker()
            except Exception as error:
                # Polling is the durable notification path. A process-local
                # wakeup failure must not undo a committed document/job pair or
                # delete the source file that recovery now owns.
                logger.warning(
                    "Could not wake ingestion worker after file enqueue",
                    job_id=job_id,
                    error=str(error),
                )
            
            logger.info(
                "File upload initiated",
                doc_id=doc_id,
                filename=filename,
                project_id=project_id,
                file_extension=file_extension,
            )
            
            return document
            
        except Exception as e:
            if database_touched:
                db.rollback()
            if isinstance(e, EnqueueCommitUncertainError):
                retained = True
            if owns_retained_lease and not retained:
                release_operation_lease(job_id)
            elif job_id is None:
                lease.release()
            if file_path is not None and not retained:
                file_path.unlink(missing_ok=True)
            logger.error("Failed to process file upload", filename=filename, error=str(e))
            raise
    
    async def _process_pdf_async(
        self,
        doc_id: str,
        file_path: Path,
        operation_lease: Optional[OperationLease] = None,
    ) -> None:
        """Process PDF file asynchronously.
        
        Args:
            doc_id: Document ID
            file_path: Path to PDF file
            operation_lease: Quota ownership released only after this task and
                any uncancellable executor work finish.

        Returns:
            None.
        """
        lease = _operation_lease(operation_lease)
        extraction_future = None
        try:
            with self.session_context() as db:
                try:
                    doc = db.query(Document).filter(Document.id == doc_id).first()
                    if doc:
                        doc.status = "processing"
                        db.commit()

                    extraction_future = self.executor.submit(
                        self.pdf_adapter.extract_text_from_file,
                        str(file_path),
                    )
                    try:
                        result = await asyncio.shield(
                            asyncio.wrap_future(extraction_future)
                        )
                    except asyncio.CancelledError:
                        lease.defer_release_until(extraction_future)
                        raise

                    doc = db.query(Document).filter(Document.id == doc_id).first()
                    if doc:
                        doc.content = result["text"]
                        doc.meta_json = {
                            **(doc.meta_json or {}),
                            "num_pages": result["num_pages"],
                            # The chunker needs per-page text to populate page_num.
                            "pages": result.get("pages", []),
                            "metadata": result.get("metadata", {}),
                            "processed_at": utc_now_iso(),
                        }
                        db.commit()

                        status = self._index_document(db, doc_id, "PDF")
                        logger.info(
                            "PDF processing completed",
                            doc_id=doc_id,
                            num_pages=result["num_pages"],
                            status=status,
                        )
                except asyncio.CancelledError:
                    raise
                except ChunkLimitPersistenceError:
                    logger.critical(
                        "PDF chunk-limit cleanup could not be persisted",
                        doc_id=doc_id,
                    )
                    raise
                except Exception as error:
                    logger.error(
                        "Failed to process PDF",
                        doc_id=doc_id,
                        error=str(error),
                    )
                    self._mark_failed(db, doc_id, str(error))
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
        job_id = None
        retained = False
        owns_retained_lease = False
        try:
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
                document_id=doc_id,
                shared_by_user_id=user_id,
            )
            db.add(project_doc)
            enqueue_result = enqueue_ingestion_job_with_result(
                db,
                document_id=doc_id,
                job_type="url",
                payload={"url": url},
            )
            job = enqueue_result.job
            job_id = job.id
            owns_retained_lease = retain_enqueued_operation_lease(
                enqueue_result,
                operation_lease,
            )
            _commit_ingestion_enqueue(
                db,
                document_id=doc_id,
                project_id=project_id,
                job_id=job_id,
                job_type="url",
                payload={"url": url},
            )
            retained = True
            try:
                notify_ingestion_worker()
            except Exception as error:
                logger.warning(
                    "Could not wake ingestion worker after URL enqueue",
                    job_id=job_id,
                    error=str(error),
                )
            
            logger.info("URL processing initiated",
                       doc_id=doc_id,
                       url=url,
                       project_id=project_id)
            
            return document
            
        except Exception as e:
            db.rollback()
            if isinstance(e, EnqueueCommitUncertainError):
                retained = True
            if owns_retained_lease and not retained:
                release_operation_lease(job_id)
            elif job_id is None:
                lease.release()
            logger.error("Failed to process URL",
                        url=url,
                        error=str(e))
            raise
    
    async def _process_url_async(
        self,
        doc_id: str,
        url: str,
        extracted: Optional[Dict] = None,
        operation_lease: Optional[OperationLease] = None,
    ) -> None:
        """Process URL asynchronously.
        
        Args:
            doc_id: Document ID
            url: URL to process
            extracted: Content already fetched at the request boundary. Tests
                and recovery callers may omit it to perform extraction here.
            operation_lease: Quota ownership released only after this task and
                any uncancellable executor work finish.

        Returns:
            None.
        """
        lease = _operation_lease(operation_lease)
        extraction_future = None
        try:
            with self.session_context() as db:
                try:
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

                    doc = db.query(Document).filter(Document.id == doc_id).first()
                    if doc:
                        doc.content = result["text"]
                        doc.title = result.get("title", url)
                        doc.meta_json = {
                            **(doc.meta_json or {}),
                            "metadata": result.get("metadata", {}),
                            "headings": result.get("headings", []),
                            "num_links": len(result.get("links", [])),
                            "text_size": len(result["text"].encode("utf-8")),
                            "processed_at": utc_now_iso(),
                        }
                        db.commit()

                        status = self._index_document(db, doc_id, "URL")
                        logger.info(
                            "URL processing completed",
                            doc_id=doc_id,
                            url=url,
                            status=status,
                        )
                except asyncio.CancelledError:
                    raise
                except ChunkLimitPersistenceError:
                    logger.critical(
                        "URL chunk-limit cleanup could not be persisted",
                        doc_id=doc_id,
                    )
                    raise
                except Exception as error:
                    if extraction_future is not None and not extraction_future.done():
                        lease.defer_release_until(extraction_future)
                    logger.error(
                        "Failed to process URL",
                        doc_id=doc_id,
                        url=url,
                        error=str(error),
                    )
                    self._mark_failed(db, doc_id, str(error))
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
        job_id = None
        retained = False
        owns_retained_lease = False
        try:
            # Initialize YouTube adapter if needed
            self._get_youtube_adapter()

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
                document_id=doc_id,
                shared_by_user_id=user_id,
            )
            db.add(project_doc)
            enqueue_result = enqueue_ingestion_job_with_result(
                db,
                document_id=doc_id,
                job_type="youtube",
                payload={"youtube_url": youtube_url},
            )
            job = enqueue_result.job
            job_id = job.id
            owns_retained_lease = retain_enqueued_operation_lease(
                enqueue_result,
                operation_lease,
            )
            _commit_ingestion_enqueue(
                db,
                document_id=doc_id,
                project_id=project_id,
                job_id=job_id,
                job_type="youtube",
                payload={"youtube_url": youtube_url},
            )
            retained = True
            try:
                notify_ingestion_worker()
            except Exception as error:
                logger.warning(
                    "Could not wake ingestion worker after YouTube enqueue",
                    job_id=job_id,
                    error=str(error),
                )
            
            logger.info("YouTube processing initiated",
                       doc_id=doc_id,
                       youtube_url=youtube_url,
                       project_id=project_id)
            
            return document
            
        except Exception as e:
            db.rollback()
            if isinstance(e, EnqueueCommitUncertainError):
                retained = True
            if owns_retained_lease and not retained:
                release_operation_lease(job_id)
            elif job_id is None:
                lease.release()
            logger.error("Failed to process YouTube URL",
                        youtube_url=youtube_url,
                        error=str(e))
            raise
    
    async def _process_youtube_async(
        self,
        doc_id: str,
        youtube_url: str,
        operation_lease: Optional[OperationLease] = None,
    ) -> None:
        """Process YouTube video asynchronously.
        
        Args:
            doc_id: Document ID
            youtube_url: YouTube URL
            operation_lease: Quota ownership released only after this task and
                any uncancellable executor work finish.

        Returns:
            None.
        """
        lease = _operation_lease(operation_lease)
        extraction_future = None
        try:
            with self.session_context() as db:
                try:
                    doc = db.query(Document).filter(Document.id == doc_id).first()
                    if doc:
                        doc.status = "processing"
                        db.commit()

                    extraction_future = self.executor.submit(
                        self.youtube_adapter.extract_transcript,
                        youtube_url,
                    )
                    try:
                        result = await asyncio.shield(
                            asyncio.wrap_future(extraction_future)
                        )
                    except asyncio.CancelledError:
                        lease.defer_release_until(extraction_future)
                        raise

                    doc = db.query(Document).filter(Document.id == doc_id).first()
                    if doc:
                        doc.content = result["text"]
                        doc.title = f"YouTube: {result.get('video_id', youtube_url)}"
                        doc.meta_json = {
                            **(doc.meta_json or {}),
                            "video_id": result.get("video_id"),
                            "duration": result.get("duration", 0),
                            "language": result.get("language", "unknown"),
                            "metadata": result.get("metadata", {}),
                            "num_segments": len(result.get("segments", [])),
                            "text_size": len(result["text"].encode("utf-8")),
                            "transcription_source": result.get(
                                "transcription_source", "youtube_captions"
                            ),
                            "processed_at": utc_now_iso(),
                        }
                        db.commit()

                        status = self._index_document(db, doc_id, "YouTube")
                        logger.info(
                            "YouTube processing completed",
                            doc_id=doc_id,
                            video_id=result.get("video_id"),
                            status=status,
                        )
                except asyncio.CancelledError:
                    raise
                except ChunkLimitPersistenceError:
                    logger.critical(
                        "YouTube chunk-limit cleanup could not be persisted",
                        doc_id=doc_id,
                    )
                    raise
                except Exception as error:
                    logger.error(
                        "Failed to process YouTube video",
                        doc_id=doc_id,
                        youtube_url=youtube_url,
                        error_type=type(error).__name__,
                        error=str(error),
                    )
                    self._mark_failed(db, doc_id, str(error))
        finally:
            lease.release()

    async def process_text(
        self,
        db: Session,
        project_id: str,
        user_id: str,
        title: str,
        text: str,
        operation_lease: Optional[OperationLease] = None,
        document_id: Optional[str] = None,
        note_id: Optional[str] = None,
    ) -> Document:
        """Store or refresh pasted text as a source and queue it for indexing.

        Args:
            db: Database session
            project_id: Project ID
            user_id: Account that will own the document
            title: Document title
            text: Pasted body
            operation_lease: Explicit quota ownership transferred to this
                service until background indexing really finishes.
            document_id: Existing text source to refresh, or a stable id for a
                note source.
            note_id: Note linked to this source, when it came from a note.

        Returns:
            Created document
        """
        lease = _operation_lease(operation_lease)
        job_id = None
        retained = False
        owns_retained_lease = False
        try:
            size = len(text.encode("utf-8"))
            if size > self.settings.max_file_size_bytes:
                raise UploadTooLargeError(
                    "Text size exceeds maximum of %sMB"
                    % self.settings.max_file_size_mb
                )

            doc_id = document_id or str(uuid.uuid4())
            document = db.get(Document, doc_id)
            is_refresh = document is not None
            if is_refresh:
                if document.source_type != "text" or document.note_id != note_id:
                    raise ValueError("Only the linked note source can be refreshed")
                active_job = db.query(IngestionJob.id).filter(
                    IngestionJob.document_id == doc_id,
                    IngestionJob.status.in_(("queued", "running")),
                ).first()
                if (
                    document.status in {"queued", "processing", "transcribing"}
                    or active_job is not None
                ):
                    raise TextSourceBusyError("The note source is still processing")
                # Do not leave old passages searchable after the saved note changes.
                get_retrieval_index().delete_document(db, doc_id)
                for chunk in db.query(Chunk).filter(Chunk.document_id == doc_id).all():
                    db.delete(chunk)
                document.title = title
                document.content = text
                document.status = "queued"
                document.error_message = None
                document.meta_json = {
                    **(document.meta_json or {}),
                    "text_size": size,
                    "upload_time": utc_now_iso(),
                }
            else:
                # The text is the source, so the job only has to chunk and embed it.
                document = Document(
                    id=doc_id,
                    user_id=user_id,
                    note_id=note_id,
                    title=title,
                    source_type="text",
                    content=text,
                    status="queued",
                    meta_json={
                        "text_size": size,
                        "upload_time": utc_now_iso(),
                    },
                )
                db.add(document)
                db.add(ProjectDocument(
                    project_id=project_id,
                    document_id=doc_id,
                    shared_by_user_id=user_id,
                ))
            payload = {"document_id": doc_id}
            enqueue_result = enqueue_ingestion_job_with_result(
                db,
                document_id=doc_id,
                job_type="text",
                payload=payload,
                force_new=is_refresh,
            )
            if is_refresh and not enqueue_result.created_new_active:
                db.rollback()
                raise TextSourceBusyError("The note source is still processing")
            job_id = enqueue_result.job.id
            owns_retained_lease = retain_enqueued_operation_lease(
                enqueue_result,
                operation_lease,
            )
            _commit_ingestion_enqueue(
                db,
                document_id=doc_id,
                project_id=project_id,
                job_id=job_id,
                job_type="text",
                payload=payload,
            )
            retained = True
            try:
                notify_ingestion_worker()
            except Exception as error:
                logger.warning(
                    "Could not wake ingestion worker after text enqueue",
                    job_id=job_id,
                    error=str(error),
                )

            logger.info("Text source added", doc_id=doc_id, project_id=project_id)
            return document

        except Exception as e:
            db.rollback()
            if isinstance(e, EnqueueCommitUncertainError):
                retained = True
            if owns_retained_lease and not retained:
                release_operation_lease(job_id)
            elif job_id is None:
                lease.release()
            logger.error("Failed to add text source", error=str(e))
            raise

    def enqueue_resync(
        self,
        db: Session,
        project_id: str,
        document: Document,
        operation_lease: Optional[OperationLease] = None,
    ) -> Document:
        """Queue a fresh extraction for a URL or YouTube source.

        Args:
            db: Session holding the authorized document.
            project_id: Project through which the caller manages the source.
            document: Existing source whose id and relationships must survive.
            operation_lease: Request quota retained until the durable job ends.

        Returns:
            The same document, queued for a fresh extraction when no work is active.
        """
        lease = _operation_lease(operation_lease)
        job_id = None
        retained = False
        owns_retained_lease = False
        try:
            if document.source_type == "url":
                payload = {"url": document.source_url}
            elif document.source_type == "youtube":
                payload = {"youtube_url": document.source_url}
            else:
                raise ValueError("Only URL and YouTube sources can be re-synced")
            payload.update({
                "previous_status": document.status,
                "previous_error_message": document.error_message,
            })
            enqueue_result = enqueue_ingestion_job_with_result(
                db,
                document_id=document.id,
                job_type="resync",
                payload=payload,
                force_new=True,
            )
            if not enqueue_result.created_new_active:
                lease.release()
                return document
            job_id = enqueue_result.job.id
            owns_retained_lease = retain_enqueued_operation_lease(
                enqueue_result,
                operation_lease,
            )
            _commit_ingestion_enqueue(
                db,
                document_id=document.id,
                project_id=project_id,
                job_id=job_id,
                job_type="resync",
                payload=payload,
            )
            retained = True
            try:
                notify_ingestion_worker()
            except Exception as error:
                logger.warning(
                    "Could not wake ingestion worker after re-sync enqueue",
                    job_id=job_id,
                    error=str(error),
                )
            return document
        except Exception as error:
            db.rollback()
            if isinstance(error, EnqueueCommitUncertainError):
                retained = True
            if owns_retained_lease and not retained:
                release_operation_lease(job_id)
            elif job_id is None:
                lease.release()
            raise

    def process_ingestion_job(
        self,
        db: Session,
        document_id: str,
        job_type: str,
        payload: Dict,
    ) -> str:
        """Run one durable extraction and indexing pipeline synchronously.

        The lifespan worker invokes this entire method through
        ``asyncio.to_thread``. Content and chunk/embedding checkpoints may
        commit independently, but the final ``ready`` state is deliberately
        left uncommitted so the worker can persist it together with the job's
        ``completed`` state.

        Args:
            db: Session created and owned by the worker for this job.
            document_id: Document referenced by the durable job.
            job_type: Persisted source kind.
            payload: Persisted recoverable source references.

        Returns:
            The uncommitted final document status, always ``ready``.
        """
        document = db.get(Document, document_id)
        if document is None:
            raise ValueError("Document %s not found" % document_id)
        is_resync = job_type == "resync"
        if is_resync:
            if document.source_type in {"url", "youtube", "pdf"}:
                job_type = document.source_type
            elif document.source_type in {
                extension[1:]
                for extension in (
                    SUPPORTED_FILE_EXTENSIONS
                    | SUPPORTED_IMAGE_EXTENSIONS
                    | SUPPORTED_AUDIO_EXTENSIONS
                )
            }:
                job_type = "file"
            else:
                raise ValueError("This source type cannot be re-synced")
        if job_type == "reindex":
            if document.status != "ready":
                raise ValueError("Only ready documents can be re-indexed")
            chunks = (
                db.query(Chunk)
                .filter(Chunk.document_id == document_id)
                .all()
            )
            if not chunks:
                raise RuntimeError(
                    "No saved chunks are available for re-indexing"
                )
            while True:
                db.refresh(document)
                indexed_title = document.title
                embeddings = self.embedding_service.embed_chunks(
                    db,
                    document_id,
                    force_regenerate=True,
                )
                if not embeddings:
                    raise RuntimeError(
                        "No searchable text could be embedded for this source."
                    )
                db.refresh(document)
                if document.title != indexed_title:
                    continue
                document.status = "ready"
                document.error_message = None
                self._publish_document_index(db, document_id)
                db.flush()
                db.refresh(document)
                if document.title == indexed_title:
                    break

            invalidate_source_guide(document)
            # The worker compares this snapshot against the latest rename while
            # it holds the queue's writer reservation before completing the job.
            payload["_indexed_title"] = indexed_title
            return "ready"

        if job_type == "file":
            file_source_types = {
                extension[1:]
                for extension in (
                    SUPPORTED_FILE_EXTENSIONS
                    | SUPPORTED_IMAGE_EXTENSIONS
                    | SUPPORTED_AUDIO_EXTENSIONS
                )
            }
            if document.source_type not in file_source_types:
                raise ValueError(
                    "File job does not match document source type %s"
                    % document.source_type
                )
        elif document.source_type != job_type:
            raise ValueError(
                "Ingestion job type %s does not match document source type %s"
                % (job_type, document.source_type)
            )

        source_key = {
            "pdf": "file_path",
            "file": "file_path",
            "url": "url",
            "youtube": "youtube_url",
            "text": "document_id",
        }.get(job_type)
        if source_key is None:
            raise ValueError("Unsupported ingestion job type: %s" % job_type)
        source_reference = payload.get(source_key)
        if not isinstance(source_reference, str) or not source_reference:
            raise ValueError("Ingestion job is missing %s" % source_key)
        if job_type in {"pdf", "file"}:
            expected_source = Path(document.source_url or "").resolve()
            actual_source = Path(source_reference).resolve()
            if actual_source != expected_source:
                raise ValueError("File job source does not match its document")
            if job_type == "file":
                file_extension = (document.meta_json or {}).get("file_extension")
                if (
                    file_extension not in (
                        SUPPORTED_FILE_EXTENSIONS
                        | SUPPORTED_IMAGE_EXTENSIONS
                        | SUPPORTED_AUDIO_EXTENSIONS
                    )
                    or file_extension[1:] != document.source_type
                ):
                    raise ValueError("File job has no valid persisted file extension")
        elif job_type == "text":
            if source_reference != document.id:
                raise ValueError("Text job does not match its document")
        elif source_reference != document.source_url:
            raise ValueError("Ingestion job source does not match its document")

        file_extension = (document.meta_json or {}).get("file_extension")
        is_audio_file = (
            job_type == "file" and file_extension in SUPPORTED_AUDIO_EXTENSIONS
        )
        if not is_resync:
            document.status = "transcribing" if is_audio_file else "processing"
            document.error_message = None
        if is_audio_file:
            # Pollers need a committed status during the long model call; if it
            # stayed in this transaction, users would only see "queued".
            db.commit()

        if job_type == "pdf":
            result = self.pdf_adapter.extract_text_from_file(source_reference)
            document.content = result["text"]
            document.meta_json = {
                **(document.meta_json or {}),
                "num_pages": result["num_pages"],
                "pages": result.get("pages", []),
                "metadata": result.get("metadata", {}),
                "processed_at": utc_now_iso(),
            }
        elif job_type == "file":
            file_extension = document.meta_json["file_extension"]
            if file_extension in SUPPORTED_AUDIO_EXTENSIONS:
                result = self._get_audio_adapter().transcribe_file(source_reference)
                document.content = result["text"]
                document.meta_json = {
                    **(document.meta_json or {}),
                    "duration": result["duration"],
                    "language": result["language"],
                    "segments": result["segments"],
                    "metadata": result.get("metadata", {}),
                    "num_segments": len(result["segments"]),
                    "processed_at": utc_now_iso(),
                }
            else:
                if file_extension in SUPPORTED_IMAGE_EXTENSIONS:
                    filename = (document.meta_json or {}).get("filename") or Path(
                        source_reference
                    ).name
                    result = self.ocr_adapter.extract_text_from_image(
                        source_reference,
                        filename,
                    )
                else:
                    result = self.office_adapter.extract_text_from_file(
                        source_reference,
                        file_extension,
                    )
                document.content = result["text"]
                document.meta_json = {
                    **(document.meta_json or {}),
                    "num_pages": result["num_pages"],
                    "pages": result.get("pages", []),
                    "metadata": result.get("metadata", {}),
                    "processed_at": utc_now_iso(),
                }
        elif job_type == "text":
            # Pasted text was stored with the document; there is nothing to extract.
            pass
        elif job_type == "url":
            result = self.url_adapter.extract_content(source_reference)
            document.content = result["text"]
            document.title = result.get("title", source_reference)
            document.meta_json = {
                **(document.meta_json or {}),
                "metadata": result.get("metadata", {}),
                "headings": result.get("headings", []),
                "num_links": len(result.get("links", [])),
                "text_size": len(result["text"].encode("utf-8")),
                **({
                    "num_pages": result["num_pages"],
                    "pages": result.get("pages", []),
                } if "num_pages" in result else {}),
                "processed_at": utc_now_iso(),
            }
        else:
            if self.youtube_adapter is None:
                self.youtube_adapter = YouTubeAdapter()
            result = self.youtube_adapter.extract_transcript(source_reference)
            document.content = result["text"]
            document.title = "YouTube: %s" % result.get(
                "video_id",
                source_reference,
            )
            document.meta_json = {
                **(document.meta_json or {}),
                "video_id": result.get("video_id"),
                "duration": result.get("duration", 0),
                "language": result.get("language", "unknown"),
                "metadata": result.get("metadata", {}),
                "num_segments": len(result.get("segments", [])),
                "text_size": len(result["text"].encode("utf-8")),
                "processed_at": utc_now_iso(),
            }

        old_content_hash = document.content_hash
        content_hash = hashlib.sha256(
            (document.content or "").encode("utf-8")
        ).hexdigest()
        index_recovery_needed = bool(
            (document.meta_json or {}).get("_resync_index_started")
        )
        unchanged_resync = (
            is_resync
            and payload.get("previous_status") == "ready"
            and not index_recovery_needed
            and old_content_hash == content_hash
        )
        document.content_hash = content_hash
        document.last_sync_changed = old_content_hash != content_hash
        if unchanged_resync:
            document.status = "ready"
            document.last_synced_at = utc_now()
            document.error_message = None
            db.commit()
            return "ready"

        if is_resync:
            document.status = "processing"
            document.meta_json = {
                **(document.meta_json or {}),
                "_resync_index_started": True,
            }

        # A durable content checkpoint preserves the latest extracted text if a
        # later model/process step fails. Retries still repeat extraction and
        # rebuild the index from scratch, so these commits cannot duplicate it.
        db.commit()
        chunks = self.chunking_service.chunk_document(
            db,
            document_id,
            max_chunks=self.max_chunks_per_doc,
        )
        if len(chunks) > self.max_chunks_per_doc:
            raise ChunkLimitExceededError(
                len(chunks),
                self.max_chunks_per_doc,
            )
        embeddings = self.embedding_service.embed_chunks(db, document_id)
        if not embeddings:
            raise RuntimeError(
                "No searchable text could be extracted, so this source "
                "cannot be queried."
            )

        document = db.get(Document, document_id)
        document.status = "ready"
        document.error_message = None
        document.last_synced_at = utc_now()
        if is_resync:
            metadata = dict(document.meta_json or {})
            metadata.pop("_resync_index_started", None)
            document.meta_json = metadata
        self._publish_document_index(db, document_id)
        return "ready"
    
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

        file_path = (
            Path(doc.source_url)
            if (
                doc.source_url
                and (
                    doc.source_type == "pdf"
                    or ".%s" % doc.source_type
                    in (
                        SUPPORTED_FILE_EXTENSIONS
                        | SUPPORTED_IMAGE_EXTENSIONS
                        | SUPPORTED_AUDIO_EXTENSIONS
                    )
                )
            )
            else None
        )

        # This conditional DELETE competes for SQLite's writer lock with the
        # worker's conditional claim UPDATE. Only rows that are still queued
        # at the write boundary return an id whose request lease may be
        # released; a claim winner remains owned until its processor exits.
        queued_job_ids = list(db.execute(
            delete(IngestionJob)
            .where(
                IngestionJob.document_id == doc_id,
                IngestionJob.status == "queued",
            )
            .returning(IngestionJob.id)
            .execution_options(synchronize_session="fetch")
        ).scalars())

        # Commit the durable state first. Removing the only recoverable source
        # before a failed database delete would leave a queued job that can
        # never succeed after restart.
        get_retrieval_index().delete_document(db, doc_id)
        db.delete(doc)
        try:
            db.commit()
        except Exception as commit_error:
            try:
                db.rollback()
            except Exception:
                raise
            try:
                with Session(bind=db.get_bind()) as verification_db:
                    delete_was_persisted = (
                        verification_db.get(Document, doc_id) is None
                        and verification_db.query(IngestionJob).filter(
                            IngestionJob.document_id == doc_id,
                        ).first() is None
                    )
            except Exception:
                # A source file and its lease are safer retained than deleted
                # while the durable outcome cannot be read.
                raise commit_error
            if not delete_was_persisted:
                raise commit_error
            logger.warning(
                "Document delete commit acknowledgement was lost",
                document_id=doc_id,
            )
        for job_id in queued_job_ids:
            release_operation_lease(job_id)

        if file_path is not None and file_path.exists():
            try:
                file_path.unlink()
            except Exception as e:
                logger.warning("Failed to delete file",
                             file_path=str(file_path),
                             error=str(e))
        
        logger.info("Document deleted", doc_id=doc_id)
        return True

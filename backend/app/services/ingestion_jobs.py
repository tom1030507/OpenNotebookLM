"""Durable ingestion queue and lifespan-owned worker."""
from __future__ import annotations

import asyncio
from threading import Lock
from typing import Callable, Dict, Optional
import uuid

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
import structlog

from app.db.models import Chunk, Document, IngestionJob
from app.services.chunking import ChunkLimitExceededError
from app.services.rate_limit import OperationLease
from app.utils.time import utc_now

logger = structlog.get_logger()

ACTIVE_JOB_STATUSES = ("queued", "running")
TERMINAL_JOB_STATUSES = ("completed", "failed")
SUPPORTED_JOB_TYPES = ("pdf", "url", "youtube")

JobProcessor = Callable[[Session, IngestionJob], None]

_active_worker: Optional["IngestionJobWorker"] = None
_lease_lock = Lock()
_operation_leases: Dict[str, OperationLease] = {}


def enqueue_ingestion_job(
    db: Session,
    document_id: str,
    job_type: str,
    payload: dict,
) -> IngestionJob:
    """Create one queued job, reusing existing active or completed work.

    A failed row remains as attempt history and enqueue creates a new retry.
    The database partial unique index arbitrates racing callers, so at most one
    queued/running row can exist for a document.

    Args:
        db: Session whose surrounding transaction owns the document creation.
        document_id: Document to extract and index.
        job_type: One of pdf, url, or youtube.
        payload: Recoverable source references needed by the worker.

    Returns:
        The existing idempotent job or the newly queued retry.
    """
    if job_type not in SUPPORTED_JOB_TYPES:
        raise ValueError("Unsupported ingestion job type: %s" % job_type)

    active = _active_job(db, document_id)
    if active is not None:
        return active

    latest = (
        db.query(IngestionJob)
        .filter(IngestionJob.document_id == document_id)
        .order_by(IngestionJob.created_at.desc(), IngestionJob.id.desc())
        .first()
    )
    if latest is not None and latest.status == "completed":
        return latest

    candidate = IngestionJob(
        id=str(uuid.uuid4()),
        document_id=document_id,
        job_type=job_type,
        payload_json=dict(payload),
        status="queued",
        attempts=0,
    )
    try:
        # A savepoint contains only the candidate insert. Rolling it back after
        # a racing unique-index winner must not discard the caller's new
        # Document and ProjectDocument rows in the outer transaction.
        with db.begin_nested():
            db.add(candidate)
            db.flush()
    except IntegrityError:
        active = _active_job(db, document_id)
        if active is None:
            raise
        return active

    document = db.get(Document, document_id)
    if document is not None:
        document.status = "queued"
        document.error_message = None
    return candidate


def recover_abandoned_jobs(session_factory: sessionmaker) -> int:
    """Requeue jobs left running by a terminated application process.

    Args:
        session_factory: Factory that opens an independent recovery Session.

    Returns:
        Number of abandoned jobs returned to the queue.
    """
    with session_factory() as db:
        abandoned = (
            db.query(IngestionJob)
            .filter(IngestionJob.status == "running")
            .all()
        )
        for job in abandoned:
            job.status = "queued"
            job.started_at = None
            job.completed_at = None
            if job.document is not None and job.document.status == "processing":
                job.document.status = "queued"
                job.document.error_message = None
        db.commit()
        return len(abandoned)


def claim_next_job(session_factory: sessionmaker) -> Optional[str]:
    """Atomically claim the oldest queued job.

    Args:
        session_factory: Factory used only for this short claim transaction.

    Returns:
        Claimed job id, or None when no queued work exists.
    """
    with session_factory() as db:
        oldest_queued_id = (
            select(IngestionJob.id)
            .where(IngestionJob.status == "queued")
            .order_by(IngestionJob.created_at, IngestionJob.id)
            .limit(1)
            .scalar_subquery()
        )
        claimed = db.execute(
            update(IngestionJob)
            .where(
                IngestionJob.id == oldest_queued_id,
                IngestionJob.status == "queued",
            )
            .values(
                status="running",
                attempts=IngestionJob.attempts + 1,
                started_at=utc_now(),
                completed_at=None,
                last_error=None,
            )
            .returning(IngestionJob.id, IngestionJob.document_id)
        ).first()
        if claimed is None:
            db.rollback()
            return None

        job_id, document_id = claimed
        db.execute(
            update(Document)
            .where(Document.id == document_id)
            .values(status="processing", error_message=None)
        )
        db.commit()
        return job_id


def retain_operation_lease(job_id: str, lease: Optional[OperationLease]) -> None:
    """Transfer an in-process ingestion slot to one durable job.

    Args:
        job_id: Job that now owns the slot.
        lease: Request-acquired operation lease, if rate limiting is enabled.

    Returns:
        None.
    """
    if lease is None:
        return
    with _lease_lock:
        if job_id in _operation_leases:
            # An idempotent duplicate does not own a second durable operation.
            lease.release()
            return
        _operation_leases[job_id] = lease


def release_operation_lease(job_id: str) -> None:
    """Release the in-process slot owned by a terminal job.

    Args:
        job_id: Job whose processing ended.

    Returns:
        None.
    """
    with _lease_lock:
        lease = _operation_leases.pop(job_id, None)
    if lease is not None:
        lease.release()


def release_all_operation_leases() -> None:
    """Release queued leases when the owning application shuts down.

    Args:
        None.

    Returns:
        None.
    """
    with _lease_lock:
        leases = list(_operation_leases.values())
        _operation_leases.clear()
    for lease in leases:
        lease.release()


def notify_ingestion_worker() -> None:
    """Wake the active lifespan worker after a transaction commits.

    Args:
        None.

    Returns:
        None.
    """
    if _active_worker is not None:
        _active_worker.notify()


def _active_job(db: Session, document_id: str) -> Optional[IngestionJob]:
    """Return the active job for one document, if present."""
    return (
        db.query(IngestionJob)
        .filter(
            IngestionJob.document_id == document_id,
            IngestionJob.status.in_(ACTIVE_JOB_STATUSES),
        )
        .order_by(IngestionJob.created_at, IngestionJob.id)
        .first()
    )


class IngestionJobWorker:
    """Bounded worker retained for the FastAPI lifespan."""

    def __init__(
        self,
        session_factory: sessionmaker,
        processor: Optional[JobProcessor] = None,
        concurrency: int = 1,
        poll_interval: float = 0.25,
    ) -> None:
        """Configure a durable ingestion worker.

        Args:
            session_factory: Factory for claim and per-job Sessions.
            processor: Synchronous job pipeline; production is used when None.
            concurrency: Maximum number of simultaneously executing jobs.
            poll_interval: Maximum seconds before checking the queue again.

        Returns:
            None.
        """
        if concurrency < 1:
            raise ValueError("ingestion worker concurrency must be at least 1")
        if poll_interval <= 0:
            raise ValueError("ingestion worker poll interval must be positive")
        self.session_factory = session_factory
        self.processor = processor or self._process_with_document_service
        self.concurrency = concurrency
        self.poll_interval = poll_interval
        self._task: Optional[asyncio.Task] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._stop_event = asyncio.Event()
        self._wake_event = asyncio.Event()

    async def start(self) -> None:
        """Recover abandoned work and start the retained supervisor task.

        Args:
            None.

        Returns:
            None.
        """
        global _active_worker
        if self._task is not None and not self._task.done():
            return
        self._stop_event = asyncio.Event()
        self._wake_event = asyncio.Event()
        self._loop = asyncio.get_running_loop()
        await asyncio.to_thread(recover_abandoned_jobs, self.session_factory)
        _active_worker = self
        self._task = asyncio.create_task(
            self._run(),
            name="durable-ingestion-worker",
        )

    async def stop(self) -> None:
        """Stop claiming, await active jobs, and release process-local slots.

        Args:
            None.

        Returns:
            None.
        """
        global _active_worker
        task = self._task
        if task is None:
            release_all_operation_leases()
            return
        self._stop_event.set()
        self._wake_event.set()
        await task
        self._task = None
        self._loop = None
        if _active_worker is self:
            _active_worker = None
        release_all_operation_leases()

    def notify(self) -> None:
        """Wake the queue poller after newly committed work arrives.

        Args:
            None.

        Returns:
            None.
        """
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None
        if running_loop is loop:
            self._wake_event.set()
        else:
            loop.call_soon_threadsafe(self._wake_event.set)

    async def _run(self) -> None:
        """Claim bounded work until shutdown, then drain active jobs."""
        active_tasks = set()
        try:
            while not self._stop_event.is_set():
                while (
                    len(active_tasks) < self.concurrency
                    and not self._stop_event.is_set()
                ):
                    job_id = await asyncio.to_thread(
                        claim_next_job,
                        self.session_factory,
                    )
                    if job_id is None:
                        break
                    active_tasks.add(asyncio.create_task(
                        asyncio.to_thread(self._process_claimed_job, job_id),
                        name="ingestion-job-%s" % job_id,
                    ))

                if self._stop_event.is_set():
                    break
                if active_tasks:
                    done, _ = await asyncio.wait(
                        active_tasks,
                        timeout=self.poll_interval,
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    active_tasks.difference_update(done)
                    for task in done:
                        self._log_task_failure(task)
                else:
                    await self._wait_for_wake()
        finally:
            if active_tasks:
                results = await asyncio.gather(
                    *active_tasks,
                    return_exceptions=True,
                )
                for result in results:
                    if isinstance(result, BaseException):
                        logger.error(
                            "Ingestion worker task failed",
                            error_type=type(result).__name__,
                            error=str(result),
                        )

    async def _wait_for_wake(self) -> None:
        """Wait for enqueue notification or the bounded poll deadline."""
        try:
            await asyncio.wait_for(
                self._wake_event.wait(),
                timeout=self.poll_interval,
            )
        except asyncio.TimeoutError:
            pass
        finally:
            self._wake_event.clear()

    def _process_claimed_job(self, job_id: str) -> None:
        """Run one synchronous pipeline inside its own Session."""
        terminal_persisted = False
        try:
            with self.session_factory() as db:
                job = db.get(IngestionJob, job_id)
                if job is None or job.status != "running":
                    terminal_persisted = job is None
                    return
                try:
                    self._delete_document_index(db, job.document_id)
                    self.processor(db, job)
                    db.flush()
                    document = db.get(Document, job.document_id)
                    if document is None:
                        raise ValueError(
                            "Document %s not found" % job.document_id
                        )
                    if document.status != "ready":
                        raise RuntimeError(
                            "Ingestion processor ended with document status %s"
                            % document.status
                        )
                except Exception as error:
                    db.rollback()
                    failed_job = db.get(IngestionJob, job_id)
                    if failed_job is not None:
                        self._delete_document_index(db, failed_job.document_id)
                        failed_job.status = "failed"
                        failed_job.last_error = {
                            "type": type(error).__name__,
                            "message": str(error),
                        }
                        failed_job.completed_at = utc_now()
                        if failed_job.document is not None:
                            failed_job.document.status = "error"
                            failed_job.document.error_message = str(error)
                            if isinstance(error, ChunkLimitExceededError):
                                action = (
                                    "Reduce the source size or increase "
                                    "CHUNK_SIZE before retrying."
                                )
                                failed_job.document.error_message = (
                                    "%s. %s" % (error, action)
                                )
                                failed_job.document.meta_json = {
                                    **(failed_job.document.meta_json or {}),
                                    "indexing_failure": {
                                        "code": "chunk_limit_exceeded",
                                        "chunk_count": error.chunk_count,
                                        "max_chunks": error.max_chunks,
                                        "action": action,
                                    },
                                }
                        db.commit()
                        terminal_persisted = True
                    else:
                        # Deleting a running document cascades its durable job.
                        # No database row remains to own the process-local slot.
                        terminal_persisted = True
                    logger.error(
                        "Ingestion job failed",
                        job_id=job_id,
                        error_type=type(error).__name__,
                        error=str(error),
                    )
                    return

                completed_job = db.get(IngestionJob, job_id)
                if completed_job is not None:
                    completed_job.status = "completed"
                    completed_job.last_error = None
                    completed_job.completed_at = utc_now()
                    db.commit()
                    terminal_persisted = True
                else:
                    terminal_persisted = True
        finally:
            if terminal_persisted:
                release_operation_lease(job_id)

    @staticmethod
    def _delete_document_index(db: Session, document_id: str) -> None:
        """Delete chunks through ORM cascades so embeddings cannot orphan."""
        for chunk in (
            db.query(Chunk)
            .filter(Chunk.document_id == document_id)
            .all()
        ):
            db.delete(chunk)
        db.flush()

    @staticmethod
    def _process_with_document_service(db: Session, job: IngestionJob) -> None:
        """Run the production document pipeline for one claimed job."""
        # Imported lazily so schema/database unit tests do not load the
        # embedding model merely by importing the queue module.
        from app.services.documents import DocumentService

        DocumentService().process_ingestion_job(
            db,
            document_id=job.document_id,
            job_type=job.job_type,
            payload=dict(job.payload_json or {}),
        )

    @staticmethod
    def _log_task_failure(task: asyncio.Task) -> None:
        """Report supervisor-level failures without losing the retained task."""
        try:
            task.result()
        except Exception as error:
            logger.error(
                "Ingestion worker task failed",
                error_type=type(error).__name__,
                error=str(error),
            )

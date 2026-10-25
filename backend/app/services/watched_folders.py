"""Periodic imports from server folders explicitly configured by project owners."""
from __future__ import annotations

import asyncio
import hashlib
import os
import tempfile
import uuid
from pathlib import Path
from typing import Optional

import structlog
from sqlalchemy.orm import sessionmaker

from app.adapters.office import (
    SUPPORTED_AUDIO_EXTENSIONS,
    SUPPORTED_FILE_EXTENSIONS,
    SUPPORTED_IMAGE_EXTENSIONS,
    SUPPORTED_UPLOAD_EXTENSIONS,
)
from app.config import Settings
from app.db.models import Chunk, Document, IngestionJob, Project, ProjectDocument
from app.services.document_files import UPLOAD_DIR
from app.services.ingestion_jobs import (
    ACTIVE_JOB_STATUSES,
    _reserve_sqlite_enqueue_transaction,
    enqueue_ingestion_job_with_result,
    notify_ingestion_worker,
)
from app.services.retrieval_index import get_retrieval_index
from app.utils.time import utc_now

logger = structlog.get_logger()
POLL_INTERVAL_SECONDS = 60
REMOVED_MESSAGE = "This file was removed from the watched folder."


def resolve_watched_folder(root: str | Path, folder: str | Path) -> Path:
    """Resolve a project folder and reject paths outside the server root.

    Args:
        root: Server-configured directory exposed to the application.
        folder: Absolute folder path or a path relative to ``root``.

    Returns:
        The existing canonical folder path.

    Raises:
        ValueError: If either path is unavailable or the folder escapes root.
    """
    try:
        allowed_root = Path(root).expanduser().resolve(strict=True)
        candidate = Path(folder).expanduser()
        if not candidate.is_absolute():
            candidate = allowed_root / candidate
        resolved = candidate.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise ValueError("Watched folder must exist inside the configured root") from error

    if not allowed_root.is_dir() or not resolved.is_dir() or not resolved.is_relative_to(allowed_root):
        raise ValueError("Watched folder must exist inside the configured root")
    return resolved


def _hash_file(path: Path) -> str:
    """Hash a source without loading its full contents into memory."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _snapshot_folder(folder: Path, settings: Settings):
    """List safe paths, content hashes, and whether the scan was complete."""
    snapshot = {}
    seen = set()
    complete = True
    extensions = {
        "." + extension.strip().lower().lstrip(".")
        for extension in settings.allowed_file_types_list
        if extension.strip()
    } & SUPPORTED_UPLOAD_EXTENSIONS

    def onerror(_error):
        nonlocal complete
        complete = False

    for directory, directory_names, filenames in os.walk(
        folder,
        topdown=True,
        followlinks=False,
        onerror=onerror,
    ):
        current = Path(directory)
        for name in list(directory_names):
            child = current / name
            if child.is_symlink():
                directory_names.remove(name)
                try:
                    if not child.resolve(strict=True).is_relative_to(folder):
                        complete = False
                except OSError:
                    complete = False

        for name in filenames:
            candidate = current / name
            try:
                source = candidate.resolve(strict=True)
                if not source.is_relative_to(folder) or not source.is_file():
                    complete = False
                    continue
                seen.add(str(source))
                extension = source.suffix.lower()
                if extension not in extensions:
                    continue
                if extension in SUPPORTED_IMAGE_EXTENSIONS and not settings.ocr_enabled:
                    continue
                size = source.stat().st_size
                if size > settings.max_file_size_bytes:
                    logger.warning(
                        "Watched source exceeds the configured upload limit",
                        path=str(source),
                        size=size,
                    )
                    continue
                snapshot[str(source)] = {
                    "path": source,
                    "extension": extension,
                    "size": size,
                    "hash": _hash_file(source),
                }
            except OSError:
                complete = False
    return snapshot, seen, complete


def _copy_source(source: Path, target: Path, max_bytes: int) -> tuple[str, int]:
    """Copy a watched source into the app's private upload store and hash it."""
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".%s-" % target.name,
        dir=target.parent,
    )
    digest = hashlib.sha256()
    size = 0
    try:
        with os.fdopen(descriptor, "wb") as writer, source.open("rb") as reader:
            while block := reader.read(1024 * 1024):
                size += len(block)
                if size > max_bytes:
                    raise ValueError("Watched source exceeds the configured upload limit")
                digest.update(block)
                writer.write(block)
        os.replace(temporary_name, target)
    except Exception:
        Path(temporary_name).unlink(missing_ok=True)
        raise
    return digest.hexdigest(), size


def _queue_source(db, project, source, settings, created_files):
    """Create a project source and durable file job for a watched path."""
    document_id = str(uuid.uuid4())
    file_extension = source["extension"]
    source_type = "pdf" if file_extension == ".pdf" else file_extension[1:]
    job_type = "pdf" if file_extension == ".pdf" else "file"
    target = UPLOAD_DIR / (document_id + "_" + source["path"].name)
    file_hash, file_size = _copy_source(
        source["path"],
        target,
        settings.max_file_size_bytes,
    )
    created_files.append((target, document_id))
    document = Document(
        id=document_id,
        user_id=project.user_id,
        title=source["path"].name,
        source_type=source_type,
        source_url=str(target),
        status="queued",
        watch_source_path=str(source["path"]),
        watch_file_hash=file_hash,
        meta_json={
            "filename": source["path"].name,
            "file_extension": file_extension,
            "file_size": file_size,
        },
    )
    db.add(document)
    db.add(ProjectDocument(
        project_id=project.id,
        document_id=document_id,
        shared_by_user_id=project.user_id,
    ))
    db.flush()
    enqueue_ingestion_job_with_result(
        db,
        document_id=document_id,
        job_type=job_type,
        payload={"file_path": str(target)},
    )


def scan_watched_folders(session_factory: sessionmaker, settings: Settings) -> int:
    """Import changed files and remove missing files from the search index.

    Args:
        session_factory: Factory for short project transactions.
        settings: Server settings containing the allowed folder root.

    Returns:
        Number of durable ingestion jobs created.
    """
    if not settings.watched_folder_root:
        return 0
    try:
        root = Path(settings.watched_folder_root).expanduser().resolve(strict=True)
        if not root.is_dir():
            return 0
    except (OSError, RuntimeError):
        logger.error("Configured watched-folder root is unavailable")
        return 0

    with session_factory() as db:
        projects = db.query(Project.id, Project.watched_folder).filter(
            Project.watched_folder.isnot(None)
        ).all()

    jobs_created = 0
    for project_id, configured_folder in projects:
        try:
            folder = resolve_watched_folder(root, configured_folder)
            snapshot, seen, scan_complete = _snapshot_folder(folder, settings)
        except ValueError as error:
            logger.warning(
                "Skipping invalid watched folder",
                project_id=project_id,
                error=str(error),
            )
            continue

        created_files = []
        queued = 0
        try:
            with session_factory() as db:
                # SQLite serializes multiple API workers before they can create
                # duplicate documents for the same newly discovered path.
                _reserve_sqlite_enqueue_transaction(db)
                project = db.get(Project, project_id)
                if project is None or project.watched_folder != configured_folder:
                    db.rollback()
                    continue
                documents = db.query(Document).join(
                    ProjectDocument,
                    ProjectDocument.document_id == Document.id,
                ).filter(ProjectDocument.project_id == project_id).all()
                tracked = {
                    document.watch_source_path: document
                    for document in documents
                    if document.watch_source_path
                }
                active_ids = {
                    row[0]
                    for row in db.query(IngestionJob.document_id).filter(
                        IngestionJob.status.in_(ACTIVE_JOB_STATUSES)
                    ).all()
                }

                for path, source in snapshot.items():
                    document = tracked.get(path)
                    if document is None:
                        _queue_source(db, project, source, settings, created_files)
                        queued += 1
                        continue
                    if document.id in active_ids:
                        continue

                    removed_before = document.error_message == REMOVED_MESSAGE
                    if (
                        source["hash"] == document.watch_file_hash
                        and not removed_before
                    ):
                        if document.status == "ready":
                            document.last_synced_at = utc_now()
                            document.last_sync_changed = False
                        continue

                    copied_hash, _file_size = _copy_source(
                        source["path"],
                        Path(document.source_url),
                        settings.max_file_size_bytes,
                    )
                    document.watch_file_hash = copied_hash
                    file_path = document.source_url
                    enqueue = enqueue_ingestion_job_with_result(
                        db,
                        document_id=document.id,
                        job_type="resync",
                        payload={
                            "file_path": file_path,
                            "previous_status": document.status,
                            "previous_error_message": document.error_message,
                        },
                        force_new=True,
                    )
                    if enqueue.created_new_active:
                        queued += 1

                if scan_complete:
                    missing = set(tracked) - seen
                    for path in missing:
                        document = tracked[path]
                        if document.id in active_ids or document.error_message == REMOVED_MESSAGE:
                            continue
                        get_retrieval_index().delete_document(db, document.id)
                        for chunk in db.query(Chunk).filter(
                            Chunk.document_id == document.id
                        ).all():
                            db.delete(chunk)
                        document.status = "error"
                        document.error_message = REMOVED_MESSAGE
                        document.last_synced_at = utc_now()
                        document.last_sync_changed = True

                db.commit()
        except Exception:
            for path, document_id in created_files:
                try:
                    with session_factory() as verification_db:
                        durable_source = verification_db.get(Document, document_id)
                        durable_job = verification_db.query(IngestionJob.id).filter(
                            IngestionJob.document_id == document_id
                        ).first()
                except Exception:
                    durable_source = True
                    durable_job = True
                if durable_source is None and durable_job is None:
                    path.unlink(missing_ok=True)
            logger.exception("Watched-folder scan failed", project_id=project_id)
            continue

        jobs_created += queued
        if queued:
            try:
                notify_ingestion_worker()
            except Exception as error:
                logger.warning(
                    "Could not wake ingestion worker after watched-folder scan",
                    project_id=project_id,
                    error=str(error),
                )
    return jobs_created


class WatchedFolderWorker:
    """Run safe folder scans on a lifespan-owned periodic task."""

    def __init__(
        self,
        session_factory: sessionmaker,
        settings: Settings,
        poll_interval: int = POLL_INTERVAL_SECONDS,
    ) -> None:
        """Configure periodic scans.

        Args:
            session_factory: Factory used by each project scan.
            settings: Settings that define the allowed server root.
            poll_interval: Seconds between complete scans.
        """
        self.session_factory = session_factory
        self.settings = settings
        self.poll_interval = poll_interval
        self._task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        """Start polling only when the server has configured a root."""
        if self.settings.watched_folder_root and self._task is None:
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        """Finish the active scan and stop polling."""
        if self._task is None:
            return
        self._stop_event.set()
        await self._task
        self._task = None

    async def _run(self) -> None:
        """Scan immediately, then wait interruptibly between cycles."""
        while not self._stop_event.is_set():
            try:
                await asyncio.to_thread(
                    scan_watched_folders,
                    self.session_factory,
                    self.settings,
                )
            except Exception:
                logger.exception("Watched-folder worker failed")
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self.poll_interval,
                )
            except asyncio.TimeoutError:
                pass

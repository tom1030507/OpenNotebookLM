"""Application startup and shutdown resource management."""
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
import threading
from time import perf_counter

from fastapi import FastAPI
import structlog

from app.config import get_settings
from app.db.database import SessionLocal, init_db
from app.services.auth import get_auth_service
from app.services.admin_usage import sync_admin_users
from app.services.bootstrap import ensure_demo_account
from app.services.audio_overview_jobs import AudioOverviewWorker
from app.services.ingestion_jobs import IngestionJobWorker
from app.services.watched_folders import WatchedFolderWorker
from app.services.trash import purge_expired_trash

logger = structlog.get_logger()
TRASH_PURGE_INTERVAL_SECONDS = 24 * 60 * 60


async def _purge_trash(session_factory, retention_days: int) -> None:
    """Run hard deletion outside the event loop and keep startup available on errors.

    Args:
        session_factory: Factory for database sessions.
        retention_days: Number of days deleted items remain restorable.

    Returns:
        None.
    """
    try:
        removed = await asyncio.to_thread(
            purge_expired_trash,
            session_factory,
            retention_days,
        )
        if removed:
            logger.info("Expired trash items purged", count=removed)
    except Exception:
        logger.exception("Failed to purge expired trash items")


async def _purge_trash_periodically(session_factory, retention_days: int) -> None:
    """Purge expired items daily until the application shuts down.

    Args:
        session_factory: Factory for database sessions.
        retention_days: Number of days deleted items remain restorable.

    Returns:
        None.
    """
    while True:
        await asyncio.sleep(TRASH_PURGE_INTERVAL_SECONDS)
        await _purge_trash(session_factory, retention_days)


def warm_retrieval(app: FastAPI) -> None:
    """Build the question-answering service before the first question needs it.

    Building it imports torch and loads the embedding model, about 13 seconds
    on CPU. Left to the first question, that wait looks like a stalled chat
    (#242). This goes through the routes' own dependency, so the instance it
    builds is the one they reuse, and an app that overrides the dependency
    (the E2E server) warms its replacement rather than the real model.

    Args:
        app: Application whose question routes will use the service.

    Returns:
        None. A failure is logged; the first question then retries the load
        and reports its error.
    """
    from app.routers.query import get_rag_service

    started = perf_counter()
    try:
        app.dependency_overrides.get(get_rag_service, get_rag_service)()
    except Exception as exc:
        logger.warning(
            "Retrieval warm-up failed; the first question will load the models",
            error=str(exc),
        )
        return
    logger.info("Retrieval models ready", seconds=round(perf_counter() - started, 1))


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize and shut down resources owned by the application.

    Args:
        app: FastAPI application entering or leaving its lifespan.

    Returns:
        An async context manager that yields while the app is serving.
    """
    logger.info("Starting OpenNotebookLM", version="0.1.0")

    # Auth dependencies are otherwise built on the first protected request.
    # Resolve them now so a production instance cannot advertise readiness
    # while every authenticated request is guaranteed to fail.
    get_auth_service()

    init_db()
    logger.info("Database initialized")

    settings = get_settings()
    await _purge_trash(SessionLocal, settings.trash_retention_days)

    # A fresh database would otherwise be a locked door: public registration is
    # closed by default, so without this the only way in is a shell command.
    with SessionLocal() as db:
        demo_account = ensure_demo_account(
            db,
            get_auth_service(),
            enabled=settings.seed_demo_user,
            username=settings.demo_username,
            email=settings.demo_email,
            password=settings.demo_password,
        )
        sync_admin_users(db, settings.admin_emails_list)
    if demo_account is not None:
        # Warning, not info: this deployment publishes working credentials on
        # its sign-in page, and that belongs somewhere an operator will see it.
        logger.warning(
            "Demo account is enabled and its credentials are published on the "
            "sign-in page. Set SEED_DEMO_USER=false for any deployment others "
            "can reach.",
            username=demo_account.username,
        )

    if settings.rate_limit_requests is not None or settings.rate_limit_period is not None:
        logger.warning(
            "RATE_LIMIT_REQUESTS and RATE_LIMIT_PERIOD are not used; remove them "
            "from the environment. The enforced limits are listed under "
            "\"Rate limits\" in the README.",
        )

    Path("./data").mkdir(exist_ok=True)
    Path("./models").mkdir(exist_ok=True)
    Path("./uploads").mkdir(exist_ok=True)

    ingestion_worker = IngestionJobWorker(
        session_factory=SessionLocal,
        processor=getattr(app.state, "ingestion_job_processor", None),
        concurrency=settings.ingestion_worker_concurrency,
    )
    await ingestion_worker.start()
    app.state.ingestion_worker = ingestion_worker
    logger.info(
        "Durable ingestion worker started",
        concurrency=settings.ingestion_worker_concurrency,
    )

    watched_folder_worker = WatchedFolderWorker(SessionLocal, settings)
    await watched_folder_worker.start()
    app.state.watched_folder_worker = watched_folder_worker

    audio_overview_worker = AudioOverviewWorker(
        session_factory=SessionLocal,
        processor=getattr(app.state, "audio_overview_processor", None),
        enabled=settings.audio_overview_tts_enabled,
    )
    await audio_overview_worker.start()
    app.state.audio_overview_worker = audio_overview_worker
    logger.info(
        "Durable audio overview worker configured",
        concurrency=1,
        enabled=settings.audio_overview_tts_enabled,
    )

    # A thread, not a startup step: readiness and sign-in stay immediate. Daemon,
    # so stopping the server mid-load does not wait for the model to finish.
    threading.Thread(
        target=warm_retrieval, args=(app,), name="retrieval-warmup", daemon=True
    ).start()

    trash_purge_task = asyncio.create_task(
        _purge_trash_periodically(SessionLocal, settings.trash_retention_days)
    )
    try:
        yield
    finally:
        trash_purge_task.cancel()
        await asyncio.gather(trash_purge_task, return_exceptions=True)
        await watched_folder_worker.stop()
        await audio_overview_worker.stop()
        await ingestion_worker.stop()
        logger.info("Shutting down OpenNotebookLM")

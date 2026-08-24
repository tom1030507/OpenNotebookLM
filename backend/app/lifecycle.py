"""Application startup and shutdown resource management."""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
import structlog

from app.config import get_settings
from app.db.database import SessionLocal, init_db
from app.services.auth import get_auth_service
from app.services.ingestion_jobs import IngestionJobWorker

logger = structlog.get_logger()


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

    Path("./data").mkdir(exist_ok=True)
    Path("./models").mkdir(exist_ok=True)
    Path("./uploads").mkdir(exist_ok=True)

    settings = get_settings()
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

    try:
        yield
    finally:
        await ingestion_worker.stop()
        logger.info("Shutting down OpenNotebookLM")

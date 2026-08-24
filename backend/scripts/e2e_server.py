"""Run an isolated FastAPI instance for Playwright E2E tests."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


DEFAULT_FRONTEND_URL = "http://127.0.0.1:3100"
SUPPORTED_FRONTEND_HOSTS = {"localhost", "127.0.0.1", "::1"}


def resolve_frontend_url(raw_url: str | None) -> str:
    """Validate the single browser origin allowed to call the E2E backend.

    Args:
        raw_url: Candidate origin from E2E_FRONTEND_URL, or None for the
            direct Task 2 default.

    Returns:
        A safe HTTP origin on the fixed E2E frontend port.
    """
    candidate = DEFAULT_FRONTEND_URL if raw_url is None else raw_url
    try:
        parsed = urlsplit(candidate)
        port = parsed.port
    except ValueError as error:
        raise ValueError(f"Unsafe E2E frontend URL: {candidate}") from error
    if (
        not candidate
        or candidate != candidate.strip()
        or parsed.scheme != "http"
        or parsed.hostname not in SUPPORTED_FRONTEND_HOSTS
        or port != 3100
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(f"Unsafe E2E frontend URL: {candidate}")
    return candidate


def resolve_runtime_root(raw_path: str, repo_root: Path) -> Path:
    """Validate a run-specific directory beneath repository output/e2e.

    Args:
        raw_path: Candidate runtime path from E2E_RUNTIME_ROOT.
        repo_root: Resolved repository root.

    Returns:
        The resolved safe runtime directory.
    """
    if not raw_path.strip():
        raise ValueError("E2E runtime root is empty")
    root = repo_root.resolve()
    expected_parent = root / "output" / "e2e"
    lexical_candidate = Path(os.path.abspath(raw_path))
    unsafe_roots = {
        root,
        Path.home().resolve(),
        root / "output",
        expected_parent,
        root / "data",
        root / "uploads",
    }
    if (
        lexical_candidate in unsafe_roots
        or expected_parent not in lexical_candidate.parents
    ):
        raise ValueError(f"Unsafe E2E runtime root: {lexical_candidate}")

    allowed_parent = expected_parent.resolve()
    if allowed_parent != expected_parent or root not in allowed_parent.parents:
        raise ValueError(f"Unsafe E2E runtime root: {allowed_parent}")

    candidate = lexical_candidate.resolve()
    if candidate in unsafe_roots or allowed_parent not in candidate.parents:
        raise ValueError(f"Unsafe E2E runtime root: {candidate}")
    return candidate


def install_fast_overrides(application: Any) -> None:
    """Install deterministic substitutes at expensive/external boundaries.

    Args:
        application: FastAPI application receiving dependency overrides.

    Returns:
        None.
    """
    from app.adapters.pdf import PDFAdapter
    from app.routers.ingest import get_document_service
    from app.routers.query import get_rag_service
    from app.services.chunking import ChunkingService
    from app.services.documents import DocumentService
    from app.services.llm import LLMService
    from app.services.rag import RAGService
    from scripts.e2e_services import (
        DeterministicEmbeddingService,
        FixedURLAdapter,
        FixedYouTubeAdapter,
    )

    embedding = DeterministicEmbeddingService()
    document_service = DocumentService(
        chunking_service=ChunkingService(),
        embedding_service=embedding,
        pdf_adapter=PDFAdapter(use_pymupdf=False),
        url_adapter=FixedURLAdapter(),
        youtube_adapter=FixedYouTubeAdapter(),
    )
    rag_service = RAGService(
        embedding_service=embedding,
        llm_service=LLMService(),
    )

    def process_ingestion_job(db: Any, job: Any) -> str:
        """Run durable E2E jobs through the deterministic document graph.

        Args:
            db: Worker-owned database session.
            job: Claimed durable ingestion job.

        Returns:
            The final document status.
        """
        return document_service.process_ingestion_job(
            db,
            document_id=job.document_id,
            job_type=job.job_type,
            payload=dict(job.payload_json or {}),
        )

    application.dependency_overrides[get_document_service] = lambda: document_service
    application.dependency_overrides[get_rag_service] = lambda: rag_service
    application.state.ingestion_job_processor = process_ingestion_job


def create_application() -> tuple[Any, Any]:
    """Configure and create the isolated FastAPI application.

    Args:
        None.

    Returns:
        The application and its resolved settings.
    """
    repo_root = Path(__file__).resolve().parents[2]
    runtime_root = resolve_runtime_root(
        os.environ.get("E2E_RUNTIME_ROOT", ""), repo_root
    )
    frontend_url = resolve_frontend_url(os.environ.get("E2E_FRONTEND_URL"))
    runtime_root.mkdir(parents=True, exist_ok=True)
    os.chdir(runtime_root)
    database = runtime_root / "opennotebook.db"
    os.environ.update(
        {
            "APP_ENV": "test",
            "APP_PORT": "8100",
            "DEBUG": "false",
            "DB_PATH": str(database),
            "DATABASE_URL": f"sqlite:///{database.as_posix()}",
            "JWT_SECRET_KEY": "e2e-only-signing-key-not-a-secret",
            "ALLOW_PUBLIC_REGISTRATION": "true",
            "LLM_MODE": "none",
            "OPENAI_API_KEY": "",
            "CLAUDE_API_KEY": "",
            "YT_API_KEY": "",
            "RATE_LIMIT_ENABLED": "false",
            "CORS_ORIGINS": frontend_url,
            "ENABLE_YT_TRANSCRIPTION": "true",
        }
    )

    from app.config import get_settings

    get_settings.cache_clear()
    from app.main import app

    if os.environ.get("FULL_RAG_E2E") == "1":
        from app.routers.ingest import get_document_service
        from app.routers.query import get_rag_service

        get_document_service()
        get_rag_service()
    else:
        install_fast_overrides(app)
    return app, get_settings()


def main() -> None:
    """Start the single-process E2E backend.

    Args:
        None.

    Returns:
        None.
    """
    import uvicorn

    application, settings = create_application()
    uvicorn.run(
        application,
        host="127.0.0.1",
        port=settings.app_port,
        workers=1,
        reload=False,
    )


if __name__ == "__main__":
    main()

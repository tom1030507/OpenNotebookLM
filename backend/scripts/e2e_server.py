"""Run an isolated FastAPI instance for Playwright E2E tests."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any


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
    allowed_parent = (root / "output" / "e2e").resolve()
    candidate = Path(raw_path).resolve()
    if candidate == allowed_parent or allowed_parent not in candidate.parents:
        raise ValueError(f"Unsafe E2E runtime root: {candidate}")
    if candidate in {root, Path.home().resolve(), root / "data", root / "uploads"}:
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
    application.dependency_overrides[get_document_service] = lambda: document_service
    application.dependency_overrides[get_rag_service] = lambda: rag_service


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
            "LLM_MODE": "none",
            "OPENAI_API_KEY": "",
            "CLAUDE_API_KEY": "",
            "YT_API_KEY": "",
            "RATE_LIMIT_ENABLED": "false",
            "CORS_ORIGINS": "http://127.0.0.1:3100",
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

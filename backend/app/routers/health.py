"""Process liveness and database readiness routes."""
from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session
from sqlalchemy import text
import os
import psutil

from app.db.database import get_db
from app.config import get_settings
from app.utils.time import utc_now_iso

router = APIRouter()
settings = get_settings()


def _configured_llm() -> tuple:
    """Return the (provider, model) a question would be sent to.

    Mirrors the provider selection in services.llm without constructing a
    client, so a health check never performs network I/O.
    """
    mode = (settings.llm_mode or "auto").lower()
    if mode == "none":
        return None, None
    if mode in ("claude", "cloud", "auto") and settings.claude_api_key:
        return "claude", settings.claude_model
    if mode in ("openai", "cloud", "auto") and settings.openai_api_key:
        return "openai", settings.openai_model
    if mode in ("local", "auto"):
        return "local", settings.ollama_model
    return None, None


@router.get("/healthz")
async def health_check():
    """Report process liveness without depending on external resources.

    Args:
        None.

    Returns:
        Process, environment, and configured model metadata.
    """
    # Get system metrics
    process = psutil.Process(os.getpid())
    memory_info = process.memory_info()

    llm_provider, llm_model = _configured_llm()

    return {
        "ok": True,
        "timestamp": utc_now_iso(),
        "version": "0.1.0",
        "environment": settings.app_env,
        "database": "unchecked; use /readyz",
        "system": {
            "cpu_percent": psutil.cpu_percent(),
            "memory_mb": memory_info.rss / 1024 / 1024,
            "disk_usage_percent": psutil.disk_usage("/").percent,
        },
        "config": {
            "llm_mode": settings.llm_mode,
            # Which provider and model a question would actually be sent to.
            # Reported without a network probe, so this says "configured", not
            # "reachable" — a failed call is logged and reported per-answer as
            # model_used="fallback".
            "llm_provider": llm_provider,
            "llm_model": llm_model,
            "emb_backend": settings.emb_backend,
            "emb_model": settings.emb_model_name,
            "debug": settings.debug,
        }
    }


@router.get("/ready", include_in_schema=False)
@router.get("/readyz")
async def readiness_check(
    response: Response,
    db: Session = Depends(get_db),
):
    """Report whether the database can accept application traffic.

    Args:
        response: HTTP response whose status reflects readiness.
        db: Request-scoped database session.

    Returns:
        ``ok=true`` when the query succeeds, otherwise ``ok=false``.
    """
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        # Database errors can contain connection strings or credentials. The
        # status is actionable to an orchestrator without exposing internals.
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"ok": False}

    return {"ok": True}

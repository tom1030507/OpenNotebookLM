"""Generate project reports from caller-visible source chunks."""
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db.database import get_db
from app.db.models import User
from app.routers.auth import get_current_user
from app.routers.ownership import owned_document_ids, require_documents, require_project
from app.routers.query import get_rag_service
from app.routers.rate_limit import (
    acquire_account_lease,
    enforce_account_rate_limit,
    get_concurrency_limiter,
    get_rate_limiter,
)
from app.schemas import ReportRequest, ReportResponse
from app.services.rate_limit import (
    ConcurrencyLimiter,
    OperationLease,
    SlidingWindowRateLimiter,
    UnlimitedConcurrencyLease,
)
from app.services.report import ReportService

router = APIRouter(dependencies=[Depends(get_current_user)])


def get_report_service(rag_service: Any = Depends(get_rag_service)) -> ReportService:
    """Build the report adapter around the shared RAG service.

    Args:
        rag_service: Existing chunk retrieval and generation service.

    Returns:
        The report service for this request.
    """
    return ReportService(rag_service)


@router.post(
    "/projects/{project_id}/report",
    response_model=ReportResponse,
    response_model_exclude_none=True,
)
def project_report(
    project_id: str,
    request: ReportRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    service: ReportService = Depends(get_report_service),
    request_limiter: SlidingWindowRateLimiter = Depends(get_rate_limiter),
    concurrency_limiter: ConcurrencyLimiter = Depends(get_concurrency_limiter),
    settings: Settings = Depends(get_settings),
):
    """Generate a Markdown report from a visible project's selected sources.

    Args:
        project_id: Project to resolve through the caller's visibility.
        request: Report format, optional instruction, and source selection.
        db: Database session.
        current_user: Authenticated caller.
        service: Report generator backed by RAG.
        request_limiter: Per-account report request limiter.
        concurrency_limiter: Per-account active generation limiter.
        settings: Current abuse-control settings.

    Returns:
        Markdown and the cited passages used to write it.
    """
    project = require_project(db, project_id, current_user, min_role="viewer")
    document_ids = (
        owned_document_ids(db, current_user, project_id=project.id)
        if request.document_ids is None
        else require_documents(
            db, request.document_ids, current_user, project_id=project.id,
        )
    )

    lease: OperationLease = UnlimitedConcurrencyLease()
    if settings.rate_limit_enabled:
        enforce_account_rate_limit(
            request_limiter, "report", current_user.id, limit=10, window_seconds=60,
        )
        lease = acquire_account_lease(concurrency_limiter, "report", current_user.id)
    try:
        return service.generate(
            db,
            project.id,
            request.format,
            request.instruction,
            document_ids,
            request,
        )
    finally:
        lease.release()

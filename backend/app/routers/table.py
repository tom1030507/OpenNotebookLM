"""Routes for extracting source-grounded project tables."""
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
from app.schemas import TableRequest, TableResponse
from app.services.rate_limit import (
    ConcurrencyLimiter,
    OperationLease,
    SlidingWindowRateLimiter,
    UnlimitedConcurrencyLease,
)
from app.services.table import TableService

router = APIRouter(dependencies=[Depends(get_current_user)])


def get_table_service(rag_service: Any = Depends(get_rag_service)) -> TableService:
    """Build the table generator around the shared RAG service.

    Args:
        rag_service: Existing chunk retrieval and generation service.

    Returns:
        The table service for this request.
    """
    return TableService(rag_service)


@router.post("/projects/{project_id}/table", response_model=TableResponse)
def project_table(
    project_id: str,
    request: TableRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    service: TableService = Depends(get_table_service),
    request_limiter: SlidingWindowRateLimiter = Depends(get_rate_limiter),
    concurrency_limiter: ConcurrencyLimiter = Depends(get_concurrency_limiter),
    settings: Settings = Depends(get_settings),
):
    """Generate a table from sources visible to the authenticated caller.

    Args:
        project_id: Project to resolve through the caller's visibility.
        request: Extraction instruction, optional columns, and source selection.
        db: Database session.
        current_user: Authenticated caller.
        service: Table generator backed by RAG.
        request_limiter: Per-account table request limiter.
        concurrency_limiter: Per-account active generation limiter.
        settings: Current abuse-control settings.

    Returns:
        A validated table with source references for its nonempty cells.
    """
    project = require_project(db, project_id, current_user, min_role="viewer")
    document_ids = (
        owned_document_ids(db, current_user, project_id=project.id)
        if request.source_ids is None
        else require_documents(db, request.source_ids, current_user, project_id=project.id)
    )

    lease: OperationLease = UnlimitedConcurrencyLease()
    if settings.rate_limit_enabled:
        enforce_account_rate_limit(
            request_limiter, "table", current_user.id, limit=10, window_seconds=60,
        )
        lease = acquire_account_lease(concurrency_limiter, "table", current_user.id)
    try:
        return service.generate(
            db, project.id, request.instruction, request.columns, document_ids,
        )
    finally:
        lease.release()

"""Routes for generating source-grounded study materials."""
from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db.database import get_db
from app.db.models import User
from app.routers.auth import get_current_user
from app.routers.ownership import require_documents, require_project
from app.routers.rate_limit import (
    acquire_account_lease,
    enforce_account_rate_limit,
    get_concurrency_limiter,
    get_rate_limiter,
)
from app.schemas import FlashcardsResponse, QuizResponse, StudyRequest
from app.services.study import StudyService
from app.services.admin_usage import track_studio_generation
from app.services.rate_limit import (
    ConcurrencyLimiter,
    OperationLease,
    SlidingWindowRateLimiter,
    UnlimitedConcurrencyLease,
)
from app.utils.time import utc_now

router = APIRouter(dependencies=[Depends(get_current_user)])
_service = StudyService()


def get_study_service() -> StudyService:
    """Provide the shared study generator for one request.

    Returns:
        The service that creates flashcards and quiz questions.
    """
    return _service


def _begin_study(
    user_id: str,
    settings: Settings,
    request_limiter: SlidingWindowRateLimiter,
    concurrency_limiter: ConcurrencyLimiter,
) -> OperationLease:
    """Apply per-account generation limits and return the active lease.

    Args:
        user_id: Authenticated account identifier.
        settings: Current rate-limit configuration.
        request_limiter: Shared sliding-window limiter.
        concurrency_limiter: Shared per-account concurrency limiter.

    Returns:
        A lease that keeps this generation within the account's concurrency
        allowance until the request finishes.
    """
    if not settings.rate_limit_enabled:
        return UnlimitedConcurrencyLease()
    enforce_account_rate_limit(
        request_limiter,
        "study",
        user_id,
        limit=10,
        window_seconds=60,
    )
    return acquire_account_lease(concurrency_limiter, "study", user_id)


@router.post("/projects/{project_id}/flashcards", response_model=FlashcardsResponse)
def project_flashcards(
    project_id: str,
    request: Optional[StudyRequest] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    service: StudyService = Depends(get_study_service),
    request_limiter: SlidingWindowRateLimiter = Depends(get_rate_limiter),
    concurrency_limiter: ConcurrencyLimiter = Depends(get_concurrency_limiter),
    settings: Settings = Depends(get_settings),
):
    """Generate temporary flashcards from selected ready project sources.

    Args:
        project_id: Project to resolve through the caller's visibility.
        request: Optional source selection, item count, and focus.
        db: Database session.
        current_user: Authenticated caller.
        service: Study material generator.
        request_limiter: Per-account study generation limiter.
        concurrency_limiter: Per-account active generation limiter.
        settings: Current abuse-control settings.

    Returns:
        Cards and citation metadata for the generated sources.
    """
    project = require_project(db, project_id, current_user, min_role="viewer")
    options = request or StudyRequest()
    document_ids = None
    if options.document_ids is not None:
        document_ids = require_documents(
            db, options.document_ids, current_user, project_id=project_id,
        )
    lease = _begin_study(
        current_user.id, settings, request_limiter, concurrency_limiter,
    )
    try:
        with track_studio_generation(db, current_user.id):
            return {
                **service.generate_flashcards(
                    db, project, document_ids, options.count, options.focus,
                ),
                "project_id": project.id,
                "project_name": project.name,
                "generated_at": utc_now(),
            }
    finally:
        lease.release()


@router.post("/projects/{project_id}/quiz", response_model=QuizResponse)
def project_quiz(
    project_id: str,
    request: Optional[StudyRequest] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    service: StudyService = Depends(get_study_service),
    request_limiter: SlidingWindowRateLimiter = Depends(get_rate_limiter),
    concurrency_limiter: ConcurrencyLimiter = Depends(get_concurrency_limiter),
    settings: Settings = Depends(get_settings),
):
    """Generate temporary quiz questions from selected ready sources.

    Args:
        project_id: Project to resolve through the caller's visibility.
        request: Optional source selection, item count, and focus.
        db: Database session.
        current_user: Authenticated caller.
        service: Study material generator.
        request_limiter: Per-account study generation limiter.
        concurrency_limiter: Per-account active generation limiter.
        settings: Current abuse-control settings.

    Returns:
        Questions and citation metadata for the generated sources.
    """
    project = require_project(db, project_id, current_user, min_role="viewer")
    options = request or StudyRequest()
    document_ids = None
    if options.document_ids is not None:
        document_ids = require_documents(
            db, options.document_ids, current_user, project_id=project_id,
        )
    lease = _begin_study(
        current_user.id, settings, request_limiter, concurrency_limiter,
    )
    try:
        with track_studio_generation(db, current_user.id):
            return {
                **service.generate_quiz(
                    db, project, document_ids, options.count, options.focus,
                ),
                "project_id": project.id,
                "project_name": project.name,
                "generated_at": utc_now(),
            }
    finally:
        lease.release()

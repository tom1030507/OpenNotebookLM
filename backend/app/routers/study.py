"""Routes for generating source-grounded study materials."""
from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import User
from app.routers.auth import get_current_user
from app.routers.ownership import require_documents, require_project
from app.schemas import FlashcardsResponse, QuizResponse, StudyRequest
from app.services.study import StudyService
from app.utils.time import utc_now

router = APIRouter(dependencies=[Depends(get_current_user)])
_service = StudyService()


def get_study_service() -> StudyService:
    """Provide the shared study generator for one request.

    Returns:
        The service that creates flashcards and quiz questions.
    """
    return _service


@router.post("/projects/{project_id}/flashcards", response_model=FlashcardsResponse)
def project_flashcards(
    project_id: str,
    request: Optional[StudyRequest] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    service: StudyService = Depends(get_study_service),
):
    """Generate temporary flashcards from selected ready project sources.

    Args:
        project_id: Project to resolve through the caller's visibility.
        request: Optional source selection, item count, and focus.
        db: Database session.
        current_user: Authenticated caller.
        service: Study material generator.

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
    return {
        **service.generate_flashcards(
            db, project, document_ids, options.count, options.focus,
        ),
        "project_id": project.id,
        "project_name": project.name,
        "generated_at": utc_now(),
    }


@router.post("/projects/{project_id}/quiz", response_model=QuizResponse)
def project_quiz(
    project_id: str,
    request: Optional[StudyRequest] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    service: StudyService = Depends(get_study_service),
):
    """Generate temporary quiz questions from selected ready sources.

    Args:
        project_id: Project to resolve through the caller's visibility.
        request: Optional source selection, item count, and focus.
        db: Database session.
        current_user: Authenticated caller.
        service: Study material generator.

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
    return {
        **service.generate_quiz(
            db, project, document_ids, options.count, options.focus,
        ),
        "project_id": project.id,
        "project_name": project.name,
        "generated_at": utc_now(),
    }

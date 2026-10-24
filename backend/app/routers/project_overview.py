"""Project overview and suggested-question routes.

Both routes are plain `def`: they block on the LLM, and FastAPI runs sync
handlers in its threadpool instead of stalling the event loop (see
`routers.mindmap`).
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import User
from app.routers.auth import get_current_user
from app.routers.ownership import require_conversation, require_project
from app.schemas import FollowUpResponse, ProjectOverviewResponse
from app.services.project_overview import ProjectOverviewService

router = APIRouter(dependencies=[Depends(get_current_user)])

_service = ProjectOverviewService()


def get_project_overview_service() -> ProjectOverviewService:
    """Provide the shared service; a dependency so tests can inject an offline model.

    Returns:
        The shared service.
    """
    return _service


@router.get("/projects/{project_id}/overview", response_model=ProjectOverviewResponse)
def project_overview(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    service: ProjectOverviewService = Depends(get_project_overview_service),
):
    """Read one of the caller's projects' overview, generating it when stale.

    Args:
        project_id: Project to resolve through the caller's ownership.
        db: Database session.
        current_user: Authenticated caller.
        service: Overview generator.

    Returns:
        The project's name, overview and suggested questions.
    """
    project = require_project(db, project_id, current_user)
    return service.overview(db, project)


@router.post("/conversations/{conversation_id}/follow-ups", response_model=FollowUpResponse)
def conversation_follow_ups(
    conversation_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    service: ProjectOverviewService = Depends(get_project_overview_service),
):
    """Suggest follow-up questions to the last answer in a caller's conversation.

    Args:
        conversation_id: Conversation to resolve through the caller's ownership.
        db: Database session.
        current_user: Authenticated caller.
        service: Question generator.

    Returns:
        Up to two follow-up questions.
    """
    conversation = require_conversation(db, conversation_id, current_user)
    return {"questions": service.follow_ups(conversation)}

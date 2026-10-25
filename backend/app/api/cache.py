"""Ownership-scoped cache invalidation endpoints."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
import structlog
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import Project, ProjectDocument, ProjectMember, User
from app.services.cache import cache_service
from app.routers.auth import get_current_user
from app.routers.ownership import require_document, require_project

logger = structlog.get_logger()

# Authentication belongs on the router so any future endpoint is protected by
# default. Ownership is still resolved inside each resource-specific handler.
router = APIRouter(
    prefix="/api/cache",
    tags=["Cache"],
    dependencies=[Depends(get_current_user)],
)


class CacheInvalidateResponse(BaseModel):
    """Cache invalidation response."""

    invalidated: int
    target_type: str
    target_id: str


@router.delete("/invalidate/project/{project_id}", response_model=CacheInvalidateResponse)
async def invalidate_project_cache(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CacheInvalidateResponse:
    """Invalidate cached query results for one project the caller owns.

    Args:
        project_id: Project id to invalidate.
        db: Request database session.
        current_user: Authenticated caller.

    Returns:
        Number of logical project cache scopes invalidated.
    """
    require_project(db, project_id, current_user, min_role="editor")

    try:
        count = cache_service.invalidate_project_cache(project_id)
        return CacheInvalidateResponse(
            invalidated=count,
            target_type="project",
            target_id=project_id,
        )
    except Exception as error:
        logger.error("Failed to invalidate project cache", error=str(error))
        raise HTTPException(status_code=500, detail=str(error)) from error


@router.delete("/invalidate/document/{document_id}", response_model=CacheInvalidateResponse)
async def invalidate_document_cache(
    document_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CacheInvalidateResponse:
    """Invalidate cached data for a document the caller owns or edits through a project.

    Args:
        document_id: Document id to invalidate.
        db: Request database session.
        current_user: Authenticated caller.

    Returns:
        Number of logical document cache scopes invalidated.
    """
    document = require_document(db, document_id, current_user)
    if document.user_id != current_user.id:
        editable_link = db.query(ProjectDocument.project_id).join(
            Project, Project.id == ProjectDocument.project_id
        ).outerjoin(
            ProjectMember, ProjectMember.project_id == Project.id
        ).filter(
            ProjectDocument.document_id == document_id,
            or_(
                Project.user_id == current_user.id,
                and_(
                    ProjectMember.user_id == current_user.id,
                    ProjectMember.role == "editor",
                ),
            ),
        ).first()
        if editable_link is None:
            raise HTTPException(status_code=404, detail="Document not found")

    try:
        count = cache_service.invalidate_document_cache(document_id)
        return CacheInvalidateResponse(
            invalidated=count,
            target_type="document",
            target_id=document_id,
        )
    except Exception as error:
        logger.error("Failed to invalidate document cache", error=str(error))
        raise HTTPException(status_code=500, detail=str(error)) from error

"""Export router for exporting conversations and projects."""
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response, FileResponse
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask
from starlette.types import Receive, Scope, Send
import structlog

from app.db.database import get_db
from app.db.models import User
from app.schemas import SourceSelection
from app.services.export import ExportService, MAX_BATCH_EXPORT_CONVERSATIONS
from app.services.project_overview import (
    ProjectOverviewService,
    get_project_overview_service,
)
from app.utils.time import utc_now
from app.routers.auth import get_current_user
from app.routers.ownership import require_conversation, require_documents, require_project

# Every route below requires a signed-in caller. Declaring that on the
# router rather than on each handler means an endpoint added later is
# protected by default, and it travels with the router wherever it is
# mounted.
router = APIRouter(dependencies=[Depends(get_current_user)])
logger = structlog.get_logger()

# Initialize export service
export_service = ExportService()


def _remove_exact_file(path) -> None:
    """Remove one generated file without deriving or widening its path."""
    Path(path).unlink(missing_ok=True)


class CleanupFileResponse(FileResponse):
    """File response that cannot skip cleanup on an early or failed send."""

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        """Send the file and then remove its exact path in every outcome.

        Args:
            scope: ASGI request scope.
            receive: ASGI receive callable.
            send: ASGI send callable.

        Returns:
            None.
        """
        try:
            await super().__call__(scope, receive, send)
        finally:
            # FileResponse skips its BackgroundTask on some 400/416 Range
            # returns, while this outer guard runs for every response path.
            _remove_exact_file(self.path)


@router.get("/export/conversation/{conversation_id}")
async def export_conversation(
    conversation_id: str,
    format: str = "markdown",
    include_citations: bool = True,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Export one of the caller's conversations to various formats.
    
    Supported formats: markdown, json, txt
    """
    # Validate format
    if format not in ["markdown", "json", "txt"]:
        raise HTTPException(status_code=400, detail="Invalid export format")
    
    conversation = require_conversation(db, conversation_id, current_user)
    
    try:
        # Export conversation
        content, content_type, filename = export_service.export_conversation(
            db=db,
            conversation=conversation,
            format=format,
            include_citations=include_citations
        )
        
        return Response(
            content=content,
            media_type=content_type,
            headers={
                "Content-Disposition": f"attachment; filename={filename}"
            }
        )
        
    except Exception as e:
        logger.error(f"Export failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/export/project/{project_id}")
async def export_project(
    project_id: str,
    format: str = "json",
    include_documents: bool = True,
    include_conversations: bool = True,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Export a visible project with source metadata and caller-owned chats.
    """
    # Validate format
    if format not in ["json", "markdown"]:
        raise HTTPException(status_code=400, detail="Invalid export format")
    
    project = require_project(db, project_id, current_user, min_role="viewer")
    
    try:
        # Export project
        content, content_type, filename = export_service.export_project(
            db=db,
            project=project,
            user_id=current_user.id,
            format=format,
            include_documents=include_documents,
            include_conversations=include_conversations
        )
        
        return Response(
            content=content,
            media_type=content_type,
            headers={
                "Content-Disposition": f"attachment; filename={filename}"
            }
        )
        
    except Exception as e:
        logger.error(f"Project export failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/export/project/{project_id}/summary")
def export_project_summary(
    project_id: str,
    selection: Optional[SourceSelection] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    service: ProjectOverviewService = Depends(get_project_overview_service),
):
    """Export a grounded summary report of one of the caller's projects.

    Args:
        project_id: Project to resolve through the current user's access.
        selection: Optional subset of sources to report on; omitted means all.
        db: Database session.
        current_user: Authenticated caller.
        service: Shared grounded-summary generator.

    Returns:
        The source summary as a Markdown attachment.
    """
    project = require_project(db, project_id, current_user, min_role="viewer")
    # Resolved before the try below, which would turn a 404 into a 500.
    document_ids = None
    if selection and selection.document_ids is not None:
        document_ids = require_documents(
            db, selection.document_ids, current_user, project_id=project_id
        )

    try:
        summary = service.summary(db, project, document_ids)
        report = (
            f"# Project Summary: {project.name}\n\n"
            "## Overview\n\n"
            f"{summary or 'No summary is available for the selected sources.'}\n"
        )
        
        return Response(
            content=report,
            media_type="text/markdown",
            headers={
                "Content-Disposition": f"attachment; filename=project_{project_id}_summary.md"
            }
        )
        
    except Exception as e:
        logger.error(f"Summary generation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/export/batch")
async def batch_export(
    conversation_ids: list[str],
    format: str = "json",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Export several of the caller's conversations at once.

    Args:
        conversation_ids: Conversation IDs to export in request order.
        format: Member export format.
        db: Request database session.
        current_user: Authenticated user that must own every conversation.

    Returns:
        A ZIP file response with exact-path cleanup.
    """
    if not conversation_ids:
        raise HTTPException(status_code=400, detail="No conversation IDs provided")

    if len(conversation_ids) > MAX_BATCH_EXPORT_CONVERSATIONS:
        raise HTTPException(
            status_code=400,
            detail=(
                "A batch export may contain at most "
                f"{MAX_BATCH_EXPORT_CONVERSATIONS} conversations"
            ),
        )

    if format not in ["markdown", "json", "txt"]:
        raise HTTPException(status_code=400, detail="Invalid export format")

    # Every id is checked before any of them is exported, so a batch cannot be
    # used to smuggle one other account's conversation in among your own.
    for conversation_id in conversation_ids:
        require_conversation(db, conversation_id, current_user)

    zip_path = None
    try:
        zip_path = export_service.batch_export_conversations(
            db=db,
            conversation_ids=conversation_ids,
            format=format
        )

        if not zip_path or not Path(zip_path).is_file():
            raise RuntimeError("Export failed")

        return CleanupFileResponse(
            path=zip_path,
            media_type="application/zip",
            filename=(
                "conversations_export_"
                f"{utc_now().strftime('%Y%m%d_%H%M%S')}.zip"
            ),
            # Keep the conventional successful-response cleanup as well as the
            # response's finally guard. Exact deletion is idempotent.
            background=BackgroundTask(_remove_exact_file, zip_path),
        )

    except Exception as e:
        if zip_path:
            _remove_exact_file(zip_path)
        logger.error(f"Batch export failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

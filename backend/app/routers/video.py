"""Video summary router.

Studio's video summary is a derived view of a project rather than a download —
the browser plays the script it returns — so it answers JSON and lives beside
the project it describes instead of under `/export`.

The route is a plain `def`. Writing the script blocks on the LLM for as long as
the model takes, and the container runs a single uvicorn worker: on the event
loop that stalls every other request for the whole call, `/healthz` included,
which the compose healthcheck gives ten seconds. FastAPI runs a sync handler in
its threadpool, which is where blocking work belongs.
"""
import re
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session
import structlog

from app.db.database import get_db
from app.db.models import User
from app.routers.auth import get_current_user
from app.routers.ownership import require_documents, require_project
from app.schemas import StudioSourceSelection, VideoSummaryPptxRequest, VideoSummaryResponse
from app.services.slides_export import render_video_summary_pptx
from app.services.video_summary import VideoSummaryService, VideoSummaryTooLargeError

# Every route below requires a signed-in caller. Declaring that on the
# router rather than on each handler means an endpoint added later is
# protected by default, and it travels with the router wherever it is
# mounted.
router = APIRouter(dependencies=[Depends(get_current_user)])
logger = structlog.get_logger()

# Built once: `LLMService` selects a provider without any network I/O, and
# rebuilding it per request would repeat that selection and its logging. Safe to
# share now that requests are handled in a threadpool because the service keeps
# nothing about one script on itself — what wrote the scenes comes back from
# `generate`, so two scripts being built at once cannot read each other's answer.
_service = VideoSummaryService()


def get_video_summary_service() -> VideoSummaryService:
    """Provide the video summary service.

    A dependency rather than a module-level reference so a test can inject a
    service that never reaches for a model server — with `LLM_MODE` defaulting
    to `auto`, the real one points at a local provider.

    Returns:
        The shared service.
    """
    return _service


@router.post(
    "/projects/{project_id}/video-summary",
    response_model=VideoSummaryResponse,
)
def project_video_summary(
    project_id: str,
    selection: Optional[StudioSourceSelection] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    service: VideoSummaryService = Depends(get_video_summary_service),
):
    """Build the video summary script for one of the caller's projects.

    The script is a title card, one scene per source, and a closing recap. The
    source scenes are written by the configured LLM when there is one; otherwise
    they are extracted from the documents themselves, and `model_used` says so.

    Args:
        project_id: Project to resolve through the current user's ownership.
        selection: Optional subset of sources to cover; omitted covers them all.
        db: Database session.
        current_user: Authenticated caller.
        service: Video summary generator.

    Returns:
        The scenes and generation metadata.
    """
    project = require_project(db, project_id, current_user, min_role="viewer")
    document_ids = None
    if selection and selection.document_ids is not None:
        document_ids = require_documents(
            db, selection.document_ids, current_user, project_id=project_id
        )

    try:
        return service.generate(db, project, document_ids, selection)
    except VideoSummaryTooLargeError as error:
        raise HTTPException(status_code=413, detail=str(error)) from error


@router.post("/projects/{project_id}/video-summary/pptx")
def export_project_video_summary_pptx(
    project_id: str,
    request: VideoSummaryPptxRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Export the scenes already shown in Studio as a PowerPoint.

    Args:
        project_id: Project to resolve through the current user's ownership.
        request: Bounded scene script to render without another model call.
        db: Database session.
        current_user: Authenticated caller.

    Returns:
        The PowerPoint bytes with a safe project-based download filename.
    """
    project = require_project(db, project_id, current_user, min_role="viewer")
    document_ids = [scene.document_id for scene in request.scenes if scene.document_id]
    if document_ids:
        require_documents(db, document_ids, current_user, project_id=project_id)

    filename = re.sub(r'[\\/<>:"|?*\x00-\x1f\x7f]+', "_", project.name).strip(" .")
    filename = "%s.pptx" % (filename or "video-summary")

    return Response(
        content=render_video_summary_pptx(request.scenes),
        media_type=(
            "application/vnd.openxmlformats-officedocument.presentationml.presentation"
        ),
        headers={
            "Content-Disposition": "attachment; filename*=utf-8''%s"
            % quote(filename, safe=""),
        },
    )

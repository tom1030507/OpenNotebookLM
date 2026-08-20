"""Video summary router.

Studio's video summary is a derived view of a project rather than a download —
the browser plays the script it returns — so it answers JSON and lives beside
the project it describes instead of under `/export`.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
import structlog

from app.db.database import get_db
from app.db.models import User
from app.routers.auth import get_current_user
from app.routers.ownership import require_project
from app.schemas import VideoSummaryResponse
from app.services.video_summary import VideoSummaryService

# Every route below requires a signed-in caller. Declaring that on the
# router rather than on each handler means an endpoint added later is
# protected by default, and it travels with the router wherever it is
# mounted.
router = APIRouter(dependencies=[Depends(get_current_user)])
logger = structlog.get_logger()

# Built once: `LLMService` selects a provider without any network I/O, and
# rebuilding it per request would repeat that selection and its logging.
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


@router.get(
    "/projects/{project_id}/video-summary",
    response_model=VideoSummaryResponse,
)
async def project_video_summary(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    service: VideoSummaryService = Depends(get_video_summary_service),
):
    """Build the video summary script for one of the caller's projects.

    The script is a title card, one scene per source, and a closing recap. The
    source scenes are written by the configured LLM when there is one; otherwise
    they are extracted from the documents themselves, and `model_used` says so.
    """
    project = require_project(db, project_id, current_user)

    return service.generate(db, project)

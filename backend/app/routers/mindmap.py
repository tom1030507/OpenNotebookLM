"""Mind map router.

Studio's mind map is a derived view of a project rather than a download, so it
answers JSON and lives beside the project it describes instead of under
`/export`.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
import structlog

from app.db.database import get_db
from app.db.models import User
from app.routers.auth import get_current_user
from app.routers.ownership import require_project
from app.schemas import MindMapResponse
from app.services.mindmap import MindMapService

# Every route below requires a signed-in caller. Declaring that on the
# router rather than on each handler means an endpoint added later is
# protected by default, and it travels with the router wherever it is
# mounted.
router = APIRouter(dependencies=[Depends(get_current_user)])
logger = structlog.get_logger()

# Built once: `LLMService` selects a provider without any network I/O, and
# rebuilding it per request would repeat that selection and its logging.
_service = MindMapService()


def get_mindmap_service() -> MindMapService:
    """Provide the mind map service.

    A dependency rather than a module-level reference so a test can inject a
    service that never reaches for a model server — with `LLM_MODE` defaulting
    to `auto`, the real one points at a local provider.

    Returns:
        The shared service.
    """
    return _service


@router.get("/projects/{project_id}/mindmap", response_model=MindMapResponse)
async def project_mindmap(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    service: MindMapService = Depends(get_mindmap_service),
):
    """Build a mind map of one of the caller's projects.

    The map is a project root, a branch per source, and the topics inside each
    source. Topics are named by the configured LLM when there is one; otherwise
    they come from the documents' own structure, and `model_used` says so.
    """
    project = require_project(db, project_id, current_user)

    return service.generate(db, project)

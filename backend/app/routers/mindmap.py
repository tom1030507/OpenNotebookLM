"""Mind map router.

Studio's mind map is a derived view of a project rather than a download, so it
answers JSON and lives beside the project it describes instead of under
`/export`.

The route is a plain `def`. Naming a project's topics blocks on the LLM for as
long as the model takes, and the container runs a single uvicorn worker: on the
event loop that stalls every other request for the whole call, `/healthz`
included, which the compose healthcheck gives ten seconds. FastAPI runs a sync
handler in its threadpool, which is where blocking work belongs.
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
# rebuilding it per request would repeat that selection and its logging. Safe to
# share now that requests are handled in a threadpool because the service keeps
# nothing about one map on itself — what named the topics comes back from
# `generate`, so two maps being built at once cannot read each other's answer.
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


@router.post("/projects/{project_id}/mindmap", response_model=MindMapResponse)
def project_mindmap(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    service: MindMapService = Depends(get_mindmap_service),
):
    """Build a mind map of one of the caller's projects.

    The configured LLM organizes ready sources into a subject and nested
    concepts. Otherwise the map preserves source heading structure, with
    `model_used` identifying the fallback.

    Args:
        project_id: Project to resolve through the current user's ownership.
        db: Database session.
        current_user: Authenticated caller.
        service: Mind map generator.

    Returns:
        The recursive tree and generation metadata.
    """
    project = require_project(db, project_id, current_user)

    return service.generate(db, project)

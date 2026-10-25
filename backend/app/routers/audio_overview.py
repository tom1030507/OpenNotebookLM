"""Create and serve durable, project-scoped audio overviews."""
import structlog
import uuid
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db.database import get_db
from app.db.models import AudioOverview, User
from app.routers.auth import get_current_user
from app.routers.ownership import require_documents, require_project
from app.routers.rate_limit import enforce_account_rate_limit, get_rate_limiter
from app.schemas import (
    AudioOverviewCreate,
    AudioOverviewListResponse,
    AudioOverviewResponse,
    AudioOverviewVoice,
)
from app.services.audio_overview import (
    VOICE_PREVIEW_TEXT,
    audio_overview_file_key,
    get_kokoro_tts,
    remove_audio_file,
    resolve_audio_file,
)
from app.services.audio_overview_jobs import AudioOverviewWorker
from app.services.rate_limit import SlidingWindowRateLimiter
from app.services.source_digest import project_documents

router = APIRouter(dependencies=[Depends(get_current_user)])
logger = structlog.get_logger(__name__)


def get_audio_overview_worker(request: Request) -> AudioOverviewWorker:
    """Get the worker retained for the application lifespan.

    Args:
        request: Current FastAPI request.

    Returns:
        The lifespan-owned worker.
    """
    worker = getattr(request.app.state, "audio_overview_worker", None)
    if worker is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Audio overview worker is unavailable",
        )
    return worker


def _response(overview: AudioOverview) -> dict:
    """Shape one ORM row without exposing its local filesystem path."""
    return {
        "id": overview.id,
        "status": overview.status,
        "options": overview.options_json or {},
        "script": overview.script_json or [],
        "duration_seconds": overview.duration_seconds,
        "error": overview.error,
        "created_at": overview.created_at,
        "updated_at": overview.updated_at,
        "started_at": overview.started_at,
        "completed_at": overview.completed_at,
    }


def _owned_overview(
    db: Session,
    project_id: str,
    overview_id: str,
) -> AudioOverview:
    overview = db.query(AudioOverview).filter(
        AudioOverview.id == overview_id,
        AudioOverview.project_id == project_id,
    ).first()
    if overview is None:
        raise HTTPException(status_code=404, detail="Audio overview not found")
    return overview


@router.post(
    "/projects/{project_id}/audio-overviews",
    response_model=AudioOverviewResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_audio_overview(
    project_id: str,
    request_data: AudioOverviewCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
    worker: AudioOverviewWorker = Depends(get_audio_overview_worker),
):
    """Queue one audio overview using only sources attached to this project.

    Args:
        project_id: Project whose sources will be used.
        request_data: Style, length, focus, and optional source selection.
        db: Request-scoped database session.
        current_user: Authenticated account.
        settings: Runtime application settings.
        worker: Durable background processor.

    Returns:
        The queued overview and its persisted options.
    """
    if not settings.audio_overview_tts_enabled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Audio overview TTS is disabled",
        )
    project = require_project(db, project_id, current_user, min_role="viewer")
    document_ids: Optional[list[str]] = None
    if request_data.document_ids is not None:
        document_ids = require_documents(
            db,
            request_data.document_ids,
            current_user,
            project_id=project_id,
        )
    documents = project_documents(db, project, document_ids)
    if document_ids is not None and len(documents) != len(document_ids):
        raise HTTPException(status_code=404, detail="Document not found")
    if not documents:
        raise HTTPException(status_code=422, detail="Project has no selected sources")

    overview_id = str(uuid.uuid4())
    options = request_data.model_dump()
    overview = AudioOverview(
        id=overview_id,
        project_id=project.id,
        user_id=current_user.id,
        status="queued",
        options_json=options,
        script_json=[],
        file_path=audio_overview_file_key(overview_id),
    )
    db.add(overview)
    db.commit()
    db.refresh(overview)
    worker.notify()
    return _response(overview)


@router.get(
    "/projects/{project_id}/audio-overviews",
    response_model=AudioOverviewListResponse,
)
def list_audio_overviews(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
):
    """List saved outputs and report whether local synthesis is enabled.

    Args:
        project_id: Project that owns the overviews.
        db: Request-scoped database session.
        current_user: Authenticated account.
        settings: Runtime application settings.

    Returns:
        The saved overviews and TTS capability flag.
    """
    require_project(db, project_id, current_user, min_role="viewer")
    rows = db.query(AudioOverview).filter(
        AudioOverview.project_id == project_id,
    ).order_by(
        AudioOverview.created_at.desc(),
        AudioOverview.id,
    ).all()
    return {
        "enabled": settings.audio_overview_tts_enabled,
        "voices": list(AudioOverviewVoice),
        "items": [_response(row) for row in rows],
    }


@router.post("/audio-overview-voices/{voice}/preview")
def preview_audio_overview_voice(
    voice: AudioOverviewVoice,
    current_user: User = Depends(get_current_user),
    request_limiter: SlidingWindowRateLimiter = Depends(get_rate_limiter),
    settings: Settings = Depends(get_settings),
):
    """Return a short sample synthesized with one allowlisted Kokoro voice.

    Args:
        voice: Supported American English Kokoro voice.
        current_user: Signed-in account to rate-limit.
        request_limiter: Process-wide request limiter.
        settings: Current audio synthesis setting.

    Returns:
        A short MP3 preview.
    """
    if not settings.audio_overview_tts_enabled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Audio overview TTS is disabled",
        )
    enforce_account_rate_limit(
        request_limiter,
        "audio-overview-voice-preview",
        current_user.id,
        limit=20,
        window_seconds=60,
    )
    try:
        with TemporaryDirectory() as temporary_directory:
            output_path = Path(temporary_directory) / "voice-preview.mp3"
            get_kokoro_tts().synthesize(
                [{"speaker": "A", "text": VOICE_PREVIEW_TEXT}],
                output_path,
                voice_a=voice.value,
            )
            return Response(output_path.read_bytes(), media_type="audio/mpeg")
    except Exception as error:
        logger.warning(
            "Audio overview voice preview failed",
            voice=voice.value,
            error_type=type(error).__name__,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Voice preview is unavailable",
        ) from error


@router.get(
    "/projects/{project_id}/audio-overviews/{overview_id}",
    response_model=AudioOverviewResponse,
)
def get_audio_overview(
    project_id: str,
    overview_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return current status and transcript for one saved overview.

    Args:
        project_id: Project that owns the overview.
        overview_id: Saved overview identifier.
        db: Request-scoped database session.
        current_user: Authenticated account.

    Returns:
        Current status, options, and transcript.
    """
    require_project(db, project_id, current_user, min_role="viewer")
    return _response(_owned_overview(db, project_id, overview_id))


@router.get("/projects/{project_id}/audio-overviews/{overview_id}/file")
def get_audio_overview_file(
    project_id: str,
    overview_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Stream the generated MP3 after checking project ownership and readiness.

    Args:
        project_id: Project that owns the overview.
        overview_id: Saved overview identifier.
        db: Request-scoped database session.
        current_user: Authenticated account.

    Returns:
        The audio file response.
    """
    require_project(db, project_id, current_user, min_role="viewer")
    overview = _owned_overview(db, project_id, overview_id)
    if overview.status != "ready" or not overview.file_path:
        raise HTTPException(status_code=409, detail="Audio overview is not ready")
    try:
        path = resolve_audio_file(overview.file_path)
    except ValueError:
        raise HTTPException(status_code=404, detail="Audio overview file not found")
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Audio overview file not found")
    return FileResponse(path, media_type="audio/mpeg", filename=Path(path).name)


@router.delete(
    "/projects/{project_id}/audio-overviews/{overview_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_audio_overview(
    project_id: str,
    overview_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete one saved overview and its generated audio file.

    Args:
        project_id: Project that owns the overview.
        overview_id: Saved overview identifier.
        db: Request-scoped database session.
        current_user: Authenticated account.

    Returns:
        An empty 204 response.
    """
    require_project(db, project_id, current_user, min_role="editor")
    overview = _owned_overview(db, project_id, overview_id)
    file_path = overview.file_path
    db.delete(overview)
    db.commit()
    remove_audio_file(file_path)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

"""Notes router: create, list, edit and delete a project's notes."""
import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session
import structlog

from app.db.database import get_db
from app.db.models import Message, User
from app.routers.auth import get_current_user
from app.routers.ingest import _begin_ingestion, get_document_service
from app.routers.ownership import require_conversation, require_project
from app.routers.rate_limit import get_concurrency_limiter, get_rate_limiter
from app.schemas import (
    NoteCreate,
    NoteResponse,
    NoteSourceBatchResponse,
    NoteSourceResponse,
    NoteUpdate,
)
from app.services.rate_limit import (
    ConcurrencyLimiter,
    OperationLeaseGroup,
    SlidingWindowRateLimiter,
)
from app.services.note_export import content_disposition, export_notes
from app.services import notes as note_service
from app.services.trash import TrashService

# Every route below requires a signed-in caller. Declaring that on the
# router rather than on each handler means an endpoint added later is
# protected by default, and it travels with the router wherever it is
# mounted.
router = APIRouter(dependencies=[Depends(get_current_user)])
logger = structlog.get_logger()


def _note_source_id(note_id: str) -> str:
    """Give retries for one note the same document key."""
    return str(uuid.uuid5(
        uuid.NAMESPACE_URL,
        "opennotebooklm/note-sources/%s" % note_id,
    ))


def _prepare_note_source(db: Session, note):
    """Validate note Markdown and decide whether its linked source needs work."""
    from app.services.documents import TextSourceBusyError

    content = note_service.note_source_text(note)
    if not content:
        raise HTTPException(status_code=422, detail="This note has no Markdown content")
    document = note_service.get_note_source(db, note)
    if document is not None:
        if (
            document.title == note.title
            and document.content == content
            and document.status != "error"
        ):
            return content, document, False
        if document.status in {"queued", "processing", "transcribing"}:
            raise TextSourceBusyError("The note source is still processing")
    return content, document, True


async def _submit_note_source(
    db: Session,
    project_id: str,
    note,
    content: str,
    document,
    user_id: str,
    document_service,
    operation_lease=None,
):
    """Create or refresh a note's searchable text source."""
    from app.services.documents import UploadTooLargeError

    try:
        return await document_service.process_text(
            db=db,
            project_id=project_id,
            user_id=user_id,
            title=note.title,
            text=content,
            operation_lease=operation_lease,
            document_id=(document.id if document is not None else _note_source_id(note.id)),
            note_id=note.id,
        )
    except UploadTooLargeError as error:
        raise HTTPException(status_code=413, detail=str(error))


@router.get("/projects/{project_id}/notes", response_model=List[NoteResponse])
def list_notes(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List the notes in one of the caller's projects.

    Args:
        project_id: Project to resolve through the caller's ownership.
        db: Database session.
        current_user: Authenticated caller.

    Returns:
        The notes, newest first.
    """
    project = require_project(db, project_id, current_user, min_role="viewer")
    return note_service.list_notes(db, project)


def _note_export_response(notes, format: str, filename: str) -> Response:
    try:
        content, content_type, filename = export_notes(notes, format, filename)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return Response(
        content=content,
        media_type=content_type,
        headers={"Content-Disposition": content_disposition(filename)},
    )


@router.get("/projects/{project_id}/notes/export")
def export_project_notes(
    project_id: str,
    format: str = "markdown",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Export every note in a project visible to the caller.

    Args:
        project_id: Project to resolve through the caller's access.
        format: Download format: Markdown, PDF, or DOCX.
        db: Database session.
        current_user: Authenticated caller.

    Returns:
        An attachment containing all project notes.
    """
    project = require_project(db, project_id, current_user, min_role="viewer")
    return _note_export_response(
        note_service.list_notes(db, project), format, "%s notes" % project.name
    )


@router.get("/projects/{project_id}/notes/{note_id}/export")
def export_project_note(
    project_id: str,
    note_id: str,
    format: str = "markdown",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Export one note after resolving it through its visible project.

    Args:
        project_id: Project containing the note.
        note_id: Note to export.
        format: Download format: Markdown, PDF, or DOCX.
        db: Database session.
        current_user: Authenticated caller.

    Returns:
        An attachment containing the note.
    """
    project = require_project(db, project_id, current_user, min_role="viewer")
    note = note_service.get_note(db, project, note_id)
    return _note_export_response([note], format, note.title)


@router.post("/projects/{project_id}/notes", response_model=NoteResponse)
def create_note(
    project_id: str,
    data: NoteCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Write a note, save an answer, or keep a Studio result.

    Args:
        project_id: Project to resolve through the caller's ownership.
        data: Note content, an answer id, or a validated Studio result.
        db: Database session.
        current_user: Authenticated caller.

    Returns:
        The created note.
    """
    project = require_project(db, project_id, current_user, min_role="editor")
    if data.source_message_id:
        conversation_id = db.query(Message.conversation_id).filter(
            Message.id == data.source_message_id
        ).scalar()
        if conversation_id:
            try:
                require_conversation(db, conversation_id, current_user)
            except HTTPException as error:
                if error.status_code == 404:
                    raise HTTPException(
                        status_code=404, detail="Message not found"
                    ) from error
                raise
    return note_service.create_note(db, project, data)


@router.put("/projects/{project_id}/notes/{note_id}", response_model=NoteResponse)
def update_note(
    project_id: str,
    note_id: str,
    data: NoteUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Edit a note's title, content, or saved mind map layout.

    Args:
        project_id: Project to resolve through the caller's ownership.
        note_id: Note within that project.
        data: Fields to change.
        db: Database session.
        current_user: Authenticated caller.

    Returns:
        The updated note.
    """
    project = require_project(db, project_id, current_user, min_role="editor")
    note = note_service.get_note(db, project, note_id)
    return note_service.update_note(db, note, data)


@router.delete("/projects/{project_id}/notes/{note_id}")
def delete_note(
    project_id: str,
    note_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a note.

    Args:
        project_id: Project to resolve through the caller's ownership.
        note_id: Note within that project.
        db: Database session.
        current_user: Authenticated caller.

    Returns:
        A confirmation.
    """
    project = require_project(db, project_id, current_user, min_role="editor")
    TrashService.trash_note(db, note_service.get_note(db, project, note_id))
    return {"status": "success", "message": "Note moved to trash"}


@router.post(
    "/projects/{project_id}/notes/sources",
    response_model=NoteSourceBatchResponse,
)
async def convert_all_notes_to_sources(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    document_service=Depends(get_document_service),
    request_limiter: SlidingWindowRateLimiter = Depends(get_rate_limiter),
    concurrency_limiter: ConcurrencyLimiter = Depends(get_concurrency_limiter),
):
    """Queue text sources for every unlinked Markdown note in the project.

    Args:
        project_id: Project receiving the note sources.
        db: Database session.
        current_user: Authenticated editor.
        document_service: Existing text ingestion service.
        request_limiter: Per-account ingestion request limiter.
        concurrency_limiter: Per-account active-ingestion limiter.

    Returns:
        Created sources and note ids that could not be queued.
    """
    project = require_project(db, project_id, current_user, min_role="editor")
    notes = note_service.list_notes(db, project)
    candidates = [
        note for note in notes
        if note.content and note.content.strip() and not note.source_document_id
    ]
    if not candidates:
        return NoteSourceBatchResponse(sources=[], failed_note_ids=[])

    sources, failed_note_ids = [], []
    prepared = []
    for note in candidates:
        try:
            content, document, needs_work = _prepare_note_source(db, note)
            if needs_work:
                prepared.append((note, content, document))
            elif document is not None:
                sources.append(NoteSourceResponse(
                    note_id=note.id,
                    doc_id=document.id,
                    status=document.status,
                ))
        except Exception as error:
            logger.error(
                "Could not prepare note source",
                note_id=note.id,
                error_type=type(error).__name__,
                error=str(error),
            )
            failed_note_ids.append(note.id)
    if not prepared:
        return NoteSourceBatchResponse(
            sources=sources,
            failed_note_ids=failed_note_ids,
        )

    lease = OperationLeaseGroup(
        _begin_ingestion(current_user.id, request_limiter, concurrency_limiter),
        len(prepared),
    )
    for note, content, document in prepared:
        try:
            document = await _submit_note_source(
                db,
                project_id,
                note,
                content,
                document,
                current_user.id,
                document_service,
                operation_lease=lease,
            )
            sources.append(NoteSourceResponse(
                note_id=note.id,
                doc_id=document.id,
                status=document.status,
            ))
        except Exception as error:
            logger.error(
                "Could not convert note to a source",
                note_id=note.id,
                error_type=type(error).__name__,
                error=str(error),
            )
            failed_note_ids.append(note.id)
    return NoteSourceBatchResponse(
        sources=sources,
        failed_note_ids=failed_note_ids,
    )


@router.post(
    "/projects/{project_id}/notes/{note_id}/source",
    response_model=NoteSourceResponse,
)
async def convert_note_to_source(
    project_id: str,
    note_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    document_service=Depends(get_document_service),
    request_limiter: SlidingWindowRateLimiter = Depends(get_rate_limiter),
    concurrency_limiter: ConcurrencyLimiter = Depends(get_concurrency_limiter),
):
    """Create or refresh one caller-owned note as a searchable text source.

    Args:
        project_id: Project containing the note.
        note_id: Note to convert.
        db: Database session.
        current_user: Authenticated editor.
        document_service: Existing text ingestion service.
        request_limiter: Per-account ingestion request limiter.
        concurrency_limiter: Per-account active-ingestion limiter.

    Returns:
        The source id and current ingestion status.
    """
    project = require_project(db, project_id, current_user, min_role="editor")
    note = note_service.get_note(db, project, note_id)
    from app.services.documents import TextSourceBusyError

    try:
        content, existing, needs_work = _prepare_note_source(db, note)
    except TextSourceBusyError as error:
        raise HTTPException(status_code=409, detail=str(error))
    if not needs_work:
        return NoteSourceResponse(
            note_id=note.id,
            doc_id=existing.id,
            status=existing.status,
        )

    lease = _begin_ingestion(current_user.id, request_limiter, concurrency_limiter)
    try:
        document = await _submit_note_source(
            db,
            project_id,
            note,
            content,
            existing,
            current_user.id,
            document_service,
            operation_lease=lease,
        )
    except TextSourceBusyError as error:
        raise HTTPException(status_code=409, detail=str(error))
    return NoteSourceResponse(
        note_id=note.id,
        doc_id=document.id,
        status=document.status,
    )

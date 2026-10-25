"""Notes kept beside a project's sources.

A note is written by hand, copied from an assistant answer, or saved from
Studio. Answers and Studio results keep their displayed content so they remain
readable after their source conversation or model call is gone.
"""
import json
import re
import uuid
from typing import List

from fastapi import HTTPException, status
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import Conversation, Message, Note, Project

from app.schemas import (
    MindMapResponse,
    NoteCreate,
    NoteUpdate,
    NOTE_PAYLOAD_MAX_BYTES,
    VideoSummaryPptxRequest,
    VideoSummaryResponse,
)

ORIGIN_MANUAL = "manual"
ORIGIN_ANSWER = "answer"
ORIGIN_STUDIO = "studio"


def _studio_note_content_and_payload(
    project: Project,
    data: NoteCreate,
) -> tuple[str, dict | None]:
    """Validate client-supplied Studio data before it is persisted.

    Args:
        project: Project that owns the note.
        data: Requested Studio note fields.

    Returns:
        Markdown content and a JSON payload, one of which is used per kind.

    Raises:
        HTTPException: If the fields do not describe a valid, bounded result.
    """
    if data.studio_kind is None:
        if data.payload_json is not None:
            raise HTTPException(status_code=422, detail="Studio kind is required")
        return data.content, None

    if data.source_message_id:
        raise HTTPException(status_code=422, detail="Studio notes cannot save an answer")

    if data.studio_kind == "report":
        if not data.content.strip() or data.payload_json is not None:
            raise HTTPException(status_code=422, detail="Invalid report note")
        return data.content, None

    if data.content:
        raise HTTPException(status_code=422, detail="JSON Studio notes cannot include content")
    if data.payload_json is None:
        raise HTTPException(status_code=422, detail="Studio payload is required")

    try:
        payload_size = len(json.dumps(
            data.payload_json, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8"))
    except (TypeError, ValueError, RecursionError):
        raise HTTPException(status_code=422, detail="Invalid Studio payload")
    if payload_size > NOTE_PAYLOAD_MAX_BYTES:
        raise HTTPException(status_code=413, detail="Studio payload is too large")

    try:
        if data.studio_kind == "mindmap":
            parsed = MindMapResponse.model_validate(data.payload_json)
        else:
            parsed = VideoSummaryResponse.model_validate(data.payload_json)
            VideoSummaryPptxRequest.model_validate({"scenes": [
                scene.model_dump() for scene in parsed.scenes
            ]})
    except (ValidationError, ValueError, RecursionError):
        raise HTTPException(status_code=422, detail="Invalid Studio payload")

    if parsed.project_id != project.id:
        raise HTTPException(status_code=422, detail="Studio payload belongs to another project")
    try:
        payload = parsed.model_dump(mode="json")
        stored_size = len(json.dumps(
            payload, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8"))
    except (TypeError, ValueError, RecursionError):
        raise HTTPException(status_code=422, detail="Invalid Studio payload")
    if stored_size > NOTE_PAYLOAD_MAX_BYTES:
        raise HTTPException(status_code=413, detail="Studio payload is too large")
    return "", payload


def list_notes(db: Session, project: Project) -> List[Note]:
    """List a project's notes, newest first.

    Args:
        db: Database session.
        project: Project already resolved for the caller.

    Returns:
        The notes.
    """
    return db.query(Note).filter(Note.project_id == project.id).order_by(
        Note.created_at.desc(), Note.id.desc()
    ).all()


def get_note(db: Session, project: Project, note_id: str) -> Note:
    """Return one of a project's notes.

    Args:
        db: Database session.
        project: Project already resolved for the caller.
        note_id: Note id from the request.

    Returns:
        The note.

    Raises:
        HTTPException: 404 if the note is missing or in another project, so a
            note id cannot be probed through a project the caller does own.
    """
    note = db.query(Note).filter(
        Note.id == note_id, Note.project_id == project.id
    ).first()
    if not note:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Note not found")
    return note


def format_answer(message: Message) -> str:
    """Render an answer and its citations as one Markdown document.

    Args:
        message: Stored assistant message.

    Returns:
        The answer text followed by passages grouped under their source title.
    """
    citations = message.citations_json or []
    if not citations:
        return message.text

    lines = [message.text.rstrip(), "", "**Sources**", ""]
    groups = {}
    for citation in citations:
        title = (
            citation.get("document_title") or citation.get("source")
            or citation.get("title") or "Unknown source"
        )
        key = citation.get("document_id") or title
        group = groups.setdefault(key, {"title": title, "citations": []})
        group["citations"].append(citation)

    for group in groups.values():
        lines.append("- " + group["title"])
        for citation in group["citations"]:
            label = "[%s]" % citation["id"] if citation.get("id") else "Passage"
            page = citation.get("page_num", citation.get("page"))
            if page is not None:
                label += ", page %s" % page
            lines.append("  - " + label)
            excerpt = citation.get("text_preview") or citation.get("text") or ""
            excerpt = re.sub(r"\s+", " ", excerpt).strip()
            if excerpt:
                lines.append("    > " + excerpt)
    return "\n".join(lines)


def create_note(db: Session, project: Project, data: NoteCreate) -> Note:
    """Create a manual note, saved answer, or validated Studio result.

    Args:
        db: Database session.
        project: Project already resolved for the caller.
        data: Title, and either content or the answer to save.

    Returns:
        The created note.

    Raises:
        HTTPException: 404 if `source_message_id` is not an assistant answer
            in this project; ownership of the project is what authorizes
            reading the message.
    """
    content, origin = data.content, ORIGIN_MANUAL
    payload_json = None
    if data.source_message_id:
        if data.studio_kind or data.payload_json is not None:
            raise HTTPException(status_code=422, detail="Studio fields cannot save an answer")
        message = db.query(Message).join(Conversation).filter(
            Message.id == data.source_message_id,
            Message.role == "assistant",
            Conversation.project_id == project.id,
        ).first()
        if not message:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Message not found"
            )
        existing = db.query(Note).filter(
            Note.project_id == project.id,
            Note.source_message_id == data.source_message_id,
        ).first()
        if existing:
            return existing
        content, origin = format_answer(message), ORIGIN_ANSWER
    elif data.studio_kind:
        content, payload_json = _studio_note_content_and_payload(project, data)
        origin = ORIGIN_STUDIO
    elif data.payload_json is not None:
        raise HTTPException(status_code=422, detail="Studio kind is required")

    note_id = str(uuid.uuid4())
    if origin == ORIGIN_ANSWER:
        # A stable primary key makes simultaneous retries collide at the database.
        note_id = str(uuid.uuid5(
            uuid.NAMESPACE_URL,
            "opennotebooklm/notes/%s/%s" % (project.id, data.source_message_id),
        ))

    note = Note(
        id=note_id,
        project_id=project.id,
        title=data.title,
        content=content,
        origin=origin,
        source_message_id=data.source_message_id,
        studio_kind=data.studio_kind,
        payload_json=payload_json,
    )
    db.add(note)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        if origin == ORIGIN_ANSWER:
            existing = db.query(Note).filter(
                Note.project_id == project.id,
                Note.source_message_id == data.source_message_id,
            ).first()
            if existing:
                return existing
        raise
    db.refresh(note)
    return note


def update_note(db: Session, note: Note, data: NoteUpdate) -> Note:
    """Apply an edit to a note.

    Args:
        db: Database session.
        note: Note already resolved for the caller.
        data: Fields to change; omitted ones are kept.

    Returns:
        The updated note.
    """
    for field, value in data.model_dump(exclude_unset=True, exclude_none=True).items():
        setattr(note, field, value)
    db.commit()
    db.refresh(note)
    return note


def delete_note(db: Session, note: Note) -> None:
    """Delete a note.

    Args:
        db: Database session.
        note: Note already resolved for the caller.

    Returns:
        None.
    """
    db.delete(note)
    db.commit()

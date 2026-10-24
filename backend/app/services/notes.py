"""Notes kept beside a project's sources.

A note is either written by hand or saved from an assistant answer. A saved
answer is a copy, not a reference: the conversation it came from can be deleted
and the note still has to read the same, citations included.
"""
import re
import uuid
from typing import List

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.db.models import Conversation, Message, Note, Project
from app.schemas import NoteCreate, NoteUpdate

ORIGIN_MANUAL = "manual"
ORIGIN_ANSWER = "answer"


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
        The answer text followed by a numbered source list, so the `[n]`
        markers in the text still resolve once the note stands alone.
    """
    citations = message.citations_json or []
    if not citations:
        return message.text

    lines = [message.text.rstrip(), "", "**Sources**", ""]
    for citation in citations:
        title = (
            citation.get("document_title") or citation.get("source")
            or citation.get("title") or "Unknown source"
        )
        label = "[%s] %s" % (citation["id"], title) if citation.get("id") else title
        page = citation.get("page_num", citation.get("page"))
        if page is not None:
            label += ", page %s" % page
        lines.append("- " + label)
        excerpt = citation.get("text_preview") or citation.get("text") or ""
        excerpt = re.sub(r"\s+", " ", excerpt).strip()
        if excerpt:
            lines.append("  > " + excerpt)
    return "\n".join(lines)


def create_note(db: Session, project: Project, data: NoteCreate) -> Note:
    """Create a note, either by hand or from an assistant answer.

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
    if data.source_message_id:
        message = db.query(Message).join(Conversation).filter(
            Message.id == data.source_message_id,
            Message.role == "assistant",
            Conversation.project_id == project.id,
        ).first()
        if not message:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Message not found"
            )
        content, origin = format_answer(message), ORIGIN_ANSWER

    note = Note(
        id=str(uuid.uuid4()),
        project_id=project.id,
        title=data.title,
        content=content,
        origin=origin,
        source_message_id=data.source_message_id,
    )
    db.add(note)
    db.commit()
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

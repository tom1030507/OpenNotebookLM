"""Notes router: create, list, edit and delete a project's notes."""
from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import User
from app.routers.auth import get_current_user
from app.routers.ownership import require_project
from app.schemas import NoteCreate, NoteResponse, NoteUpdate
from app.services import notes as note_service

# Every route below requires a signed-in caller. Declaring that on the
# router rather than on each handler means an endpoint added later is
# protected by default, and it travels with the router wherever it is
# mounted.
router = APIRouter(dependencies=[Depends(get_current_user)])


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
    project = require_project(db, project_id, current_user)
    return note_service.list_notes(db, project)


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
    project = require_project(db, project_id, current_user)
    return note_service.create_note(db, project, data)


@router.put("/projects/{project_id}/notes/{note_id}", response_model=NoteResponse)
def update_note(
    project_id: str,
    note_id: str,
    data: NoteUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Edit a note's title or content.

    Args:
        project_id: Project to resolve through the caller's ownership.
        note_id: Note within that project.
        data: Fields to change.
        db: Database session.
        current_user: Authenticated caller.

    Returns:
        The updated note.
    """
    project = require_project(db, project_id, current_user)
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
    project = require_project(db, project_id, current_user)
    note_service.delete_note(db, note_service.get_note(db, project, note_id))
    return {"status": "success", "message": "Note deleted"}

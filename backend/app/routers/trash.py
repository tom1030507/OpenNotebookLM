"""Routes for listing, restoring, and permanently deleting trashed items."""
from typing import Literal

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.database import get_db
from app.db.models import User
from app.routers.auth import get_current_user
from app.services.trash import TrashService

router = APIRouter(dependencies=[Depends(get_current_user)])


@router.get("/trash")
def list_trash(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List the caller's deleted projects, sources, and notes.

    Args:
        db: Database session.
        current_user: Authenticated account.

    Returns:
        Trash items and their retention period.
    """
    settings = get_settings()
    return {
        "items": TrashService.list_items(db, current_user),
        "retention_days": settings.trash_retention_days,
    }


@router.post("/trash/{item_type}/{item_id}/restore")
def restore_trash_item(
    item_type: Literal["project", "source", "note"],
    item_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Restore one item from the caller's trash.

    Args:
        item_type: Project, source, or note.
        item_id: Trashed row id.
        db: Database session.
        current_user: Authenticated account.

    Returns:
        A confirmation.
    """
    TrashService.restore(db, current_user, item_type, item_id)
    return {"status": "success"}


@router.delete("/trash/{item_type}/{item_id}")
def delete_trash_item(
    item_type: Literal["project", "source", "note"],
    item_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Permanently delete one item from the caller's trash.

    Args:
        item_type: Project, source, or note.
        item_id: Trashed row id.
        db: Database session.
        current_user: Authenticated account.

    Returns:
        A confirmation.
    """
    TrashService.delete_forever(db, current_user, item_type, item_id)
    return {"status": "success"}

"""Soft deletion, restoration, and retention cleanup for user content."""
from datetime import timedelta
from typing import Literal

import structlog
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import Document, Note, Project, User
from app.services import notes as note_service
from app.services.projects import ProjectService
from app.utils.time import utc_now

logger = structlog.get_logger()
TrashItemType = Literal["project", "source", "note"]


class TrashService:
    """Keep deleted rows available until a user restores or purges them."""

    @staticmethod
    def list_items(db: Session, user: User) -> list[dict]:
        """List this account's trashed projects, sources, and notes.

        Args:
            db: Database session.
            user: Account whose trash is requested.

        Returns:
            Trashed items, newest deletion first.
        """
        items = [
            {
                "id": project.id,
                "type": "project",
                "title": project.name,
                "deleted_at": project.deleted_at,
            }
            for project in db.query(Project).filter(
                Project.user_id == user.id,
                Project.deleted_at.isnot(None),
            ).all()
        ]
        items.extend(
            {
                "id": document.id,
                "type": "source",
                "title": document.title,
                "deleted_at": document.deleted_at,
            }
            for document in db.query(Document).filter(
                Document.user_id == user.id,
                Document.deleted_at.isnot(None),
            ).all()
        )
        items.extend(
            {
                "id": note.id,
                "type": "note",
                "title": note.title,
                "deleted_at": note.deleted_at,
                "project_id": project.id,
                "project_name": project.name,
            }
            for note, project in db.query(Note, Project).join(
                Project, Project.id == Note.project_id
            ).filter(
                Project.user_id == user.id,
                Project.deleted_at.is_(None),
                Note.deleted_at.isnot(None),
            ).all()
        )
        return sorted(items, key=lambda item: item["deleted_at"], reverse=True)

    @staticmethod
    def trash_project(db: Session, project: Project) -> None:
        """Move a project into trash without changing its sources or notes.

        Args:
            db: Database session.
            project: Project already authorized for the caller.

        Returns:
            None.
        """
        project.deleted_at = utc_now()
        db.commit()

    @staticmethod
    def trash_source(db: Session, document: Document) -> None:
        """Hide a source while preserving its chunks and uploaded file.

        Args:
            db: Database session.
            document: Source already authorized for the caller.

        Returns:
            None.
        """
        document.deleted_at = utc_now()
        db.commit()

    @staticmethod
    def trash_note(db: Session, note: Note) -> None:
        """Move a note into trash without unlinking its source.

        Args:
            db: Database session.
            note: Note already authorized for the caller.

        Returns:
            None.
        """
        note.deleted_at = utc_now()
        db.commit()

    @staticmethod
    def restore(db: Session, user: User, item_type: TrashItemType, item_id: str) -> None:
        """Restore one trashed item owned by the caller.

        Args:
            db: Database session.
            user: Account requesting restoration.
            item_type: Project, source, or note.
            item_id: Trashed row id.

        Returns:
            None.

        Raises:
            HTTPException: If the item is missing, active, or belongs to another account.
        """
        item = TrashService._owned_item(db, user, item_type, item_id)
        if item is None or item.deleted_at is None:
            raise HTTPException(status_code=404, detail="Trash item not found")
        item.deleted_at = None
        db.commit()

    @staticmethod
    def delete_forever(
        db: Session,
        user: User,
        item_type: TrashItemType,
        item_id: str,
    ) -> None:
        """Permanently remove one trashed item through existing hard-delete code.

        Args:
            db: Database session.
            user: Account requesting permanent deletion.
            item_type: Project, source, or note.
            item_id: Trashed row id.

        Returns:
            None.

        Raises:
            HTTPException: If the item is missing, active, or belongs to another account.
        """
        item = TrashService._owned_item(db, user, item_type, item_id)
        if item is None or item.deleted_at is None:
            raise HTTPException(status_code=404, detail="Trash item not found")
        TrashService._hard_delete(db, item_type, item_id)

    @staticmethod
    def _owned_item(
        db: Session,
        user: User,
        item_type: TrashItemType,
        item_id: str,
    ):
        if item_type == "project":
            return db.query(Project).filter(
                Project.id == item_id,
                Project.user_id == user.id,
            ).first()
        if item_type == "source":
            return db.query(Document).filter(
                Document.id == item_id,
                Document.user_id == user.id,
            ).first()
        return db.query(Note).join(Project).filter(
            Note.id == item_id,
            Project.user_id == user.id,
        ).first()

    @staticmethod
    def _hard_delete(db: Session, item_type: TrashItemType, item_id: str) -> bool:
        if item_type == "project":
            return ProjectService.delete_project(db, item_id)
        if item_type == "source":
            from app.services.documents import DocumentService

            return DocumentService.delete_document(db, item_id)
        note = db.get(Note, item_id)
        if note is None:
            return False
        note_service.delete_note(db, note)
        return True


def purge_expired_trash(session_factory: sessionmaker, retention_days: int) -> int:
    """Permanently remove every item older than the configured retention period.

    Args:
        session_factory: Factory for short database transactions.
        retention_days: Number of days an item remains restorable.

    Returns:
        Number of items removed.
    """
    cutoff = utc_now() - timedelta(days=retention_days)
    with session_factory() as db:
        project_ids = [row[0] for row in db.query(Project.id).filter(
            Project.deleted_at <= cutoff
        ).all()]
        document_ids = [row[0] for row in db.query(Document.id).filter(
            Document.deleted_at <= cutoff
        ).all()]
        note_ids = [row[0] for row in db.query(Note.id).filter(
            Note.deleted_at <= cutoff
        ).all()]

    removed = 0
    models = {"source": Document, "note": Note, "project": Project}
    for item_type, item_ids in (
        ("source", document_ids),
        ("note", note_ids),
        ("project", project_ids),
    ):
        for item_id in item_ids:
            try:
                with session_factory() as db:
                    if db.get_bind().dialect.name == "sqlite":
                        # SQLite ignores FOR UPDATE, so serialize restores against this purge.
                        db.execute(text("BEGIN IMMEDIATE"))
                    model = models[item_type]
                    expired_item = db.query(model).filter(
                        model.id == item_id,
                        model.deleted_at <= cutoff,
                    ).with_for_update().first()
                    if expired_item and TrashService._hard_delete(
                        db, item_type, item_id
                    ):
                        removed += 1
            except Exception:
                logger.exception(
                    "Failed to purge expired trash item",
                    item_type=item_type,
                    item_id=item_id,
                )
    return removed

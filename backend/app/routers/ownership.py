"""Resolve a resource id to a row the signed-in account is allowed to touch.

Authentication and authorization are separate problems, and this project only
solved the first one. Every route sits behind `get_current_user`, so a request
without a valid token is refused — but nothing then asked *whose* project was
being opened, and `Project` had no owner to ask about. Any signed-in account
could read, edit and delete every other account's work by id.

These helpers are the one place that question is answered, so a route cannot
forget to ask it: take an id, hand back the row, or raise. Project routes pass
the least role that can perform the action.

| Action | owner | editor | viewer |
|---|---|---|---|
| Read project, sources, notes, ask questions, Studio | ✓ | ✓ | ✓ |
| Add/remove sources, edit notes, chat settings | ✓ | ✓ | |
| Rename/delete project, manage members | ✓ | | |

Conversations are private to their creator. A document is readable only when
owned by the caller or linked to a project they can currently see.

**Not found and not yours are deliberately the same answer.** Returning 403 for a
row that exists but belongs to someone else confirms the id is real, which is a
membership oracle: an attacker enumerating ids learns exactly which ones exist.
404 leaks nothing, and it matches the choice already made for authentication,
where a missing token and an invalid one are also indistinguishable.
"""
from typing import List, Literal, Optional

from fastapi import HTTPException, status
from sqlalchemy import or_
from sqlalchemy.orm import Query, Session

from app.db.models import (
    Conversation,
    Document,
    Project,
    ProjectMember,
    User,
)
from app.services.projects import ProjectService

ProjectRole = Literal["owner", "editor", "viewer"]
_ROLE_LEVEL = {"viewer": 0, "editor": 1, "owner": 2}


def _not_found(kind: str) -> HTTPException:
    """Build the response used for both "missing" and "not yours".

    Args:
        kind: Human-readable resource name for the message.

    Returns:
        The exception to raise.
    """
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="%s not found" % kind.capitalize(),
    )


def visible_projects(db: Session, user: User) -> Query:
    """Start a project query narrowed to what this account can see.

    Args:
        db: Database session.
        user: The signed-in account.

    Returns:
        A query filtered by owner or membership, for the caller to page or count.
    """
    return db.query(Project).outerjoin(
        ProjectMember,
        ProjectMember.project_id == Project.id,
    ).filter(
        Project.deleted_at.is_(None),
        or_(Project.user_id == user.id, ProjectMember.user_id == user.id)
    ).distinct()


def visible_documents(db: Session, user: User) -> Query:
    """Start a document query narrowed to owned or project-shared sources.

    Args:
        db: Database session.
        user: The signed-in account.

    Returns:
        A query filtered by document owner or a currently visible project link.
    """
    accessible_project_ids = visible_projects(db, user).with_entities(Project.id)
    shared_document_ids = ProjectService.project_document_query(db).filter(
        Project.id.in_(accessible_project_ids)
    ).with_entities(Document.id)
    return db.query(Document).filter(
        Document.deleted_at.is_(None),
        or_(
            Document.user_id == user.id,
            Document.id.in_(shared_document_ids),
        )
    )


def project_role(db: Session, project: Project, user: User) -> ProjectRole:
    """Resolve the caller's role in one project, hiding non-members as missing.

    Args:
        db: Database session.
        project: Project being accessed.
        user: The signed-in account.

    Returns:
        The caller's effective project role.

    Raises:
        HTTPException: 404 if the caller cannot see the project.
    """
    if project.user_id == user.id:
        return "owner"

    member = db.query(ProjectMember.role).filter(
        ProjectMember.project_id == project.id,
        ProjectMember.user_id == user.id,
    ).first()
    if member is None or member.role not in ("viewer", "editor"):
        raise _not_found("project")
    return member.role


def require_project(
    db: Session,
    project_id: str,
    user: User,
    min_role: ProjectRole = "owner",
) -> Project:
    """Return a visible project if the caller has the requested minimum role.

    Args:
        db: Database session.
        project_id: Project id from the request.
        user: The signed-in account.
        min_role: Lowest role allowed to perform the route's action.

    Returns:
        The project.

    Raises:
        HTTPException: 404 if it does not exist or the caller lacks the role.
    """
    project = visible_projects(db, user).filter(Project.id == project_id).first()
    if project is None:
        raise _not_found("project")
    if _ROLE_LEVEL[project_role(db, project, user)] < _ROLE_LEVEL[min_role]:
        raise _not_found("project")
    return project


def require_document(
    db: Session,
    document_id: str,
    user: User,
    project_id: Optional[str] = None,
    owner_only: bool = False,
) -> Document:
    """Return an owned document or one linked through a visible project.

    Args:
        db: Database session.
        document_id: Document id from the request.
        user: The signed-in account.
        project_id: If supplied, require access through this project or ownership.
        owner_only: If true, require the caller to own the underlying document.

    Returns:
        The document.

    Raises:
        HTTPException: 404 if the document is missing or inaccessible.
    """
    document = db.query(Document).filter(
        Document.id == document_id,
        Document.deleted_at.is_(None),
    ).first()
    if document is None:
        raise _not_found("document")

    if owner_only:
        if document.user_id != user.id:
            raise _not_found("document")
        return document

    if project_id is not None:
        require_project(db, project_id, user, min_role="viewer")
        if document.user_id == user.id:
            return document
        linked = ProjectService.project_document_query(db, project_id).filter(
            Document.id == document_id,
        ).first()
        if linked is None:
            raise _not_found("document")
        return document

    if document.user_id != user.id and not visible_documents(db, user).filter(
        Document.id == document_id
    ).first():
        raise _not_found("document")
    return document


def require_conversation(db: Session, conversation_id: str, user: User) -> Conversation:
    """Return the conversation if this account owns the project holding it.

    Conversations have no owner column of their own: `project_id` is NOT NULL, so
    ownership always reaches them through the project.

    Args:
        db: Database session.
        conversation_id: Conversation id from the request.
        user: The signed-in account.

    Returns:
        The conversation.

    Raises:
        HTTPException: 404 if it does not exist, or its project is not this
            account's.
    """
    conversation = db.query(Conversation).filter(
        Conversation.id == conversation_id
    ).first()
    if not conversation:
        raise _not_found("conversation")

    project = db.query(Project).filter(
        Project.id == conversation.project_id,
        Project.deleted_at.is_(None),
    ).first()
    if project is None:
        raise _not_found("conversation")

    if conversation.user_id == user.id:
        return conversation
    if (
        conversation.user_id is not None
        or project.user_id != user.id
    ):
        raise _not_found("conversation")
    return conversation


def owned_document_ids(
    db: Session,
    user: User,
    project_id: Optional[str] = None,
) -> list:
    """List caller-owned documents or sources linked to one visible project.

    Used to scope retrieval, so a query can never reach another account's chunks
    even when the caller supplies no project.

    Args:
        db: Database session.
        user: The signed-in account.
        project_id: Optional project whose linked sources are being used.

    Returns:
        Document ids.
    """
    query = db.query(Document.id).filter(Document.deleted_at.is_(None))
    if project_id is None:
        query = query.filter(Document.user_id == user.id)
    else:
        require_project(db, project_id, user, min_role="viewer")
        query = ProjectService.project_document_query(db, project_id).with_entities(
            Document.id
        )
    return [row[0] for row in query.all()]


def require_documents(
    db: Session,
    document_ids: List[str],
    user: User,
    project_id: Optional[str] = None,
) -> List[str]:
    """Return requested ids if all are owned or linked to the given project.

    One unowned id fails the whole selection, with the same 404 as an unknown
    one, rather than being dropped: dropping it silently would answer from fewer
    sources than the caller chose.

    Args:
        db: Database session.
        document_ids: Document ids from the request.
        user: The signed-in account.
        project_id: Optional project that must contain every selected source.

    Returns:
        The ids, de-duplicated, in request order.

    Raises:
        HTTPException: 404 if any id does not exist or belongs to someone else.
    """
    wanted = list(dict.fromkeys(document_ids))
    query = db.query(Document.id).filter(
        Document.id.in_(wanted),
        Document.deleted_at.is_(None),
    )
    if project_id is None:
        query = query.filter(Document.user_id == user.id)
    else:
        require_project(db, project_id, user, min_role="viewer")
        query = ProjectService.project_document_query(db, project_id).filter(
            Document.id.in_(wanted)
        ).with_entities(Document.id)
    accessible = {row[0] for row in query.all()}
    if len(accessible) != len(wanted):
        raise _not_found("document")
    return wanted

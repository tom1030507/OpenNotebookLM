"""Resolve a resource id to a row the signed-in account is allowed to touch.

Authentication and authorization are separate problems, and this project only
solved the first one. Every route sits behind `get_current_user`, so a request
without a valid token is refused — but nothing then asked *whose* project was
being opened, and `Project` had no owner to ask about. Any signed-in account
could read, edit and delete every other account's work by id.

These helpers are the one place that question is answered, so a route cannot
forget to ask it: take an id, hand back the row, or raise.

**Not found and not yours are deliberately the same answer.** Returning 403 for a
row that exists but belongs to someone else confirms the id is real, which is a
membership oracle: an attacker enumerating ids learns exactly which ones exist.
404 leaks nothing, and it matches the choice already made for authentication,
where a missing token and an invalid one are also indistinguishable.
"""
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy.orm import Query, Session

from app.db.models import Conversation, Document, Project, User


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
    """Start a project query narrowed to what this account owns.

    Args:
        db: Database session.
        user: The signed-in account.

    Returns:
        A query filtered by owner, for the caller to page or count.
    """
    return db.query(Project).filter(Project.user_id == user.id)


def visible_documents(db: Session, user: User) -> Query:
    """Start a document query narrowed to what this account owns.

    Args:
        db: Database session.
        user: The signed-in account.

    Returns:
        A query filtered by owner.
    """
    return db.query(Document).filter(Document.user_id == user.id)


def require_project(db: Session, project_id: str, user: User) -> Project:
    """Return the project if this account owns it.

    Args:
        db: Database session.
        project_id: Project id from the request.
        user: The signed-in account.

    Returns:
        The project.

    Raises:
        HTTPException: 404 if it does not exist or belongs to someone else.
    """
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project or project.user_id != user.id:
        raise _not_found("project")
    return project


def require_document(db: Session, document_id: str, user: User) -> Document:
    """Return the document if this account owns it.

    Args:
        db: Database session.
        document_id: Document id from the request.
        user: The signed-in account.

    Returns:
        The document.

    Raises:
        HTTPException: 404 if it does not exist or belongs to someone else.
    """
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document or document.user_id != user.id:
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

    project = db.query(Project).filter(Project.id == conversation.project_id).first()
    if not project or project.user_id != user.id:
        raise _not_found("conversation")
    return conversation


def owned_document_ids(db: Session, user: User) -> list:
    """List the document ids this account owns.

    Used to scope retrieval, so a query can never reach another account's chunks
    even when the caller supplies no project.

    Args:
        db: Database session.
        user: The signed-in account.

    Returns:
        Document ids.
    """
    return [row[0] for row in db.query(Document.id).filter(Document.user_id == user.id).all()]

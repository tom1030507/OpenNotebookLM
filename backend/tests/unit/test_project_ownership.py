"""Project roles and resource checks stay in one authorization layer."""
from __future__ import annotations

import inspect

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import models
from app.routers import ownership


@pytest.fixture
def db():
    """Create an isolated database for role-resolution tests.

    Yields:
        A SQLAlchemy session with the current schema.
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    models.Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _user(db, username):
    user = models.User(
        id=username,
        username=username,
        email=f"{username}@example.com",
        hashed_password="unused",
    )
    db.add(user)
    db.flush()
    return user


def _project(db, owner, project_id="project-1"):
    project = models.Project(id=project_id, user_id=owner.id, name=project_id)
    db.add(project)
    db.flush()
    return project


def _membership(db, project, user, role):
    assert hasattr(models, "ProjectMember")
    member = models.ProjectMember(project_id=project.id, user_id=user.id, role=role)
    db.add(member)
    db.flush()
    return member


def test_project_role_and_minimum_role_are_resolved_per_project(db):
    assert callable(getattr(ownership, "project_role", None))
    assert "min_role" in inspect.signature(ownership.require_project).parameters

    owner = _user(db, "owner")
    editor = _user(db, "editor")
    viewer = _user(db, "viewer")
    mixed = _user(db, "mixed")
    outsider = _user(db, "outsider")
    project = _project(db, owner)
    second_project = _project(db, owner, "project-2")
    _membership(db, project, editor, "editor")
    _membership(db, project, viewer, "viewer")
    _membership(db, project, mixed, "editor")
    _membership(db, second_project, mixed, "viewer")

    assert ownership.project_role(db, project, owner) == "owner"
    assert ownership.project_role(db, project, editor) == "editor"
    assert ownership.project_role(db, project, viewer) == "viewer"
    assert ownership.project_role(db, project, mixed) == "editor"
    assert ownership.project_role(db, second_project, mixed) == "viewer"
    assert ownership.require_project(db, project.id, owner) is project
    assert ownership.require_project(db, project.id, viewer, min_role="viewer") is project
    assert ownership.require_project(db, project.id, editor, min_role="editor") is project
    assert ownership.require_project(db, second_project.id, mixed, min_role="viewer") is second_project
    with pytest.raises(HTTPException) as wrong_project_role:
        ownership.require_project(db, second_project.id, mixed, min_role="editor")
    assert wrong_project_role.value.status_code == 404
    with pytest.raises(HTTPException) as denied:
        ownership.require_project(db, project.id, viewer, min_role="editor")
    assert denied.value.status_code == 404
    with pytest.raises(HTTPException) as hidden:
        ownership.require_project(db, project.id, outsider, min_role="viewer")
    assert hidden.value.status_code == 404


def test_project_membership_is_unique_per_user_and_project(db):
    assert "project_members" in models.Base.metadata.tables
    owner = _user(db, "owner")
    editor = _user(db, "editor")
    project = _project(db, owner)
    _membership(db, project, editor, "editor")

    db.add(models.ProjectMember(project_id=project.id, user_id=editor.id, role="viewer"))
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_shared_documents_are_limited_to_the_project_and_revoked_immediately(db):
    assert "project_id" in inspect.signature(ownership.require_document).parameters
    assert "owner_only" in inspect.signature(ownership.require_document).parameters
    assert "project_id" in inspect.signature(ownership.require_documents).parameters
    assert "project_id" in inspect.signature(ownership.owned_document_ids).parameters

    owner = _user(db, "owner")
    editor = _user(db, "editor")
    other_owner = _user(db, "other-owner")
    project = _project(db, owner)
    other_project = _project(db, owner, "project-2")
    _membership(db, project, editor, "editor")
    _membership(db, project, other_owner, "editor")
    _membership(db, other_project, editor, "viewer")
    document = models.Document(
        id="document-1", user_id=other_owner.id, title="Shared",
        source_type="text", status="ready",
    )
    other_document = models.Document(
        id="document-2", user_id=owner.id, title="Other project",
        source_type="text", status="ready",
    )
    editor_document = models.Document(
        id="document-3", user_id=editor.id, title="Owned by editor",
        source_type="text", status="ready",
    )
    db.add_all([document, other_document, editor_document])
    db.flush()
    db.add_all([
        models.ProjectDocument(project_id=project.id, document_id=document.id),
        models.ProjectDocument(project_id=other_project.id, document_id=other_document.id),
    ])
    db.flush()

    assert ownership.require_document(db, document.id, editor).id == document.id
    assert ownership.require_document(db, document.id, editor, project_id=project.id).id == document.id
    with pytest.raises(HTTPException) as foreign_document:
        ownership.require_document(db, other_document.id, editor, project_id=project.id)
    assert foreign_document.value.status_code == 404
    with pytest.raises(HTTPException) as owner_only:
        ownership.require_document(db, document.id, editor, owner_only=True)
    assert owner_only.value.status_code == 404
    with pytest.raises(HTTPException) as foreign_to_project:
        ownership.require_documents(db, [other_document.id], editor, project_id=project.id)
    assert foreign_to_project.value.status_code == 404
    assert ownership.require_documents(db, [document.id], editor, project_id=project.id) == [document.id]
    assert ownership.owned_document_ids(db, editor) == [editor_document.id]
    assert ownership.owned_document_ids(db, editor, project_id=project.id) == [document.id]

    membership = db.query(models.ProjectMember).filter_by(
        project_id=project.id, user_id=editor.id
    ).one()
    db.delete(membership)
    db.flush()
    with pytest.raises(HTTPException) as revoked:
        ownership.require_document(db, document.id, editor)
    assert revoked.value.status_code == 404


def test_only_conversation_creator_can_access_it_and_legacy_owner_is_preserved(db):
    assert "user_id" in models.Conversation.__table__.columns
    owner = _user(db, "owner")
    member = _user(db, "member")
    project = _project(db, owner)
    _membership(db, project, member, "editor")
    member_conversation = models.Conversation(
        id="member-conversation", project_id=project.id, user_id=member.id,
        title="Private",
    )
    legacy_conversation = models.Conversation(
        id="legacy-conversation", project_id=project.id, title="Old project chat",
    )
    db.add_all([member_conversation, legacy_conversation])
    db.flush()

    assert ownership.require_conversation(db, member_conversation.id, member) is member_conversation
    with pytest.raises(HTTPException) as private:
        ownership.require_conversation(db, member_conversation.id, owner)
    assert private.value.status_code == 404
    assert ownership.require_conversation(db, legacy_conversation.id, owner) is legacy_conversation
    with pytest.raises(HTTPException) as legacy_private:
        ownership.require_conversation(db, legacy_conversation.id, member)
    assert legacy_private.value.status_code == 404

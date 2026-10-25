"""Project sharing membership API tests."""
from __future__ import annotations

import sys
import uuid
from types import ModuleType

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import get_db
from app.db.models import Base, Conversation, Project, ProjectMember, User

# The query routes are included by the production app but retrieval is not under
# test here. Keep their model service importable without loading the embedding stack.
rag_module = ModuleType("app.services.rag")
rag_module.RAGService = type("RAGService", (), {})
sys.modules["app.services.rag"] = rag_module

from app.main import app  # noqa: E402
from conftest import authenticated_client  # noqa: E402


@pytest.fixture
def sharing_env():
    """Create four existing accounts and one isolated project database."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(autocommit=False, autoflush=False, bind=engine)()

    def override_get_db():
        yield session

    app.dependency_overrides[get_db] = override_get_db
    clients = {
        name: authenticated_client(app, session, "share-%s" % name)
        for name in ("owner", "alice", "bob", "outsider")
    }
    users = {
        user.username: user
        for user in session.query(User).all()
    }

    class Env:
        pass

    env = Env()
    env.session = session
    env.engine = engine
    env.clients = clients
    env.users = users
    env.owner = clients["owner"]
    env.alice = clients["alice"]
    env.bob = clients["bob"]
    env.outsider = clients["outsider"]
    env.owner_user = users["share-owner"]
    env.alice_user = users["share-alice"]
    env.bob_user = users["share-bob"]
    yield env

    app.dependency_overrides.clear()
    session.close()
    engine.dispose()


def make_project(client, name="Shared notebook", description=None):
    response = client.post(
        "/api/projects",
        json={"name": name, "description": description},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_project_responses_include_effective_owner_and_member_roles(sharing_env):
    owner_project = make_project(sharing_env.owner, "Owner notebook")
    shared_project = make_project(sharing_env.owner, "Shared notebook")
    sharing_env.session.add(ProjectMember(
        project_id=shared_project["id"],
        user_id=sharing_env.alice_user.id,
        role="editor",
    ))
    sharing_env.session.commit()

    owner_list = sharing_env.owner.get("/api/projects").json()
    shared_list = sharing_env.alice.get("/api/projects").json()

    assert {p["id"]: p["role"] for p in owner_list["projects"]} == {
        owner_project["id"]: "owner",
        shared_project["id"]: "owner",
    }
    assert shared_list["projects"][0]["id"] == shared_project["id"]
    assert shared_list["projects"][0]["role"] == "editor"
    assert shared_list["projects"][0]["conversation_count"] == 0


def test_member_management_adds_by_username_and_email_and_lists_owner(sharing_env):
    project = make_project(sharing_env.owner)
    base = "/api/projects/%s/members" % project["id"]

    alice = sharing_env.owner.post(
        base,
        json={"username": "share-alice", "role": "viewer"},
    )
    bob = sharing_env.owner.post(
        base,
        json={"email": "share-bob@example.com", "role": "editor"},
    )
    listed = sharing_env.owner.get(base)

    assert alice.status_code == 201, alice.text
    assert bob.status_code == 201, bob.text
    assert listed.status_code == 200, listed.text
    members = {row["user_id"]: row for row in listed.json()}
    assert members[sharing_env.owner_user.id]["role"] == "owner"
    assert members[sharing_env.owner_user.id]["username"] == "share-owner"
    assert members[sharing_env.alice_user.id]["role"] == "viewer"
    assert members[sharing_env.bob_user.id]["role"] == "editor"


def test_member_management_rejects_invalid_missing_duplicate_and_owner(sharing_env):
    project = make_project(sharing_env.owner)
    base = "/api/projects/%s/members" % project["id"]

    assert sharing_env.owner.post(
        base,
        json={"username": "share-alice", "role": "admin"},
    ).status_code == 422
    assert sharing_env.owner.post(
        base,
        json={"username": "share-alice", "email": "share-alice@example.com", "role": "viewer"},
    ).status_code == 422
    assert sharing_env.owner.post(
        base,
        json={"role": "viewer"},
    ).status_code == 422
    assert sharing_env.owner.post(
        base,
        json={"username": "missing-user", "role": "viewer"},
    ).status_code == 404
    assert sharing_env.owner.post(
        base,
        json={"username": "share-owner", "role": "viewer"},
    ).status_code == 409

    add = sharing_env.owner.post(
        base,
        json={"username": "share-alice", "role": "viewer"},
    )
    duplicate = sharing_env.owner.post(
        base,
        json={"username": "share-alice", "role": "editor"},
    )

    assert add.status_code == 201
    assert duplicate.status_code == 409


def test_owner_can_change_and_remove_a_member(sharing_env):
    project = make_project(sharing_env.owner)
    base = "/api/projects/%s/members" % project["id"]
    added = sharing_env.owner.post(
        base,
        json={"username": "share-alice", "role": "viewer"},
    )
    user_id = added.json()["user_id"]

    changed = sharing_env.owner.patch(
        "%s/%s" % (base, user_id),
        json={"role": "editor"},
    )
    removed = sharing_env.owner.delete("%s/%s" % (base, user_id))

    assert changed.status_code == 200, changed.text
    assert changed.json()["role"] == "editor"
    assert removed.status_code == 200
    assert all(row["user_id"] != user_id for row in sharing_env.owner.get(base).json())


def test_non_owner_cannot_reach_any_member_route(sharing_env):
    project = make_project(sharing_env.owner)
    base = "/api/projects/%s/members" % project["id"]
    paths = [
        ("get", base, None),
        ("post", base, {"username": "not-looked-up", "role": "viewer"}),
        ("patch", "%s/%s" % (base, sharing_env.bob_user.id), {"role": "editor"}),
        ("delete", "%s/%s" % (base, sharing_env.bob_user.id), None),
    ]

    for method, path, body in paths:
        request = getattr(sharing_env.alice, method)
        response = request(path) if body is None else request(path, json=body)
        assert response.status_code == 404, (method, response.text)


def test_shared_projects_are_unique_searchable_paginated_and_count_private_conversations(sharing_env):
    first = make_project(sharing_env.owner, "Research alpha", "shared research")
    second = make_project(sharing_env.owner, "Research beta", "shared research")
    for project in (first, second):
        sharing_env.session.add(ProjectMember(
            project_id=project["id"], user_id=sharing_env.alice_user.id, role="viewer"
        ))
    sharing_env.session.add_all([
        Conversation(
            id=str(uuid.uuid4()), project_id=first["id"],
            user_id=sharing_env.alice_user.id, title="Alice chat",
        ),
        Conversation(
            id=str(uuid.uuid4()), project_id=first["id"],
            user_id=sharing_env.owner_user.id, title="Owner chat",
        ),
    ])
    sharing_env.session.commit()

    page_one = sharing_env.alice.get("/api/projects?search=Research&page=1&per_page=1").json()
    page_two = sharing_env.alice.get("/api/projects?search=Research&page=2&per_page=1").json()
    all_projects = sharing_env.alice.get("/api/projects?search=Research&per_page=10").json()

    assert page_one["total"] == page_two["total"] == all_projects["total"] == 2
    assert page_one["projects"][0]["id"] != page_two["projects"][0]["id"]
    assert {row["id"] for row in all_projects["projects"]} == {first["id"], second["id"]}
    first_result = next(row for row in all_projects["projects"] if row["id"] == first["id"])
    assert first_result["conversation_count"] == 1


def test_deleting_a_project_cascades_memberships(sharing_env):
    project = make_project(sharing_env.owner)
    added = sharing_env.owner.post(
        "/api/projects/%s/members" % project["id"],
        json={"username": "share-alice", "role": "editor"},
    )
    assert added.status_code == 201, added.text

    deleted = sharing_env.owner.delete("/api/projects/%s" % project["id"])

    assert deleted.status_code == 200
    assert sharing_env.session.query(ProjectMember).filter_by(
        project_id=project["id"]
    ).count() == 0

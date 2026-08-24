"""Contract and ownership tests for the intentionally narrow cache API."""
from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.api.cache as cache_api
from app.db.database import get_db
from app.db.models import Base, Document, Project, ProjectDocument, User
from app.routers.auth import get_current_user


PROJECT_ID = "alice-project"
DOCUMENT_ID = "alice-document"


def cache_route_contract() -> set[tuple[str, str]]:
    """Return methods and paths mounted by the cache router.

    Args:
        None.

    Returns:
        Cache router method/path pairs.
    """
    return {
        (method, route.path)
        for route in cache_api.router.routes
        for method in (route.methods or set())
        if method in {"DELETE", "GET", "PATCH", "POST", "PUT"}
    }


def test_cache_router_exposes_only_owned_resource_invalidation() -> None:
    """Stats, health, warmup, global clear, and arbitrary patterns are not public."""
    assert cache_route_contract() == {
        ("DELETE", "/api/cache/invalidate/project/{project_id}"),
        ("DELETE", "/api/cache/invalidate/document/{document_id}"),
    }


@pytest.fixture
def cache_api_env():
    """Serve the cache router against two users and Alice's resources."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=engine,
    )
    Base.metadata.create_all(bind=engine)
    session = session_factory()
    alice = User(
        id="alice",
        username="alice",
        email="alice@example.com",
        hashed_password="x",
        is_active=True,
    )
    bob = User(
        id="bob",
        username="bob",
        email="bob@example.com",
        hashed_password="x",
        is_active=True,
    )
    session.add_all([alice, bob])
    session.add(Project(id=PROJECT_ID, user_id=alice.id, name="Alice", meta_json={}))
    session.add(Document(
        id=DOCUMENT_ID,
        user_id=alice.id,
        title="Alice source",
        source_type="url",
        status="ready",
        meta_json={},
    ))
    session.add(ProjectDocument(project_id=PROJECT_ID, document_id=DOCUMENT_ID))
    session.commit()

    active_user = {"value": bob}

    def override_db():
        yield session

    app = FastAPI()
    app.include_router(cache_api.router)
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: active_user["value"]

    yield SimpleNamespace(
        client=TestClient(app),
        active_user=active_user,
        alice=alice,
        bob=bob,
    )

    session.close()
    engine.dispose()


@pytest.mark.parametrize("path", [
    "/api/cache/clear",
    "/api/cache/clear?pattern=*",
    "/api/cache/stats",
    "/api/cache/health",
    f"/api/cache/warmup/{PROJECT_ID}",
])
def test_authenticated_users_cannot_reach_broad_cache_controls(
    cache_api_env,
    path: str,
) -> None:
    """Signing in cannot grant process-wide cache administration."""
    method = "POST" if "/warmup/" in path else (
        "GET" if path.endswith(("/stats", "/health")) else "DELETE"
    )

    response = cache_api_env.client.request(method, path)

    assert response.status_code == 404


@pytest.mark.parametrize("resource,path", [
    ("project", "/api/cache/invalidate/project/{}"),
    ("document", "/api/cache/invalidate/document/{}"),
])
def test_foreign_and_missing_resources_are_identical_and_skip_cache(
    cache_api_env,
    monkeypatch,
    resource: str,
    path: str,
) -> None:
    """Ownership checks answer 404 before invalidation can reveal cache activity."""
    invalidator = f"invalidate_{resource}_cache"
    called = False

    def reject_invalidation(_resource_id: str) -> int:
        nonlocal called
        called = True
        raise AssertionError("cache invalidation ran before ownership resolution")

    monkeypatch.setattr(cache_api.cache_service, invalidator, reject_invalidation)
    existing_id = PROJECT_ID if resource == "project" else DOCUMENT_ID

    foreign = cache_api_env.client.delete(path.format(existing_id))
    missing = cache_api_env.client.delete(path.format("missing-id"))

    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json()
    assert called is False


@pytest.mark.parametrize("resource,path", [
    ("project", "/api/cache/invalidate/project/{}"),
    ("document", "/api/cache/invalidate/document/{}"),
])
def test_owned_resources_can_be_invalidated(
    cache_api_env,
    monkeypatch,
    resource: str,
    path: str,
) -> None:
    """Removing broad controls must preserve useful owned invalidation."""
    cache_api_env.active_user["value"] = cache_api_env.alice
    invalidator = f"invalidate_{resource}_cache"
    monkeypatch.setattr(cache_api.cache_service, invalidator, lambda _id: 1)
    resource_id = PROJECT_ID if resource == "project" else DOCUMENT_ID

    response = cache_api_env.client.delete(path.format(resource_id))

    assert response.status_code == 200
    assert response.json() == {
        "invalidated": 1,
        "target_type": resource,
        "target_id": resource_id,
    }

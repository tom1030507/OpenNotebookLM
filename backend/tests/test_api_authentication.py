"""Every API route that touches user data or spends budget demands a token.

Sign-in used to be a client-side redirect and nothing more. The routers were
mounted without a security dependency, so `curl http://host:8000/api/projects`
could list, create and delete projects, read any uploaded file, and spend the
configured LLM budget through `/api/query`, with no credentials at all.

These tests pin the fix from the outside, over HTTP, and they walk the
*production* route table rather than a hand-written list: a router mounted later
is covered without anybody remembering to extend this file. Anything genuinely
meant to stay reachable without a token has to be named in `PUBLIC_PATHS`, which
makes each of those a deliberate, reviewable decision.
"""
from __future__ import annotations

import re
import sys
from types import ModuleType

import pytest
from fastapi.testclient import TestClient
import jwt
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import get_db
from app.db.models import Base


# Route-level authentication is what these tests exercise; retrieval and model
# inference are not. Replace that heavyweight boundary before importing the app
# so the tests run in the minimal API environment.
rag_module = ModuleType("app.services.rag")


class StubRAGService:
    """Stand-in for the unused RAG dependency during route contract tests."""


rag_module.RAGService = StubRAGService
sys.modules["app.services.rag"] = rag_module

from app.main import app as production_app  # noqa: E402
from conftest import TEST_AUTH_SERVICE, authenticated_client  # noqa: E402


# Reachable without a token, each for a stated reason:
PUBLIC_PATHS = frozenset({
    # docker-compose's healthcheck polls /healthz, and a probe cannot hold a
    # token. Protecting these would keep the container permanently unhealthy.
    "/healthz",
    "/ready",
    "/readyz",
    # The name-and-version banner. Carries no user data.
    "/",
    # You cannot present a token before you have an account, or before you
    # exchange credentials for one.
    "/api/auth/register",
    "/api/auth/token",
    # The sign-in page has to be able to say which demo credentials work
    # before anybody holds one. It returns nothing at all unless this
    # deployment deliberately published a demo account.
    "/api/auth/demo-account",
    # FastAPI's own docs. They describe the API's shape and return none of its
    # data; the endpoints they describe are all protected.
    "/openapi.json",
    "/docs",
    "/docs/oauth2-redirect",
    "/redoc",
})

PATH_PARAMETER = re.compile(r"\{[^}]+\}")

# A token that is well-formed but signed with a key nobody trusts.
FOREIGN_TOKEN = "Bearer " + jwt.encode(
    {"sub": "test-user"},
    "not-the-signing-key",
    algorithm="HS256",
)


def concrete(path: str) -> str:
    """Fill a route template's path parameters with an id nothing matches.

    Args:
        path: OpenAPI route template to make concrete.

    Returns:
        The route path with every template parameter replaced.
    """
    return PATH_PARAMETER.sub("no-such-id", path)


def protected_routes() -> list[tuple[str, str]]:
    """List every method and path the production app serves but does not open.

    Args:
        None.

    Returns:
        Sorted ``(method, path)`` pairs, excluding the public allow-list and the
        methods Starlette answers without reaching a handler
    """
    routes = set()
    for path, operations in production_app.openapi()["paths"].items():
        if path in PUBLIC_PATHS:
            continue

        for method in operations:
            method = method.upper()
            if method not in {"DELETE", "GET", "PATCH", "POST", "PUT"}:
                continue
            routes.add((method, path))

    return sorted(routes)


@pytest.fixture(scope="module")
def api():
    """The production app, backed by an empty database, with an account to use.

    Yields:
        ``(anonymous_client, signed_in_client)`` against the same app
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = testing_session()
        try:
            yield db
        finally:
            db.close()

    production_app.dependency_overrides[get_db] = override_get_db

    with testing_session() as db:
        signed_in = authenticated_client(production_app, db)

    # Not entered as a context manager: the app's lifespan initialises the real
    # database, which these tests neither need nor should touch.
    yield TestClient(production_app), signed_in

    production_app.dependency_overrides.clear()


@pytest.fixture()
def anonymous(api):
    """A client that presents no credentials at all."""
    return api[0]


@pytest.fixture()
def signed_in(api):
    """A client that presents a valid bearer token."""
    return api[1]


def test_the_app_actually_serves_the_routes_under_test():
    """Guard against the sweep below passing because it swept nothing."""
    paths = {path for _, path in protected_routes()}

    assert "/api/projects" in paths
    assert "/api/docs/{doc_id}/file" in paths
    assert "/api/query" in paths
    assert "/api/export/conversation/{conversation_id}" in paths
    assert "/api/cache/invalidate/project/{project_id}" in paths
    assert len(paths) > 20


@pytest.mark.parametrize("method,path", protected_routes())
def test_route_rejects_a_caller_with_no_token(anonymous, method, path):
    """No route outside the allow-list answers an anonymous caller."""
    response = anonymous.request(method, concrete(path))

    assert response.status_code == 401, (
        f"{method} {path} answered an anonymous caller with "
        f"{response.status_code}"
    )


@pytest.mark.parametrize("method,path", protected_routes())
def test_route_rejects_a_token_it_cannot_validate(anonymous, method, path):
    """A token signed by somebody else is refused exactly like no token.

    `oauth2_scheme` is built with ``auto_error=False`` so both cases fall
    through to the same check and cannot be told apart by their response.
    """
    response = anonymous.request(
        method,
        concrete(path),
        headers={"Authorization": FOREIGN_TOKEN},
    )

    assert response.status_code == 401, (
        f"{method} {path} accepted a token signed with the wrong key"
    )


def test_the_refusals_are_indistinguishable(anonymous):
    """A missing header and a bad token reveal nothing about which it was."""
    missing = anonymous.get("/api/projects")
    invalid = anonymous.get(
        "/api/projects",
        headers={"Authorization": FOREIGN_TOKEN},
    )

    assert missing.status_code == invalid.status_code == 401
    assert missing.json() == invalid.json()
    assert missing.headers["WWW-Authenticate"] == invalid.headers["WWW-Authenticate"]


def test_a_token_for_a_deleted_account_is_refused(anonymous):
    """Signing correctly is not enough; the account has to still exist."""
    token = TEST_AUTH_SERVICE.create_access_token("never-registered")

    response = anonymous.get(
        "/api/projects",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 401


@pytest.mark.parametrize("path", ["/healthz", "/ready", "/readyz"])
def test_health_checks_stay_reachable_without_a_token(anonymous, path):
    """The container's healthcheck cannot hold a token."""
    response = anonymous.get(path)

    assert response.status_code == 200


@pytest.mark.parametrize("method,path", protected_routes())
def test_a_valid_token_gets_past_the_gate(signed_in, method, path):
    """Every protected route accepts the token and goes on to do its job.

    What it answers depends on the route and on ids that match nothing; the
    point here is only that authentication is no longer what stops it.
    """
    response = signed_in.request(method, concrete(path))

    assert response.status_code != 401, (
        f"{method} {path} refused a valid token"
    )


@pytest.mark.parametrize("method,path,body,expected", [
    ("GET", "/api/projects", None, 200),
    ("POST", "/api/projects", {"name": "Signed in"}, 200),
    ("GET", "/api/docs/no-such-id", None, 404),
    ("GET", "/api/docs/no-such-id/file", None, 404),
    ("POST", "/api/query", {"project_id": "no-such-id", "query": "hello"}, 404),
    ("GET", "/api/export/conversation/no-such-id", None, 404),
    ("DELETE", "/api/cache/invalidate/project/no-such-id", None, 404),
])
def test_signed_in_behaviour_is_unchanged(signed_in, method, path, body, expected):
    """One route per router group still answers what it always answered."""
    response = signed_in.request(method, path, json=body)

    assert response.status_code == expected, response.text

"""Shared fixtures for tests that talk to the API over HTTP.

Every router that reads or writes user data now requires a bearer token, so a
test that calls one has to hold a token too. `authenticated_client` builds a
client that presents one on every request, which keeps the change to existing
tests confined to how they construct their client rather than spreading through
every call they make.
"""
from __future__ import annotations

import uuid

from app.config import Settings, get_settings

# The suite must not read `backend/.env`. That file configures a running
# deployment — including keys a given checkout's `Settings` may not declare,
# which turns every test into a collection error rather than a failure anybody
# can act on. Settings are built from their declared defaults instead, and this
# runs before the imports below reach a module that reads them.
Settings.model_config["env_file"] = None
get_settings.cache_clear()

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.db.models import User  # noqa: E402
from app.services.auth import AuthService, get_auth_service  # noqa: E402

# A fixed signing key keeps issued tokens reproducible without depending on the
# environment the suite happens to run in.
TEST_AUTH_SERVICE = AuthService(
    secret_key="test-secret-key",
    access_token_expire_minutes=60,
)

TEST_USERNAME = "test-user"


def seed_user(db: Session, username: str = TEST_USERNAME) -> User:
    """Insert the active account a token can resolve to.

    Args:
        db: Session on the test database
        username: Account name the token will name

    Returns:
        The stored account
    """
    user = User(
        id=str(uuid.uuid4()),
        username=username,
        email=f"{username}@example.com",
        # Sign-in is not under test here; nothing verifies this hash.
        hashed_password="not-a-real-hash",
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    return user


def owner_id(db: Session, username: str = TEST_USERNAME) -> str:
    """Return the id of a seeded account, to stamp on rows a test creates.

    Data-bearing rows have an owner now, and the API will not return a row that
    belongs to nobody, so a fixture that inserts one directly has to say whose it
    is.

    Args:
        db: Session on the test database
        username: Account to look up

    Returns:
        The account's id

    Raises:
        AssertionError: if the account has not been seeded yet
    """
    user = db.query(User).filter(User.username == username).first()
    assert user, "seed the account first, via authorize() or authenticated_client()"

    return user.id


def auth_headers(username: str = TEST_USERNAME) -> dict[str, str]:
    """Build an Authorization header carrying a token for the given account."""
    token = TEST_AUTH_SERVICE.create_access_token(username)

    return {"Authorization": f"Bearer {token}"}


def authorize(
    app: FastAPI,
    db: Session,
    username: str = TEST_USERNAME,
) -> dict[str, str]:
    """Make an app trust a token, and return the header that carries one.

    The app's auth service is overridden with the fixed-key one so the token
    validates, and the account it names is inserted into the test database so it
    resolves to a live user.

    Use this where the test builds its own client — a client that has to be
    entered as a context manager, say. Otherwise reach for
    `authenticated_client`.

    Args:
        app: App under test; its dependency overrides are modified
        db: Session on the app's test database. The caller keeps ownership.
        username: Account the token identifies

    Returns:
        An Authorization header to pass to the client
    """
    app.dependency_overrides[get_auth_service] = lambda: TEST_AUTH_SERVICE
    seed_user(db, username)

    return auth_headers(username)


def authenticated_client(
    app: FastAPI,
    db: Session,
    username: str = TEST_USERNAME,
) -> TestClient:
    """Build a client that presents a valid bearer token on every request.

    Args:
        app: App under test; its dependency overrides are modified
        db: Session on the app's test database. The caller keeps ownership.
        username: Account the token identifies

    Returns:
        A client whose every request carries the bearer token
    """
    return TestClient(app, headers=authorize(app, db, username))


class OfflineLLM:
    """LLM stand-in that answers the way the unconfigured service does.

    `LLM_MODE` defaults to `auto`, so a real `LLMService` built in a test points
    at a local provider and every call opens a socket to it. Injecting this
    instead keeps the suite offline; what it returns is the extractive fallback
    shape, so callers take their structural path.
    """

    def generate(self, prompt: str, **kwargs) -> dict:
        """Return the fallback shape, ignoring the prompt.

        Args:
            prompt: Ignored.
            **kwargs: Ignored.

        Returns:
            The same keys the real service returns, with model "fallback".
        """
        return {
            "text": "Configure an LLM for better answers.",
            "model": "fallback",
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }

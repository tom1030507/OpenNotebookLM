"""Tests for the authentication API."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import Settings, get_settings
from app.db.database import get_db
from app.db.models import Base, User
from app.routers import auth
from app.routers.rate_limit import get_rate_limiter
from app.services.auth import AuthService, get_auth_service
from app.services.rate_limit import SlidingWindowRateLimiter

app = FastAPI()
app.include_router(auth.router, prefix="/api")

SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# A fixed test secret keeps issued tokens reproducible without touching the
# environment the rest of the suite runs in.
test_auth_service = AuthService(secret_key="test-secret-key", access_token_expire_minutes=5)


def override_get_db():
    """Override database dependency for testing."""
    try:
        db = TestingSessionLocal()
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db
app.dependency_overrides[get_auth_service] = lambda: test_auth_service
disabled_rate_limiter = SlidingWindowRateLimiter(enabled=False)
app.dependency_overrides[get_rate_limiter] = lambda: disabled_rate_limiter

Base.metadata.create_all(bind=engine)

client = TestClient(app)


def register(username, password="correct-horse", email=None):
    """Register an account through the API."""
    return client.post(
        "/api/auth/register",
        json={
            "username": username,
            "email": email or f"{username}@example.com",
            "password": password,
        },
    )


def get_token(username, password="correct-horse"):
    """Request an access token through the API."""
    return client.post(
        "/api/auth/token",
        data={"username": username, "password": password},
    )


def test_register_returns_the_account_without_any_password():
    """Registration succeeds and never echoes the credentials back."""
    response = register("ada")

    assert response.status_code == 200
    data = response.json()
    assert data["username"] == "ada"
    assert data["email"] == "ada@example.com"
    assert "id" in data
    assert "password" not in data
    assert "hashed_password" not in data
    assert "correct-horse" not in response.text


def test_register_stores_only_a_bcrypt_hash():
    """The stored password is a bcrypt hash, never the plain text."""
    register("grace", password="hopper-secret")

    with TestingSessionLocal() as db:
        user = db.query(User).filter(User.username == "grace").first()
        assert user is not None
        assert user.hashed_password != "hopper-secret"
        assert user.hashed_password.startswith("$2")


def test_register_rejects_a_duplicate_username():
    """A second registration for the same username is refused."""
    register("alan", email="alan@example.com")

    response = register("alan", email="alan.turing@example.com")

    assert response.status_code == 400
    assert "already" in response.json()["detail"].lower()


def test_register_rejects_a_duplicate_email():
    """A second registration for the same email is refused."""
    register("edsger", email="shared@example.com")

    response = register("barbara", email="shared@example.com")

    assert response.status_code == 400
    assert "already" in response.json()["detail"].lower()


def test_register_rejects_a_malformed_email():
    """An address that cannot be an email is rejected before hashing."""
    response = register("katherine", email="not-an-email")

    assert response.status_code == 422


def test_token_is_issued_for_a_registered_account():
    """Valid credentials return a bearer access token."""
    register("linus", password="kernel-secret")

    response = get_token("linus", password="kernel-secret")

    assert response.status_code == 200
    data = response.json()
    assert data["token_type"] == "bearer"
    assert data["access_token"]


def test_token_rejects_a_wrong_password():
    """A wrong password fails with 401 and a readable message."""
    register("margaret", password="apollo-secret")

    response = get_token("margaret", password="wrong-password")

    assert response.status_code == 401
    assert response.json()["detail"] == "Incorrect username or password"


def test_token_rejects_an_unknown_username():
    """An account that was never registered cannot sign in."""
    response = get_token("nobody", password="whatever-secret")

    assert response.status_code == 401
    assert response.json()["detail"] == "Incorrect username or password"


def test_me_accepts_a_freshly_issued_token():
    """The token issued at sign-in identifies the account."""
    register("barbara2", email="barbara2@example.com")
    token = get_token("barbara2").json()["access_token"]

    response = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json()["username"] == "barbara2"


def test_me_rejects_a_missing_token():
    """Without credentials the account endpoint is unauthorized."""
    response = client.get("/api/auth/me")

    assert response.status_code == 401


def test_me_rejects_a_malformed_token():
    """A token that is not a JWT at all is refused."""
    response = client.get(
        "/api/auth/me",
        headers={"Authorization": "Bearer not-a-token"},
    )

    assert response.status_code == 401


def test_me_rejects_a_token_signed_with_another_secret():
    """A token minted with a different secret does not authenticate."""
    register("forger")
    forged = AuthService(secret_key="another-secret").create_access_token("forger")

    response = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {forged}"},
    )

    assert response.status_code == 401


def test_me_rejects_an_expired_token():
    """An expired token stops working."""
    register("expired")
    stale = AuthService(
        secret_key="test-secret-key",
        access_token_expire_minutes=-1,
    ).create_access_token("expired")

    response = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {stale}"},
    )

    assert response.status_code == 401


def test_me_rejects_a_token_for_a_deleted_account():
    """A valid signature is not enough once the account is gone."""
    register("vanishing")
    token = get_token("vanishing").json()["access_token"]

    with TestingSessionLocal() as db:
        db.query(User).filter(User.username == "vanishing").delete()
        db.commit()

    response = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 401


def test_password_verification_rejects_a_similar_password():
    """Hashing is order and content sensitive, not a prefix match."""
    service = AuthService(secret_key="test-secret-key")
    hashed = service.hash_password("a-long-enough-secret")

    assert service.verify_password("a-long-enough-secret", hashed) is True
    assert service.verify_password("a-long-enough-secre", hashed) is False


def test_jwt_secret_is_required_outside_development():
    """A deployment must supply its own signing key."""
    from app.config import Settings
    from app.services.auth import resolve_jwt_secret_key

    with pytest.raises(RuntimeError):
        resolve_jwt_secret_key(Settings(app_env="production", jwt_secret_key=None))

    assert resolve_jwt_secret_key(
        Settings(app_env="production", jwt_secret_key="supplied")
    ) == "supplied"


def test_fourth_registration_from_one_client_ip_returns_429_with_retry_after():
    """Public account creation is limited to three attempts per IP per hour."""
    limiter = SlidingWindowRateLimiter(clock=lambda: 0.0)
    app.dependency_overrides[get_rate_limiter] = lambda: limiter
    try:
        responses = [register("rate-register-%s" % index) for index in range(4)]
    finally:
        app.dependency_overrides[get_rate_limiter] = lambda: disabled_rate_limiter

    assert [response.status_code for response in responses] == [200, 200, 200, 429]
    assert responses[-1].headers["Retry-After"] == "3600"


def test_eleventh_login_from_one_client_ip_returns_429_with_retry_after():
    """Password verification is limited to ten attempts per IP per minute."""
    limiter = SlidingWindowRateLimiter()
    app.dependency_overrides[get_rate_limiter] = lambda: limiter
    try:
        responses = [get_token("missing-rate-user") for _ in range(11)]
    finally:
        app.dependency_overrides[get_rate_limiter] = lambda: disabled_rate_limiter

    assert [response.status_code for response in responses[:10]] == [401] * 10
    assert responses[-1].status_code == 429
    assert responses[-1].headers["Retry-After"] == "60"


def test_production_registration_is_closed_by_default():
    """Production refuses public enrollment unless an operator opts in."""
    app.dependency_overrides[get_settings] = lambda: Settings(app_env="production")
    try:
        response = register("closed-production")
    finally:
        app.dependency_overrides.pop(get_settings, None)

    assert response.status_code == 403
    assert response.json()["detail"] == "Public registration is disabled"


def test_development_registration_remains_open_by_default():
    """Local development preserves the existing no-configuration signup flow."""
    app.dependency_overrides[get_settings] = lambda: Settings(app_env="development")
    try:
        response = register("open-development")
    finally:
        app.dependency_overrides.pop(get_settings, None)

    assert response.status_code == 200


def test_development_can_explicitly_disable_rate_limits():
    """Local tests and trusted development can switch limiter state off."""
    limiter = SlidingWindowRateLimiter(clock=lambda: 0.0)
    app.dependency_overrides[get_rate_limiter] = lambda: limiter
    app.dependency_overrides[get_settings] = lambda: Settings(
        app_env="development",
        rate_limit_enabled=False,
    )
    try:
        responses = [register("no-limit-%s" % index) for index in range(4)]
    finally:
        app.dependency_overrides[get_rate_limiter] = lambda: disabled_rate_limiter
        app.dependency_overrides.pop(get_settings, None)

    assert [response.status_code for response in responses] == [200] * 4

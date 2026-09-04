"""The demo account is present after startup, not only after a manual script."""
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import get_settings
from app.db.models import Base, User
from app.services.auth import get_auth_service


def isolated_sessions():
    """Create an isolated account database and session factory.

    Returns:
        SQLAlchemy session factory backed by one in-memory database.
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


def run_startup(monkeypatch, sessions):
    """Run the application lifespan against an isolated database.

    Args:
        monkeypatch: Pytest monkeypatch fixture.
        sessions: Session factory the lifespan should use.

    Returns:
        None once startup and shutdown have both completed.
    """
    from app import lifecycle

    monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-key-for-lifespan")
    monkeypatch.setattr(lifecycle, "SessionLocal", sessions)
    # Schema creation belongs to the module engine, which points at the real
    # database file. This test is about seeding, not about DDL.
    monkeypatch.setattr(lifecycle, "init_db", lambda: None)
    get_settings.cache_clear()
    get_auth_service.cache_clear()
    try:
        with TestClient(FastAPI(lifespan=lifecycle.lifespan)):
            pass
    finally:
        get_auth_service.cache_clear()
        get_settings.cache_clear()


def test_startup_leaves_a_demo_account_ready_to_sign_in(monkeypatch):
    """Bringing the service up is all it takes to have the demo account."""
    sessions = isolated_sessions()

    run_startup(monkeypatch, sessions)

    with sessions() as db:
        demo = db.query(User).filter(User.username == "demo").one()
        assert demo.email == "demo@example.com"
        assert get_auth_service().verify_password("demo1234", demo.hashed_password)


def test_second_startup_does_not_add_a_second_demo_account(monkeypatch):
    """Restarts keep exactly one demo account."""
    sessions = isolated_sessions()

    run_startup(monkeypatch, sessions)
    run_startup(monkeypatch, sessions)

    with sessions() as db:
        assert db.query(User).filter(User.username == "demo").count() == 1

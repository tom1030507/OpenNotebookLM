"""Operational account-bootstrap tests."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import Base, User
from app.services.auth import AuthService
from app.services.auth import DuplicateUserError
from scripts.create_user import create_user, main


def database_factory():
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


def test_create_user_is_idempotent_without_changing_the_password_hash():
    """Re-running bootstrap for the same identity preserves the account."""
    sessions = database_factory()
    service = AuthService(secret_key="unused-by-bootstrap")
    with sessions() as db:
        first, first_created = create_user(
            db,
            service,
            username="operator",
            email="operator@example.com",
            password="first-bootstrap-password",
        )
        original_hash = first.hashed_password
        second, second_created = create_user(
            db,
            service,
            username="operator",
            email="operator@example.com",
            password="replacement-password",
        )

        assert first_created is True
        assert second_created is False
        assert second.id == first.id
        assert second.hashed_password == original_hash
        assert db.query(User).count() == 1


def test_cli_prompts_hidden_and_never_prints_password_material(capsys):
    """Bootstrap output identifies the account without leaking credentials."""
    sessions = database_factory()
    supplied = iter(["cli-secret-password", "cli-secret-password"])

    exit_code = main(
        ["--username", "cli-user", "--email", "cli@example.com"],
        password_reader=lambda prompt: next(supplied),
        session_factory=sessions,
        initialize_database=lambda: None,
    )

    output = capsys.readouterr()
    assert exit_code == 0
    assert "cli-user" in output.out
    assert "cli-secret-password" not in output.out + output.err
    assert "$2" not in output.out + output.err


def test_idempotent_cli_run_does_not_prompt_for_a_password(capsys):
    """Automation can safely repeat bootstrap after the account exists."""
    sessions = database_factory()
    first_passwords = iter(["cli-secret-password", "cli-secret-password"])
    arguments = ["--username", "repeat-user", "--email", "repeat@example.com"]
    assert main(
        arguments,
        password_reader=lambda prompt: next(first_passwords),
        session_factory=sessions,
        initialize_database=lambda: None,
    ) == 0

    def must_not_prompt(prompt):
        raise AssertionError("idempotent bootstrap prompted for a password")

    assert main(
        arguments,
        password_reader=must_not_prompt,
        session_factory=sessions,
        initialize_database=lambda: None,
    ) == 0
    assert "already exists" in capsys.readouterr().out.lower()


def test_create_user_rejects_a_partial_identity_collision():
    """A username cannot be silently rebound to a different email."""
    sessions = database_factory()
    service = AuthService(secret_key="unused-by-bootstrap")
    with sessions() as db:
        create_user(
            db,
            service,
            username="operator",
            email="first@example.com",
            password="first-bootstrap-password",
        )

        with pytest.raises(DuplicateUserError):
            create_user(
                db,
                service,
                username="operator",
                email="other@example.com",
                password="other-bootstrap-password",
            )

        assert db.query(User).count() == 1

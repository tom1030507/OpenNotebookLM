"""Bootstrap an account when public registration is disabled."""
import argparse
import getpass
import sys
from typing import Callable, Optional, Sequence, Tuple

from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.database import SessionLocal, init_db
from app.db.models import User
from app.schemas import UserRegister
from app.services.auth import AuthService, DuplicateUserError


def _existing_identity(db: Session, username: str, email: str) -> Optional[User]:
    """Return a row colliding with either bootstrap identity field.

    Args:
        db: SQLAlchemy session.
        username: Requested account username.
        email: Requested account email.

    Returns:
        Matching account, if any.
    """
    return db.query(User).filter(
        (User.username == username) | (User.email == email)
    ).first()


def create_user(
    db: Session,
    auth_service: AuthService,
    username: str,
    email: str,
    password: str,
) -> Tuple[User, bool]:
    """Create one account, treating the same identity as an idempotent success.

    Args:
        db: SQLAlchemy session.
        auth_service: Password hashing/account service.
        username: Account username.
        email: Account email.
        password: Plain password supplied only to the hashing boundary.

    Returns:
        A pair of the account and whether this call created it.

    Raises:
        DuplicateUserError: If username or email belongs to a different
            identity.
    """
    existing = _existing_identity(db, username, email)
    if existing:
        if existing.username == username and existing.email == email:
            return existing, False
        raise DuplicateUserError("That username or email is already registered")

    try:
        return auth_service.register_user(db, username, email, password), True
    except IntegrityError as exc:
        # Another bootstrap process can win after the query above. Re-read after
        # rollback so an identical concurrent command is still idempotent.
        db.rollback()
        existing = _existing_identity(db, username, email)
        if existing and existing.username == username and existing.email == email:
            return existing, False
        raise DuplicateUserError(
            "That username or email is already registered"
        ) from exc


def main(
    argv: Optional[Sequence[str]] = None,
    password_reader: Callable[[str], str] = getpass.getpass,
    session_factory: Callable = SessionLocal,
    initialize_database: Callable[[], None] = init_db,
) -> int:
    """Run the account bootstrap command.

    Args:
        argv: Optional CLI argument list.
        password_reader: Hidden password prompt callable.
        session_factory: Database session factory.
        initialize_database: Database initializer.

    Returns:
        Zero on creation/idempotent success, two on invalid input/conflict.
    """
    parser = argparse.ArgumentParser(
        description="Create an OpenNotebookLM account without public signup.",
    )
    parser.add_argument("--username", required=True)
    parser.add_argument("--email", required=True)
    args = parser.parse_args(argv)

    initialize_database()
    with session_factory() as db:
        existing = _existing_identity(db, args.username, args.email)
        if existing:
            if existing.username == args.username and existing.email == args.email:
                print("User %s already exists." % args.username)
                return 0
            print(
                "That username or email is already registered.",
                file=sys.stderr,
            )
            return 2

        password = password_reader("Password: ")
        confirmation = password_reader("Confirm password: ")
        if password != confirmation:
            print("Passwords do not match.", file=sys.stderr)
            return 2

        try:
            validated = UserRegister(
                username=args.username,
                email=args.email,
                password=password,
            )
        except ValidationError:
            # Pydantic's detailed error includes the rejected input value; a
            # generic message keeps the password out of terminal logs.
            print("Invalid username, email, or password.", file=sys.stderr)
            return 2

        auth_service = AuthService(secret_key="unused-by-account-bootstrap")
        try:
            user, created = create_user(
                db,
                auth_service,
                username=validated.username,
                email=validated.email,
                password=validated.password,
            )
        except DuplicateUserError as exc:
            print(str(exc), file=sys.stderr)
            return 2

        action = "Created" if created else "User already exists for"
        print("%s user %s." % (action, user.username))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())

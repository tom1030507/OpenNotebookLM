"""Seed the demo account a fresh deployment can sign in with."""
from dataclasses import dataclass
from typing import Optional

from pydantic import ValidationError
from sqlalchemy.orm import Session
import structlog

from app.db.models import User
from app.schemas import UserRegister
from app.services.auth import AuthService

logger = structlog.get_logger()


@dataclass(frozen=True)
class DemoAccount:
    """Credentials a sign-in page may advertise as ready to use."""

    username: str
    password: str


def advertised_demo_account(
    db: Session,
    auth_service: AuthService,
    *,
    enabled: bool,
    username: str,
    email: str,
    password: str,
) -> Optional[DemoAccount]:
    """Report the credentials a sign-in page may publish, if any.

    Read-only. The stored password is verified rather than assumed, so an
    account whose password somebody changed stops being advertised instead of
    putting a password on the sign-in page that cannot sign in.

    Args:
        db: SQLAlchemy session.
        auth_service: Password hashing/account service.
        enabled: Whether this deployment offers a demo account at all.
        username: Configured demo username.
        email: Configured demo email.
        password: Configured demo password.

    Returns:
        The credentials to advertise, or None when there are none to offer.
    """
    if not enabled:
        return None

    account = db.query(User).filter(
        (User.username == username) | (User.email == email)
    ).first()
    if account is None:
        return None
    if not auth_service.verify_password(password, account.hashed_password):
        return None
    return DemoAccount(username=account.username, password=password)


def ensure_demo_account(
    db: Session,
    auth_service: AuthService,
    *,
    enabled: bool,
    username: str,
    email: str,
    password: str,
) -> Optional[DemoAccount]:
    """Create the demo account when it is missing, and report it.

    An existing account is left exactly as it is — this never overwrites a
    password somebody changed on purpose.

    Args:
        db: SQLAlchemy session.
        auth_service: Password hashing/account service.
        enabled: Whether this deployment wants a demo account at all.
        username: Demo account username.
        email: Demo account email.
        password: Demo account password.

    Returns:
        The credentials to advertise, or None when there are none to offer.
    """
    if not enabled:
        return None

    try:
        UserRegister(username=username, email=email, password=password)
    except ValidationError:
        # A convenience account is not worth refusing to serve over. Say why
        # once, without the rejected value, and carry on without one.
        logger.error(
            "Demo account not seeded: configured credentials fail validation",
            username=username,
        )
        return None

    already_present = db.query(User).filter(
        (User.username == username) | (User.email == email)
    ).first()
    if already_present is None:
        auth_service.register_user(db, username, email, password)

    return advertised_demo_account(
        db,
        auth_service,
        enabled=True,
        username=username,
        email=email,
        password=password,
    )

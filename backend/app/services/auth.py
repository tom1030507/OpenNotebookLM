"""Authentication service: password hashing, accounts and access tokens."""
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Optional

import bcrypt
import structlog
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db.models import User

logger = structlog.get_logger()

# bcrypt only reads the first 72 bytes of a password and versions from 4.2
# refuse anything longer instead of truncating, so reject it up front.
BCRYPT_MAX_PASSWORD_BYTES = 72

# passlib 1.7.4 cannot drive bcrypt 5.x at all: its backend probe hashes an
# over-long password and dies on the ValueError above. bcrypt is the engine
# passlib[bcrypt] installs, so this module uses it directly.


class DuplicateUserError(Exception):
    """Raised when a username or email is already registered."""


class AuthService:
    """Hashes passwords, stores accounts and mints signed access tokens."""

    def __init__(
        self,
        secret_key: str,
        algorithm: str = "HS256",
        access_token_expire_minutes: int = 720,
    ):
        self.secret_key = secret_key
        self.algorithm = algorithm
        self.access_token_expire_minutes = access_token_expire_minutes

    def hash_password(self, password: str) -> str:
        """Hash a password with a per-password bcrypt salt."""
        encoded = password.encode("utf-8")
        if len(encoded) > BCRYPT_MAX_PASSWORD_BYTES:
            raise ValueError(
                f"Password must be at most {BCRYPT_MAX_PASSWORD_BYTES} bytes"
            )
        return bcrypt.hashpw(encoded, bcrypt.gensalt()).decode("utf-8")

    def verify_password(self, password: str, hashed_password: str) -> bool:
        """Check a password against its stored hash."""
        try:
            return bcrypt.checkpw(
                password.encode("utf-8"),
                hashed_password.encode("utf-8"),
            )
        except ValueError:
            # An over-long password or a hash this bcrypt build cannot read.
            return False

    def register_user(
        self,
        db: Session,
        username: str,
        email: str,
        password: str,
    ) -> User:
        """Create an account, or raise DuplicateUserError if it is taken."""
        existing = db.query(User).filter(
            (User.username == username) | (User.email == email)
        ).first()
        if existing:
            raise DuplicateUserError(
                "That username or email is already registered"
            )

        user = User(
            id=str(uuid.uuid4()),
            username=username,
            email=email,
            hashed_password=self.hash_password(password),
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)

        logger.info("User registered", user_id=user.id, username=username)
        return user

    def authenticate_user(
        self,
        db: Session,
        username: str,
        password: str,
    ) -> Optional[User]:
        """Return the account when the credentials match, otherwise None."""
        user = db.query(User).filter(
            (User.username == username) | (User.email == username)
        ).first()

        if not user or not user.is_active:
            return None

        if not self.verify_password(password, user.hashed_password):
            logger.info("Rejected sign-in attempt", username=username)
            return None

        user.last_login_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(user)
        return user

    def create_access_token(self, username: str) -> str:
        """Mint a signed token that identifies the given account."""
        expires_at = datetime.now(timezone.utc) + timedelta(
            minutes=self.access_token_expire_minutes
        )
        return jwt.encode(
            {"sub": username, "exp": expires_at},
            self.secret_key,
            algorithm=self.algorithm,
        )

    def get_user_from_token(self, db: Session, token: str) -> Optional[User]:
        """Resolve a token to a live account, or None if it does not."""
        try:
            payload = jwt.decode(token, self.secret_key, algorithms=[self.algorithm])
        except JWTError:
            return None

        username = payload.get("sub")
        if not username:
            return None

        user = db.query(User).filter(User.username == username).first()
        if not user or not user.is_active:
            return None

        return user


def resolve_jwt_secret_key(settings: Settings) -> str:
    """Return the token signing key, refusing to invent one for a deployment.

    Args:
        settings: Application settings containing the environment and key.

    Returns:
        The configured key, or a per-process development key.

    Raises:
        RuntimeError: If a non-development environment has no usable key.
    """
    configured_key = (settings.jwt_secret_key or "").strip()
    if configured_key:
        return configured_key

    if settings.app_env != "development":
        raise RuntimeError(
            "JWT_SECRET_KEY must be set when APP_ENV is not 'development'"
        )

    logger.warning(
        "JWT_SECRET_KEY is unset; signing with a key that lasts one process. "
        "Sign-ins will not survive a restart."
    )
    return secrets.token_urlsafe(32)


@lru_cache()
def get_auth_service() -> AuthService:
    """Get the cached auth service, built from application settings.

    Args:
        None.

    Returns:
        The process-wide authentication service.
    """
    settings = get_settings()
    return AuthService(
        secret_key=resolve_jwt_secret_key(settings),
        algorithm=settings.jwt_algorithm,
        access_token_expire_minutes=settings.access_token_expire_minutes,
    )

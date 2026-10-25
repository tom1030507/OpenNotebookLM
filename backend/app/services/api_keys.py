"""Create and authenticate long-lived personal API keys."""
import hashlib
import secrets
import uuid
from typing import Optional

import structlog
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.models import APIKey, User
from app.utils.time import utc_now

logger = structlog.get_logger()
API_KEY_PREFIX = "onlm_"


def hash_api_key(api_key: str) -> str:
    """Return the SHA-256 digest used to look up a random API key.

    Args:
        api_key: High-entropy bearer token.

    Returns:
        A lowercase hexadecimal digest.
    """
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def create_personal_api_key(
    db: Session,
    user: User,
    name: str,
) -> tuple[APIKey, str]:
    """Persist one key digest and return its secret for one-time display.

    Args:
        db: Database session.
        user: Account that owns the new key.
        name: User-provided key label.

    Returns:
        The key metadata row and the newly generated bearer token.
    """
    api_key = "%s%s" % (API_KEY_PREFIX, secrets.token_urlsafe(32))
    record = APIKey(
        id=str(uuid.uuid4()),
        user_id=user.id,
        name=name,
        key_hash=hash_api_key(api_key),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record, api_key


def list_personal_api_keys(db: Session, user: User) -> list[APIKey]:
    """List metadata for only the caller's active personal keys.

    Args:
        db: Database session.
        user: Account whose keys are listed.

    Returns:
        Key rows in newest-first order, without any plaintext secret.
    """
    return db.query(APIKey).filter(
        APIKey.user_id == user.id,
    ).order_by(
        APIKey.created_at.desc(), APIKey.id,
    ).all()


def revoke_personal_api_key(db: Session, user: User, key_id: str) -> bool:
    """Delete a key only when it belongs to the caller.

    Args:
        db: Database session.
        user: Account attempting the revoke.
        key_id: Key row id from the request path.

    Returns:
        True when the caller's key was deleted, otherwise False.
    """
    record = db.query(APIKey).filter(
        APIKey.id == key_id,
        APIKey.user_id == user.id,
    ).first()
    if record is None:
        return False
    db.delete(record)
    db.commit()
    return True


def get_user_from_api_key(db: Session, api_key: str) -> Optional[User]:
    """Resolve an active key to its account and persist its last-use time.

    Args:
        db: Database session.
        api_key: Presented bearer token.

    Returns:
        The active account owning the key, or None when it is invalid.
    """
    if not api_key.startswith(API_KEY_PREFIX):
        return None

    record = db.query(APIKey).filter(
        APIKey.key_hash == hash_api_key(api_key),
    ).first()
    if record is None:
        return None

    user = db.query(User).filter(
        User.id == record.user_id,
        User.is_active.is_(True),
    ).first()
    if user is None:
        return None

    record.last_used_at = utc_now()
    try:
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        # Usage tracking must not make a valid credential unusable during a
        # transient write failure.
        logger.warning("Could not update API key last-used time", api_key_id=record.id)
    return user

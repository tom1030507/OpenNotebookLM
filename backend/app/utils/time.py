"""UTC time helpers.

Timestamps are stored naive and in UTC, and every datetime that leaves this
service has to say so. A value serialised without a timezone designator — such
as ``2026-08-13T09:00:00`` — is read as *local* time by ECMAScript, so a browser
in UTC+8 renders a record created seconds ago as hours old.

Everything in the service therefore goes through one of two places: reads of a
stored datetime pass through :class:`app.db.types.UTCDateTime`, which labels
them, and newly generated datetimes come from :func:`utc_now` here rather than
from ``datetime.now()`` or the deprecated ``datetime.utcnow()``, neither of
which produces an aware value.
"""
from datetime import datetime, timezone
from typing import Optional

UTC = timezone.utc


def utc_now() -> datetime:
    """Return the current time as a timezone-aware UTC datetime."""
    return datetime.now(UTC)


def utc_now_iso() -> str:
    """Return the current time as an ISO 8601 string carrying a UTC designator."""
    return utc_now().isoformat()


def as_utc(value: Optional[datetime]) -> Optional[datetime]:
    """Label or convert a datetime to UTC without moving the instant.

    A naive value is assumed to already be UTC, which is how this service stores
    it. An aware value is converted, so a caller that supplies another zone still
    gets the same instant back.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def naive_utc(value: Optional[datetime]) -> Optional[datetime]:
    """Reduce a datetime to the naive UTC form used for storage.

    Keeps what is written to the database identical to what was written before
    aware datetimes existed in the application, so no migration is needed.
    """
    value = as_utc(value)
    if value is None:
        return None
    return value.replace(tzinfo=None)

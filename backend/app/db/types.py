"""Custom SQLAlchemy column types."""
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime
from sqlalchemy.types import TypeDecorator

from app.utils.time import as_utc, naive_utc


class UTCDateTime(TypeDecorator):
    """A ``DateTime`` column that always hands Python a UTC-aware value.

    Storage is unchanged — naive UTC, exactly what ``func.now()`` writes — so
    existing rows and existing databases keep working without a migration. The
    only difference is on the way out: loaded values carry ``tzinfo=UTC``, which
    is what makes every serialiser downstream (Pydantic response models,
    FastAPI's encoder for hand-built dicts, and direct ``.isoformat()`` calls in
    the export service) emit a UTC designator instead of a bare local-looking
    date-time that browsers misread as local time.
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(
        self, value: Optional[datetime], dialect
    ) -> Optional[datetime]:
        """Normalise anything on its way in to the stored naive UTC form."""
        return naive_utc(value)

    def process_result_value(
        self, value: Optional[datetime], dialect
    ) -> Optional[datetime]:
        """Label anything on its way out as the UTC instant it already is."""
        return as_utc(value)

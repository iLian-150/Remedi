"""Shared application-local clock helpers for naive database datetimes."""
from datetime import datetime
from zoneinfo import ZoneInfo

from ..config import settings

_APP_TIMEZONE = ZoneInfo(settings.APP_TIMEZONE)


def deadline_now() -> datetime:
    """Return app-local wall time for values stored as naive deadlines."""
    return datetime.now(_APP_TIMEZONE).replace(tzinfo=None)


def normalize_deadline(deadline: datetime | None) -> datetime | None:
    """Convert aware timestamps to app-local naive time for database comparison."""
    if deadline is None or deadline.tzinfo is None:
        return deadline
    return deadline.astimezone(_APP_TIMEZONE).replace(tzinfo=None)

"""UTC helpers for values that cross the API boundary.

MySQL and SQLite hand back NAIVE datetimes (no time zone), even though everything is
stored in UTC. Serialised as-is, "2026-11-09T11:41:21" means LOCAL time to a browser,
which is 5.5 hours off in India. UTCDateTime marks naive values as UTC, so the API
always sends "2026-11-09T11:41:21Z" and clients convert to local time correctly.
"""

from datetime import UTC, datetime
from typing import Annotated

from pydantic import AfterValidator


def as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


UTCDateTime = Annotated[datetime, AfterValidator(as_utc)]

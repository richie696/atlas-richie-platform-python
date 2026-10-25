"""Shared timestamp constraints for Console wire instants."""

from __future__ import annotations

from datetime import UTC, datetime

_MIN_SUPPORTED_UTC_YEAR = 1970


def current_utc_millisecond_instant() -> datetime:
    """Return current UTC time truncated to the Console wire precision."""
    now = datetime.now(UTC)
    return now.replace(microsecond=(now.microsecond // 1_000) * 1_000)


def is_wire_utc_millisecond_instant(value: datetime) -> bool:
    """Return whether a datetime can be represented by the Console UTC-ms wire."""
    return (
        isinstance(value, datetime)
        and value.tzinfo is not None
        and value.utcoffset() is not None
        and _MIN_SUPPORTED_UTC_YEAR <= value.year <= 9999
        and value.microsecond % 1_000 == 0
    )

"""Strict primitive query parsing shared by read-only observation routes."""

from __future__ import annotations

from datetime import UTC, datetime
import re

_UTC_MILLISECOND_PATTERN = re.compile(
    r"^(?:19[7-9]\d|[2-9]\d{3})-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$"
)
_DECIMAL_INTEGER_PATTERN = re.compile(r"^[0-9]+$")


def parse_integer(value: str, minimum: int, maximum: int) -> int:
    """Parse one unsigned decimal integer within its endpoint-specific bounds."""
    if _DECIMAL_INTEGER_PATTERN.fullmatch(value) is None:
        raise ValueError("integer query parameter is malformed")
    result = int(value)
    if not minimum <= result <= maximum:
        raise ValueError("integer query parameter is out of range")
    return result


def parse_utc_timestamp(value: str) -> datetime:
    """Parse the Console RFC3339 UTC timestamp with required millisecond precision."""
    if _UTC_MILLISECOND_PATTERN.fullmatch(value) is None:
        raise ValueError("timestamp query parameter must be UTC milliseconds")
    return datetime.fromisoformat(value[:-1] + "+00:00").astimezone(UTC)

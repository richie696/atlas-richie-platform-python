"""Strict primitive query parsing shared by read-only observation routes."""

from __future__ import annotations

import re
from datetime import UTC, datetime

from starlette.requests import Request

_UTC_MILLISECOND_PATTERN = re.compile(
    r"^(?:19[7-9]\d|[2-9]\d{3})-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$"
)
_DECIMAL_INTEGER_PATTERN = re.compile(r"^[0-9]+$")

MIN_QUERY_INTEGER = 1
MAX_QUERY_PAGE_NUMBER = 1_000_000
MAX_QUERY_PAGE_SIZE = 100
MAX_QUERY_STEP_MS = 604_800_000


def parse_query_values(
    request: Request,
    required: frozenset[str],
    optional: frozenset[str] = frozenset(),
) -> dict[str, str]:
    """Return one value per declared query key or reject the entire query.

    Starlette exposes decoded query keys through ``multi_items``. Checking the
    decoded pairs here prevents encoded aliases from bypassing duplicate-key
    rejection and keeps endpoint parsers on the same strict wire boundary.
    """
    allowed = required | optional
    supplied: dict[str, str] = {}
    for name, value in request.query_params.multi_items():
        if name not in allowed or name in supplied:
            raise ValueError("query parameters must be known and unique")
        supplied[name] = value
    if not required.issubset(supplied):
        raise ValueError("required query parameter is missing")
    return supplied


def parse_integer(value: str, minimum: int, maximum: int) -> int:
    """Parse one canonical ASCII decimal integer within endpoint-specific bounds."""
    if _DECIMAL_INTEGER_PATTERN.fullmatch(value) is None or (
        len(value) > 1 and value.startswith("0")
    ):
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

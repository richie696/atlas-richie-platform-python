"""Small shared HTTP primitives for Console protocol adapters."""

from __future__ import annotations

import json
import re
from types import MappingProxyType
from typing import Final, Mapping
from uuid import uuid4

from starlette.requests import Request
from starlette.responses import JSONResponse

_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
ERROR_STATUS_BY_CODE: Final[Mapping[str, int]] = MappingProxyType(
    {
        "invalid_request": 400,
        "current_password_invalid": 400,
        "unauthenticated": 401,
        "forbidden": 403,
        "csrf_failed": 403,
        "bootstrap_unauthorized": 403,
        "not_found": 404,
        "conflict": 409,
        "idempotency_conflict": 409,
        "target_retired": 410,
        "validation_failed": 422,
        "unsupported_profile": 422,
        "rate_limited": 429,
        "service_unavailable": 503,
        "dependency_unavailable": 503,
    }
)


def request_id(request: Request) -> tuple[str, bool]:
    """Validate a caller correlation ID without reflecting invalid input."""
    supplied = request.headers.get("x-request-id", "")
    if _REQUEST_ID_PATTERN.fullmatch(supplied):
        return supplied, True
    return str(uuid4()), False


def strict_request_id(request: Request) -> tuple[str, bool]:
    """Reject duplicate correlation headers instead of trusting parser order."""
    if len(request.headers.getlist("x-request-id")) != 1:
        return request_id(request)[0], False
    return request_id(request)


def error_response(
    request_id_value: str,
    code: str,
    status_code: int,
    *,
    retry_after_ms: int | None = None,
) -> JSONResponse:
    """Create the bounded Console error envelope without infrastructure detail."""
    if ERROR_STATUS_BY_CODE.get(code) != status_code:
        raise ValueError("Console error code/status contract mismatch")
    error: dict[str, object] = {"code": code, "requestId": request_id_value}
    if retry_after_ms is not None:
        error["retryAfterMs"] = max(0, min(retry_after_ms, 300_000))
    return JSONResponse(
        {"error": error},
        status_code=status_code,
        headers={"x-request-id": request_id_value, "cache-control": "no-store"},
    )


def cookie_count(request: Request, cookie_name: str) -> int:
    """Count a named cookie without trusting parser behavior for duplicates."""
    matches = 0
    for header in request.headers.getlist("cookie"):
        for segment in header.split(";"):
            name, separator, _value = segment.strip().partition("=")
            if separator and name == cookie_name:
                matches += 1
    return matches


async def read_json_object(
    request: Request, maximum_bytes: int
) -> dict[str, object] | None:
    """Read one bounded JSON object, rejecting duplicate keys and bad framing."""
    content_types = request.headers.getlist("content-type")
    if (
        len(content_types) != 1
        or content_types[0].partition(";")[0].strip().lower() != "application/json"
    ):
        return None
    content_lengths = request.headers.getlist("content-length")
    if len(content_lengths) > 1:
        return None
    if content_lengths:
        try:
            declared_length = int(content_lengths[0])
        except ValueError:
            return None
        if declared_length < 0 or declared_length > maximum_bytes:
            return None

    chunks: list[bytes] = []
    body_size = 0
    async for chunk in request.stream():
        body_size += len(chunk)
        if body_size > maximum_bytes:
            return None
        chunks.append(chunk)
    try:
        body = json.loads(
            b"".join(chunks), object_pairs_hook=_object_without_duplicate_keys
        )
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
        return None
    if not isinstance(body, dict) or not _has_only_unicode_scalar_values(body):
        return None
    return body


def _has_only_unicode_scalar_values(value: object) -> bool:
    """Reject lone surrogate escapes that cannot be represented in UTF-8 wire text."""
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, str):
            if any(0xD800 <= ord(character) <= 0xDFFF for character in item):
                return False
        elif isinstance(item, dict):
            pending.extend(item.keys())
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)
    return True


def _object_without_duplicate_keys(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result

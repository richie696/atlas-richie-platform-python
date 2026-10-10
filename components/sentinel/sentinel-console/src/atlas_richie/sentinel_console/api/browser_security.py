"""Shared exact-origin and double-submit CSRF checks for browser requests."""

from __future__ import annotations

import hashlib
import hmac
import re

from starlette.requests import Request

from .browser_origin import normalize_browser_origin
from .http_support import cookie_count

SESSION_COOKIE_NAME = "sentinel_session"
CSRF_COOKIE_NAME = "__Host-sentinel_csrf"
_OPAQUE_VALUE_PATTERN = re.compile(r"^[A-Za-z0-9_-]{32,256}$")


def browser_write_proof(
    request: Request, allowed_origins: frozenset[str]
) -> tuple[tuple[str, str] | None, tuple[str, int] | None]:
    """Verify the exact Origin and CSRF cookie/header pair for a browser write."""
    origin_values = request.headers.getlist("origin")
    if len(origin_values) != 1:
        return None, ("csrf_failed", 403)
    try:
        origin = normalize_browser_origin(origin_values[0])
    except ValueError:
        return None, ("csrf_failed", 403)
    if origin not in allowed_origins:
        return None, ("csrf_failed", 403)

    csrf_values = request.headers.getlist("x-sentinel-csrf")
    csrf_cookie = request.cookies.get(CSRF_COOKIE_NAME)
    if (
        len(csrf_values) != 1
        or cookie_count(request, CSRF_COOKIE_NAME) != 1
        or csrf_cookie is None
        or _OPAQUE_VALUE_PATTERN.fullmatch(csrf_values[0]) is None
        or not hmac.compare_digest(csrf_values[0], csrf_cookie)
    ):
        return None, ("csrf_failed", 403)
    session_digest, failure = browser_session_digest(request)
    if failure is not None:
        return None, failure
    assert session_digest is not None
    csrf_digest = hashlib.sha256(csrf_values[0].encode("ascii")).hexdigest()
    return (session_digest, csrf_digest), None


def browser_session_digest(
    request: Request,
) -> tuple[str | None, tuple[str, int] | None]:
    """Validate the unique opaque session cookie and return its one-way digest."""
    if cookie_count(request, SESSION_COOKIE_NAME) != 1:
        return None, ("unauthenticated", 401)
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if token is None or _OPAQUE_VALUE_PATTERN.fullmatch(token) is None:
        return None, ("unauthenticated", 401)
    return hashlib.sha256(token.encode("ascii")).hexdigest(), None

"""Shared exact-origin and double-submit CSRF checks for browser requests."""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import os
import re
from urllib.parse import urlsplit

from starlette.requests import Request

from .browser_origin import normalize_browser_origin
from .http_support import cookie_count

_LOOPBACK_HTTP_COOKIES_ENV = "SENTINEL_CONSOLE_ALLOW_INSECURE_LOOPBACK_COOKIES"


def _cookie_policy() -> tuple[str, str, bool]:
    """Use non-Secure cookies only for an explicitly constrained local HTTP setup."""
    mode = os.environ.get(_LOOPBACK_HTTP_COOKIES_ENV, "false").strip().lower()
    if mode not in {"true", "false"}:
        raise RuntimeError(f"{_LOOPBACK_HTTP_COOKIES_ENV} must be true or false")
    if mode == "false":
        return "sentinel_session", "__Host-sentinel_csrf", True

    bind_host = os.environ.get("SENTINEL_CONSOLE_BIND_HOST", "127.0.0.1").strip().lower()
    try:
        bind_is_loopback = bind_host == "localhost" or ipaddress.ip_address(bind_host).is_loopback
    except ValueError:
        bind_is_loopback = False
    origins = os.environ.get("SENTINEL_CONSOLE_ALLOWED_BROWSER_ORIGINS", "")
    origin_values = tuple(value.strip() for value in origins.split(",") if value.strip())
    if not bind_is_loopback or not origin_values:
        raise RuntimeError(
            "insecure browser cookies require a loopback bind and explicit loopback origins"
        )
    for value in origin_values:
        try:
            origin = urlsplit(value)
            host = (origin.hostname or "").lower()
            host_is_loopback = host == "localhost" or ipaddress.ip_address(host).is_loopback
        except ValueError:
            host_is_loopback = False
            origin = None
        if (
            origin is None
            or origin.scheme.lower() != "http"
            or not host_is_loopback
            or origin.username is not None
            or origin.password is not None
            or origin.path not in {"", "/"}
            or origin.query
            or origin.fragment
        ):
            raise RuntimeError(
                "insecure browser cookies require HTTP origins on localhost or loopback IPs"
            )
    return "sentinel_session", "sentinel_csrf", False


SESSION_COOKIE_NAME, CSRF_COOKIE_NAME, SECURE_COOKIES = _cookie_policy()
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

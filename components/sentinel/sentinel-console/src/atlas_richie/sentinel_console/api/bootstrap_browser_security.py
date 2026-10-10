"""Browser CSRF proof for bootstrap-operator-only mutation/check routes."""

from __future__ import annotations

import hmac
import re
from collections.abc import Collection

from starlette.requests import Request

from .browser_origin import normalize_browser_origin
from .browser_security import CSRF_COOKIE_NAME
from .http_support import cookie_count

_OPAQUE_VALUE_PATTERN = re.compile(r"^[A-Za-z0-9_-]{32,256}$")


def has_valid_bootstrap_browser_proof(
    request: Request, allowed_origins: Collection[str]
) -> bool:
    """Require one exact allowed Origin and a matching, unique CSRF nonce."""
    origin_values = request.headers.getlist("origin")
    if len(origin_values) != 1:
        return False
    try:
        origin = normalize_browser_origin(origin_values[0])
    except ValueError:
        return False
    normalized_origins = frozenset(
        normalize_browser_origin(value) for value in allowed_origins
    )
    if origin not in normalized_origins:
        return False

    csrf_values = request.headers.getlist("x-sentinel-csrf")
    csrf_cookie = request.cookies.get(CSRF_COOKIE_NAME)
    return (
        len(csrf_values) == 1
        and cookie_count(request, CSRF_COOKIE_NAME) == 1
        and csrf_cookie is not None
        and _OPAQUE_VALUE_PATTERN.fullmatch(csrf_values[0]) is not None
        and hmac.compare_digest(csrf_values[0], csrf_cookie)
    )

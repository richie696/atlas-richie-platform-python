"""Application use case for the browser's double-submit CSRF nonce."""

from __future__ import annotations

import re
from secrets import token_urlsafe

from ..domain.session import BrowserCsrfNonce

_CSRF_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{32,256}$")


class IssueCsrfNonce:
    """Reuse a valid browser nonce or mint a fresh cryptographically random one."""

    def execute(self, cookie_value: str | None) -> BrowserCsrfNonce:
        """Return an HttpOnly-cookie/header pair; the nonce grants no identity."""
        if cookie_value is not None and _CSRF_TOKEN_PATTERN.fullmatch(cookie_value):
            return BrowserCsrfNonce(cookie_value)
        return BrowserCsrfNonce(token_urlsafe(32))

"""Explicit security policy for outbound OAuth endpoints."""

from __future__ import annotations

from typing import Protocol
from urllib.parse import urlsplit

from .errors import OAuthConfigurationError


class OAuthEndpointPolicy(Protocol):
    """Validate an OAuth endpoint before the component makes a request."""

    def validate(self, endpoint: str) -> None:
        """Raise a portable configuration error when an endpoint is unsafe."""


class HttpsOnlyEndpointPolicy:
    """Public-network default that blocks credential-bearing and fragment URIs."""

    def validate(self, endpoint: str) -> None:
        parsed = urlsplit(endpoint)
        if parsed.scheme.lower() != "https" or not parsed.netloc:
            raise OAuthConfigurationError("OAuth endpoint must use HTTPS and include a host")
        if parsed.username or parsed.password or parsed.fragment:
            raise OAuthConfigurationError("OAuth endpoint must not contain credentials or a fragment")


class AllowHttpEndpointPolicy:
    """Explicit test or trusted-network policy; never the component default."""

    def validate(self, endpoint: str) -> None:
        parsed = urlsplit(endpoint)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
            raise OAuthConfigurationError("OAuth endpoint must be an absolute HTTP(S) URI")
        if parsed.username or parsed.password or parsed.fragment:
            raise OAuthConfigurationError("OAuth endpoint must not contain credentials or a fragment")

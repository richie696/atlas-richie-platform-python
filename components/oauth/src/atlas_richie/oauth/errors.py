"""Portable OAuth failure categories that never carry credentials or tokens."""

from atlas_richie.contracts import PlatformError


class OAuthError(PlatformError):
    """Base class for expected OAuth component failures."""


class OAuthConfigurationError(OAuthError):
    """A caller configured an unsafe or inconsistent OAuth value."""


class OAuthProtocolError(OAuthError):
    """An OAuth peer produced a malformed protocol response."""


class OAuthEndpointError(OAuthError):
    """An OAuth endpoint rejected a request without exposing sensitive body data."""

    def __init__(self, error: str, status_code: int) -> None:
        super().__init__(f"OAuth endpoint rejected the request: {error} (HTTP {status_code})")
        self.error = error
        self.status_code = status_code


class OAuthResourceMismatch(OAuthError):
    """A caller attempted to use a token outside of its bound resource."""


class OAuthTokenValidationError(OAuthError):
    """An access token failed local or remote resource-server validation."""

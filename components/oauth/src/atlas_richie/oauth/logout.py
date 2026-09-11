"""RP-Initiated Logout 1.0 end-session request construction.

The Builder accumulates optional parameters and the terminal `build()`
returns a `LogoutRequest` value object whose `url()` method produces the
final end-session URL with correct percent-encoding.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .errors import OAuthConfigurationError


@dataclass(frozen=True, slots=True)
class LogoutRequest:
    """A constructed RP-Initiated Logout 1.0 end-session request.

    Attributes:
        end_session_endpoint: The IdP's `end_session_endpoint` URL.
        id_token_hint: The ID Token to forward as a hint; required.
        post_logout_redirect_uri: Optional redirect target the IdP
            returns the user to after logout.
        state: Optional opaque value for CSRF defense (RP-Initiated
            Logout 1.0 §2.1 recommends echoing it back).
        ui_locales: Optional BCP47 language tag for the IdP's UI.
    """

    end_session_endpoint: str
    id_token_hint: str
    post_logout_redirect_uri: str | None = None
    state: str | None = None
    ui_locales: str | None = None

    def __post_init__(self) -> None:
        if not self.end_session_endpoint or not self.end_session_endpoint.strip():
            raise OAuthConfigurationError("end_session_endpoint is required")
        if not self.id_token_hint or not self.id_token_hint.strip():
            raise OAuthConfigurationError("id_token_hint is required")
        if self.post_logout_redirect_uri is not None and not self.post_logout_redirect_uri.strip():
            raise OAuthConfigurationError("post_logout_redirect_uri must be non-blank when present")
        if self.state is not None and not self.state.strip():
            raise OAuthConfigurationError("state must be non-blank when present")
        if self.ui_locales is not None and not self.ui_locales.strip():
            raise OAuthConfigurationError("ui_locales must be non-blank when present")

    def url(self) -> str:
        """Return the fully-encoded end-session URL."""
        parsed = urlsplit(self.end_session_endpoint)
        existing = parse_qsl(parsed.query, keep_blank_values=True)
        added: list[tuple[str, str]] = [("id_token_hint", self.id_token_hint)]
        if self.post_logout_redirect_uri is not None:
            added.append(("post_logout_redirect_uri", self.post_logout_redirect_uri))
        if self.state is not None:
            added.append(("state", self.state))
        if self.ui_locales is not None:
            added.append(("ui_locales", self.ui_locales))
        merged = existing + added
        encoded = urlencode(merged)
        return urlunsplit(
            (parsed.scheme, parsed.netloc, parsed.path, encoded, parsed.fragment)
        )


class _RpInitiatedLogoutBuilder:
    """Internal mutable builder; new instances are returned from each setter."""

    def __init__(self, end_session_endpoint: str) -> None:
        self._endpoint = end_session_endpoint
        self._id_token_hint: str | None = None
        self._post_logout_redirect_uri: str | None = None
        self._state: str | None = None
        self._ui_locales: str | None = None

    def _copy(self) -> "_RpInitiatedLogoutBuilder":
        clone = _RpInitiatedLogoutBuilder(self._endpoint)
        clone._id_token_hint = self._id_token_hint
        clone._post_logout_redirect_uri = self._post_logout_redirect_uri
        clone._state = self._state
        clone._ui_locales = self._ui_locales
        return clone

    def id_token_hint(self, value: str) -> "_RpInitiatedLogoutBuilder":
        next = self._copy()
        next._id_token_hint = value
        return next

    def post_logout_redirect_uri(self, value: str) -> "_RpInitiatedLogoutBuilder":
        next = self._copy()
        next._post_logout_redirect_uri = value
        return next

    def state(self, value: str) -> "_RpInitiatedLogoutBuilder":
        next = self._copy()
        next._state = value
        return next

    def ui_locales(self, value: str) -> "_RpInitiatedLogoutBuilder":
        next = self._copy()
        next._ui_locales = value
        return next

    def build(self) -> LogoutRequest:
        return LogoutRequest(
            end_session_endpoint=self._endpoint,
            id_token_hint=self._id_token_hint or "",
            post_logout_redirect_uri=self._post_logout_redirect_uri,
            state=self._state,
            ui_locales=self._ui_locales,
        )


class RpInitiatedLogout:
    """Builder entry point for RP-Initiated Logout 1.0 end-session requests."""

    @staticmethod
    def builder(end_session_endpoint: str) -> _RpInitiatedLogoutBuilder:
        if not end_session_endpoint or not end_session_endpoint.strip():
            raise OAuthConfigurationError("end_session_endpoint is required")
        return _RpInitiatedLogoutBuilder(end_session_endpoint)


__all__ = ["LogoutRequest", "RpInitiatedLogout"]

"""A thread-safe, process-local OAuth token lifecycle facade."""

from __future__ import annotations

from datetime import timedelta
from threading import RLock

from .client import OAuthTokenRequester
from .errors import OAuthResourceMismatch
from .models import OAuthAccessToken, OAuthClientCredentials, OAuthTokenResponse, ResourceIndicator


class OAuthTokenManager:
    """Reuse or refresh one resource-bound token without leaking token state globally."""

    CLOCK_SKEW = timedelta(seconds=30)

    def __init__(
        self,
        requester: OAuthTokenRequester,
        *,
        token_endpoint: str,
        credentials: OAuthClientCredentials,
        resource: ResourceIndicator,
        configured_scopes: frozenset[str] = frozenset(),
    ) -> None:
        self._requester = requester
        self._token_endpoint = token_endpoint
        self._credentials = credentials
        self._resource = resource
        self._configured_scopes = frozenset(configured_scopes)
        self._access_token: OAuthAccessToken | None = None
        self._refresh_token: str | None = None
        self._lock = RLock()

    def accept(self, response: OAuthTokenResponse) -> None:
        """Seed the manager after an interactive authorization-code exchange."""

        with self._lock:
            token = response.token_with_granted_scopes()
            if token.resource is not None and token.resource != self._resource:
                raise OAuthResourceMismatch("cannot accept a token bound to another resource")
            self._access_token = token
            if response.refresh_token is not None:
                self._refresh_token = response.refresh_token

    def token_for(self, resource: ResourceIndicator, required_scopes: frozenset[str] = frozenset()) -> OAuthAccessToken:
        """Return a usable exact-resource token, refreshing under a single process lock."""

        if resource != self._resource:
            raise OAuthResourceMismatch("requested resource does not match this token manager")
        requested_scopes = self._configured_scopes | frozenset(required_scopes)
        with self._lock:
            if self._usable(requested_scopes):
                return self._access_token  # type: ignore[return-value]
            response = self._refresh(requested_scopes)
            self._access_token = response.token_with_granted_scopes()
            if response.refresh_token is not None:
                self._refresh_token = response.refresh_token
            return self._access_token

    def _usable(self, scopes: frozenset[str]) -> bool:
        return self._access_token is not None and not self._access_token.expired(self.CLOCK_SKEW) and self._access_token.supports(scopes)

    def _refresh(self, scopes: frozenset[str]) -> OAuthTokenResponse:
        if self._refresh_token is not None:
            return self._requester.refresh_token(
                self._token_endpoint,
                self._credentials,
                self._refresh_token,
                self._resource,
                scopes,
            )
        return self._requester.client_credentials(
            self._token_endpoint,
            self._credentials,
            self._resource,
            scopes,
        )

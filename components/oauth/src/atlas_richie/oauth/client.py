"""OAuth token and introspection facades built only on Atlas Richie's HTTP client."""

from __future__ import annotations

from base64 import b64encode
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from atlas_richie.http import HttpClient, HttpRequest

from .errors import OAuthEndpointError, OAuthProtocolError
from .dpop import DpopProofFactory
from .models import (
    OAuthAccessToken,
    OAuthClientRegistration,
    OAuthClientCredentials,
    OAuthDeviceAuthorization,
    OAuthIntrospectionResult,
    OAuthTokenResponse,
    OidcUserInfo,
    ResourceIndicator,
)
from .policy import HttpsOnlyEndpointPolicy, OAuthEndpointPolicy
from .pkce import PkceS256

_ACCEPT_HEADER = "Accept"
_AUTHORIZATION_HEADER = "Authorization"
_DPOP_HEADER = "DPoP"
_CONTENT_TYPE_HEADER = "Content-Type"
_JSON_MEDIA_TYPE = "application/json"
_FORM_MEDIA_TYPE = "application/x-www-form-urlencoded"
_BASIC_SCHEME = "Basic"
_BEARER_SCHEME = "Bearer"
_CLIENT_CREDENTIALS_GRANT = "client_credentials"
_AUTHORIZATION_CODE_GRANT = "authorization_code"
_REFRESH_TOKEN_GRANT = "refresh_token"
_DEVICE_CODE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"
_DEFAULT_TOKEN_LIFETIME_SECONDS = 3600
_DEFAULT_DEVICE_POLL_INTERVAL_SECONDS = 5
_NO_EXPIRY_EPOCH = 0
_REGISTRATION_SECRET_FIELDS = frozenset({"client_secret", "registration_access_token"})


class OAuthTokenRequester(Protocol):
    """Port used by the token manager; implementations can be local test doubles."""

    def client_credentials(
        self,
        endpoint: str,
        credentials: OAuthClientCredentials,
        resource: ResourceIndicator,
        scopes: frozenset[str],
    ) -> OAuthTokenResponse:
        """Obtain a resource-bound client credentials token."""

    def refresh_token(
        self,
        endpoint: str,
        credentials: OAuthClientCredentials,
        refresh_token: str,
        resource: ResourceIndicator,
        scopes: frozenset[str],
    ) -> OAuthTokenResponse:
        """Refresh an existing OAuth grant."""


class IntrospectionClient(Protocol):
    """Port for opaque-token validation without exposing an HTTP library."""

    def introspect(self, endpoint: str, credentials: OAuthClientCredentials, token: str) -> OAuthIntrospectionResult:
        """Return a normalized RFC 7662 token state."""


class OAuthTokenClient(OAuthTokenRequester, IntrospectionClient):
    """A framework-neutral OAuth form client with fixed safe error handling."""

    def __init__(self, http_client: HttpClient, endpoint_policy: OAuthEndpointPolicy | None = None, *, dpop_proof_factory: DpopProofFactory | None = None) -> None:
        self._http_client = http_client
        self._endpoint_policy = endpoint_policy or HttpsOnlyEndpointPolicy()
        self._dpop_proof_factory = dpop_proof_factory

    def client_credentials(
        self,
        endpoint: str,
        credentials: OAuthClientCredentials,
        resource: ResourceIndicator,
        scopes: frozenset[str],
    ) -> OAuthTokenResponse:
        if credentials.client_secret is None:
            raise ValueError("client_credentials requires a confidential client secret")
        return self._token(
            endpoint,
            credentials,
            {
                "grant_type": _CLIENT_CREDENTIALS_GRANT,
                "client_id": credentials.client_id,
                "resource": resource.value,
                "scope": " ".join(sorted(scopes)),
            },
            resource,
            scopes,
        )

    def authorization_code(
        self,
        endpoint: str,
        credentials: OAuthClientCredentials,
        *,
        code: str,
        redirect_uri: str,
        code_verifier: str,
        resource: ResourceIndicator,
        scopes: frozenset[str] = frozenset(),
    ) -> OAuthTokenResponse:
        if not code or not redirect_uri or not code_verifier:
            raise ValueError("code, redirect_uri, and code_verifier are required")
        PkceS256.challenge(code_verifier)
        return self._token(
            endpoint,
            credentials,
            {
                "grant_type": _AUTHORIZATION_CODE_GRANT,
                "client_id": credentials.client_id,
                "code": code,
                "redirect_uri": redirect_uri,
                "code_verifier": code_verifier,
                "resource": resource.value,
                "scope": " ".join(sorted(scopes)),
            },
            resource,
            scopes,
        )

    def refresh_token(
        self,
        endpoint: str,
        credentials: OAuthClientCredentials,
        refresh_token: str,
        resource: ResourceIndicator,
        scopes: frozenset[str],
    ) -> OAuthTokenResponse:
        if not refresh_token:
            raise ValueError("refresh_token is required")
        return self._token(
            endpoint,
            credentials,
            {
                "grant_type": _REFRESH_TOKEN_GRANT,
                "client_id": credentials.client_id,
                "refresh_token": refresh_token,
                "resource": resource.value,
                "scope": " ".join(sorted(scopes)),
            },
            resource,
            scopes,
        )

    def introspect(self, endpoint: str, credentials: OAuthClientCredentials, token: str) -> OAuthIntrospectionResult:
        if not token:
            raise ValueError("token is required")
        if credentials.client_secret is None:
            raise ValueError("introspection requires a confidential client secret")
        raw = self._post_form(endpoint, credentials, {"token": token})
        return OAuthIntrospectionResult(
            active=raw.get("active") is True,
            subject=_optional_string(raw, "sub"),
            client_id=_optional_string(raw, "client_id"),
            issuer=_optional_string(raw, "iss"),
            audience=_audience(raw.get("aud")),
            scopes=_scopes(raw.get("scope")),
            expires_at=_epoch(raw.get("exp")),
            token_id=_optional_string(raw, "jti"),
            claims=raw,
        )

    def device_authorization(
        self,
        endpoint: str,
        credentials: OAuthClientCredentials,
        *,
        resource: ResourceIndicator | None = None,
        scopes: frozenset[str] = frozenset(),
    ) -> OAuthDeviceAuthorization:
        """Start RFC 8628 device authorization; applications own user interaction and scheduling."""

        form = {"client_id": credentials.client_id, "scope": " ".join(sorted(scopes))}
        if resource is not None:
            form["resource"] = resource.value
        raw = self._post_form(endpoint, credentials, form)
        expires_in = _positive_seconds(raw, "expires_in")
        interval = _optional_positive_seconds(raw, "interval") or _DEFAULT_DEVICE_POLL_INTERVAL_SECONDS
        return OAuthDeviceAuthorization(
            device_code=_required_string(raw, "device_code"),
            user_code=_required_string(raw, "user_code"),
            verification_uri=_required_string(raw, "verification_uri"),
            verification_uri_complete=_optional_string(raw, "verification_uri_complete"),
            expires_at=datetime.now(UTC) + timedelta(seconds=expires_in),
            interval_seconds=interval,
        )

    def device_code(
        self,
        endpoint: str,
        credentials: OAuthClientCredentials,
        *,
        device_code: str,
        resource: ResourceIndicator,
        scopes: frozenset[str] = frozenset(),
    ) -> OAuthTokenResponse:
        """Perform one device-code token attempt; the caller schedules retries explicitly."""

        if not device_code:
            raise ValueError("device_code is required")
        return self._token(
            endpoint,
            credentials,
            {
                "grant_type": _DEVICE_CODE_GRANT,
                "device_code": device_code,
                "client_id": credentials.client_id,
                "resource": resource.value,
                "scope": " ".join(sorted(scopes)),
            },
            resource,
            scopes,
        )

    def revoke(
        self,
        endpoint: str,
        credentials: OAuthClientCredentials,
        *,
        token: str,
        token_type_hint: str | None = None,
    ) -> None:
        """Call RFC 7009 revocation without retaining or echoing token material."""

        if not token:
            raise ValueError("token is required")
        form = {"token": token}
        if token_type_hint is not None:
            form["token_type_hint"] = token_type_hint
        self._post_without_body(endpoint, credentials, form)

    def register_client(
        self,
        endpoint: str,
        metadata: Mapping[str, Any],
        *,
        initial_access_token: str | None = None,
    ) -> OAuthClientRegistration:
        """Register against a remote RFC 7591 endpoint; this component never acts as that endpoint."""

        self._endpoint_policy.validate(endpoint)
        headers = {_ACCEPT_HEADER: _JSON_MEDIA_TYPE}
        if initial_access_token is not None:
            if not initial_access_token:
                raise ValueError("initial_access_token must be non-blank when present")
            headers[_AUTHORIZATION_HEADER] = f"{_BEARER_SCHEME} {initial_access_token}"
        response = self._http_client.execute(HttpRequest.post(endpoint).with_headers(headers).with_json(dict(metadata)))
        raw = _response_json(response.json())
        if not response.is_success:
            raise OAuthEndpointError(_safe_error_code(raw.get("error")), response.status_code)
        return OAuthClientRegistration(
            client_id=_required_string(raw, "client_id"),
            client_secret=_optional_string(raw, "client_secret"),
            registration_access_token=_optional_string(raw, "registration_access_token"),
            client_id_issued_at=_optional_epoch(raw.get("client_id_issued_at")),
            client_secret_expires_at=_optional_expiry_epoch(raw.get("client_secret_expires_at")),
            metadata={name: value for name, value in raw.items() if name not in _REGISTRATION_SECRET_FIELDS},
        )

    def user_info(self, endpoint: str, access_token: OAuthAccessToken) -> OidcUserInfo:
        """Retrieve a remote OIDC UserInfo document using its resource-bound access token."""

        self._endpoint_policy.validate(endpoint)
        response = self._http_client.execute(
            HttpRequest.get(endpoint, headers={
                _ACCEPT_HEADER: _JSON_MEDIA_TYPE,
                _AUTHORIZATION_HEADER: access_token.authorization_header(),
            })
        )
        raw = _response_json(response.json())
        if not response.is_success:
            raise OAuthEndpointError(_safe_error_code(raw.get("error")), response.status_code)
        return OidcUserInfo(subject=_required_string(raw, "sub"), claims=raw)

    def _token(
        self,
        endpoint: str,
        credentials: OAuthClientCredentials,
        form: Mapping[str, str],
        resource: ResourceIndicator,
        requested_scopes: frozenset[str],
    ) -> OAuthTokenResponse:
        raw = self._post_form(endpoint, credentials, form)
        value = _required_string(raw, "access_token")
        expires_in = raw.get("expires_in", _DEFAULT_TOKEN_LIFETIME_SECONDS)
        if isinstance(expires_in, bool) or not isinstance(expires_in, int | float) or expires_in <= 0:
            raise OAuthProtocolError("token response expires_in must be a positive number")
        granted = _scopes(raw.get("scope")) or requested_scopes
        return OAuthTokenResponse(
            access_token=OAuthAccessToken(
                value=value,
                token_type=_optional_string(raw, "token_type") or _BEARER_SCHEME,
                expires_at=datetime.now(UTC) + timedelta(seconds=expires_in),
                scopes=granted,
                resource=resource,
            ),
            refresh_token=_optional_string(raw, "refresh_token"),
            granted_scopes=granted,
        )

    def _post_form(self, endpoint: str, credentials: OAuthClientCredentials, form: Mapping[str, str]) -> Mapping[str, Any]:
        self._endpoint_policy.validate(endpoint)
        headers = {
            _ACCEPT_HEADER: _JSON_MEDIA_TYPE,
            _CONTENT_TYPE_HEADER: _FORM_MEDIA_TYPE,
        }
        if self._dpop_proof_factory is not None:
            headers[_DPOP_HEADER] = self._dpop_proof_factory.create(method="POST", target_uri=endpoint)
        if credentials.client_secret is not None:
            basic = b64encode(f"{credentials.client_id}:{credentials.client_secret}".encode("utf-8")).decode("ascii")
            headers[_AUTHORIZATION_HEADER] = f"{_BASIC_SCHEME} {basic}"
        response = self._http_client.execute(HttpRequest.post(endpoint).with_headers(headers).with_form(_non_empty_form(form)))
        raw = _response_json(response.json())
        if not response.is_success:
            error = _safe_error_code(raw.get("error"))
            raise OAuthEndpointError(error, response.status_code)
        return raw

    def _post_without_body(self, endpoint: str, credentials: OAuthClientCredentials, form: Mapping[str, str]) -> None:
        self._endpoint_policy.validate(endpoint)
        headers = {_CONTENT_TYPE_HEADER: _FORM_MEDIA_TYPE}
        if self._dpop_proof_factory is not None:
            headers[_DPOP_HEADER] = self._dpop_proof_factory.create(method="POST", target_uri=endpoint)
        if credentials.client_secret is not None:
            basic = b64encode(f"{credentials.client_id}:{credentials.client_secret}".encode("utf-8")).decode("ascii")
            headers[_AUTHORIZATION_HEADER] = f"{_BASIC_SCHEME} {basic}"
        response = self._http_client.execute(HttpRequest.post(endpoint).with_headers(headers).with_form(_non_empty_form(form)))
        if not response.is_success:
            try:
                raw = _response_json(response.json())
            except Exception:
                raw = {}
            raise OAuthEndpointError(_safe_error_code(raw.get("error")), response.status_code)


def _response_json(value: object) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise OAuthProtocolError("OAuth endpoint response must be a JSON object")
    return value


def _safe_error_code(value: object) -> str:
    """Expose only registered OAuth error codes; endpoint values are untrusted."""

    known = frozenset(
        {
            "invalid_request",
            "invalid_client",
            "invalid_grant",
            "invalid_scope",
            "unauthorized_client",
            "unsupported_grant_type",
            "access_denied",
            "temporarily_unavailable",
            "server_error",
        }
    )
    return value if value in known else "oauth_endpoint_error"


def _required_string(raw: Mapping[str, Any], field: str) -> str:
    value = _optional_string(raw, field)
    if value is None:
        raise OAuthProtocolError(f"OAuth response is missing {field}")
    return value


def _optional_string(raw: Mapping[str, Any], field: str) -> str | None:
    value = raw.get(field)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise OAuthProtocolError(f"OAuth response field {field} must be a non-blank string")
    return value


def _scopes(value: object) -> frozenset[str]:
    if value is None:
        return frozenset()
    if not isinstance(value, str):
        raise OAuthProtocolError("OAuth scope must be a space-delimited string")
    return frozenset(scope for scope in value.split() if scope)


def _audience(value: object) -> frozenset[str]:
    if isinstance(value, str):
        return frozenset({value})
    if isinstance(value, list) and all(isinstance(item, str) and item for item in value):
        return frozenset(value)
    return frozenset()


def _epoch(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise OAuthProtocolError("OAuth exp must be a numeric epoch value")
    return datetime.fromtimestamp(value, UTC)


def _optional_epoch(value: object) -> datetime | None:
    return None if value is None else _epoch(value)


def _optional_expiry_epoch(value: object) -> datetime | None:
    if value == _NO_EXPIRY_EPOCH:
        return None
    return _optional_epoch(value)


def _positive_seconds(raw: Mapping[str, Any], field: str) -> int:
    value = raw.get(field)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise OAuthProtocolError(f"OAuth response field {field} must be a positive integer")
    return value


def _optional_positive_seconds(raw: Mapping[str, Any], field: str) -> int | None:
    return None if field not in raw else _positive_seconds(raw, field)


def _non_empty_form(form: Mapping[str, str]) -> dict[str, str]:
    return {name: value for name, value in form.items() if value != ""}

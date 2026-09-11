"""Immutable OAuth protocol values with no framework or JOSE-library types."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from types import MappingProxyType
from typing import Any, Mapping
from urllib.parse import urlsplit

from .errors import OAuthConfigurationError


def _freeze_strings(values: frozenset[str] | set[str] | tuple[str, ...] | list[str] | None) -> frozenset[str]:
    result = frozenset(value.strip() for value in (values or ()) if isinstance(value, str) and value.strip())
    if len(result) != len(tuple(values or ())):
        raise OAuthConfigurationError("OAuth string collections must contain non-blank strings")
    return result


def _freeze_mapping(values: Mapping[str, Any] | None) -> Mapping[str, Any]:
    return MappingProxyType(dict(values or {}))


@dataclass(frozen=True, slots=True)
class ResourceIndicator:
    """An RFC 8707 resource identifier, retained for exact token isolation."""

    value: str

    def __post_init__(self) -> None:
        parsed = urlsplit(self.value)
        if not parsed.scheme or not parsed.netloc or parsed.username or parsed.password or parsed.fragment:
            raise OAuthConfigurationError("resource must be an absolute URI without credentials or fragment")


@dataclass(frozen=True, slots=True)
class OAuthClientCredentials:
    """Client identity; a public authorization-code client has no secret."""

    client_id: str
    client_secret: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if not self.client_id.strip() or self.client_secret == "":
            raise OAuthConfigurationError("client_id is required and client_secret cannot be blank")


@dataclass(frozen=True, slots=True)
class OAuthAccessToken:
    """Process-local access-token snapshot; token material is not printable."""

    value: str = field(repr=False)
    expires_at: datetime | None = None
    token_type: str = "Bearer"
    scopes: frozenset[str] = field(default_factory=frozenset)
    resource: ResourceIndicator | None = None
    issuer: str | None = None

    def __post_init__(self) -> None:
        if not self.value.strip():
            raise OAuthConfigurationError("access token must not be blank")
        if not self.token_type.strip():
            raise OAuthConfigurationError("token_type must not be blank")
        object.__setattr__(self, "scopes", _freeze_strings(self.scopes))
        if self.expires_at is not None:
            expiry = self.expires_at if self.expires_at.tzinfo else self.expires_at.replace(tzinfo=UTC)
            object.__setattr__(self, "expires_at", expiry.astimezone(UTC))

    def expired(self, clock_skew: timedelta = timedelta()) -> bool:
        return self.expires_at is not None and self.expires_at <= datetime.now(UTC) + clock_skew

    def authorization_header(self) -> str:
        return f"{self.token_type} {self.value}"

    def supports(self, required_scopes: frozenset[str]) -> bool:
        return self.scopes.issuperset(required_scopes)


@dataclass(frozen=True, slots=True)
class OAuthTokenResponse:
    """A token endpoint response with optional unprintable refresh-token material."""

    access_token: OAuthAccessToken
    refresh_token: str | None = field(default=None, repr=False)
    granted_scopes: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        object.__setattr__(self, "granted_scopes", _freeze_strings(self.granted_scopes))
        if self.refresh_token is not None and not self.refresh_token.strip():
            raise OAuthConfigurationError("refresh_token must be non-blank when present")

    def token_with_granted_scopes(self) -> OAuthAccessToken:
        if not self.granted_scopes:
            return self.access_token
        return OAuthAccessToken(
            value=self.access_token.value,
            expires_at=self.access_token.expires_at,
            token_type=self.access_token.token_type,
            scopes=self.granted_scopes,
            resource=self.access_token.resource,
            issuer=self.access_token.issuer,
        )


@dataclass(frozen=True, slots=True)
class OAuthDeviceAuthorization:
    """A device-flow authorization response; device_code material is never repr-visible."""

    device_code: str = field(repr=False)
    user_code: str
    verification_uri: str
    expires_at: datetime
    interval_seconds: int
    verification_uri_complete: str | None = None

    def __post_init__(self) -> None:
        if not self.device_code or not self.user_code or not self.verification_uri:
            raise OAuthConfigurationError("device authorization requires device_code, user_code, and verification_uri")
        if self.interval_seconds <= 0:
            raise OAuthConfigurationError("device authorization interval_seconds must be positive")
        expiry = self.expires_at if self.expires_at.tzinfo else self.expires_at.replace(tzinfo=UTC)
        object.__setattr__(self, "expires_at", expiry.astimezone(UTC))

    def expired(self) -> bool:
        return self.expires_at <= datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class OAuthClientRegistration:
    """Client material returned by a remote dynamic-registration endpoint."""

    client_id: str
    client_secret: str | None = field(default=None, repr=False)
    registration_access_token: str | None = field(default=None, repr=False)
    client_id_issued_at: datetime | None = None
    client_secret_expires_at: datetime | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.client_id.strip():
            raise OAuthConfigurationError("dynamic registration response requires client_id")
        for field_name in ("client_secret", "registration_access_token"):
            value = getattr(self, field_name)
            if value is not None and not value.strip():
                raise OAuthConfigurationError(f"{field_name} must be non-blank when present")
        object.__setattr__(self, "metadata", _freeze_mapping(self.metadata))
        for field_name in ("client_id_issued_at", "client_secret_expires_at"):
            value = getattr(self, field_name)
            if value is not None:
                normalized = value if value.tzinfo else value.replace(tzinfo=UTC)
                object.__setattr__(self, field_name, normalized.astimezone(UTC))


@dataclass(frozen=True, slots=True)
class OidcUserInfo:
    """Validated-shape OpenID Connect UserInfo response with extension claims retained."""

    subject: str
    claims: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.subject.strip():
            raise OAuthConfigurationError("OIDC UserInfo response requires sub")
        object.__setattr__(self, "claims", _freeze_mapping(self.claims))


@dataclass(frozen=True, slots=True)
class OAuthAuthorizationServerMetadata:
    """The component-consumed subset of RFC 8414 authorization-server metadata."""

    issuer: str
    authorization_endpoint: str | None
    token_endpoint: str | None
    jwks_uri: str | None
    introspection_endpoint: str | None = None
    revocation_endpoint: str | None = None
    registration_endpoint: str | None = None
    grant_types_supported: frozenset[str] = field(default_factory=frozenset)
    code_challenge_methods_supported: frozenset[str] = field(default_factory=frozenset)
    scopes_supported: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        if not self.issuer.strip():
            raise OAuthConfigurationError("metadata issuer is required")
        object.__setattr__(self, "grant_types_supported", _freeze_strings(self.grant_types_supported))
        object.__setattr__(self, "code_challenge_methods_supported", _freeze_strings(self.code_challenge_methods_supported))
        object.__setattr__(self, "scopes_supported", _freeze_strings(self.scopes_supported))


@dataclass(frozen=True, slots=True)
class OAuthProtectedResourceMetadata:
    """RFC 9728 protected-resource metadata without transport-specific response objects."""

    resource: ResourceIndicator
    authorization_servers: tuple[str, ...] = ()
    scopes_supported: frozenset[str] = field(default_factory=frozenset)
    extensions: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "authorization_servers", tuple(self.authorization_servers))
        object.__setattr__(self, "scopes_supported", _freeze_strings(self.scopes_supported))
        object.__setattr__(self, "extensions", _freeze_mapping(self.extensions))


@dataclass(frozen=True, slots=True)
class OAuthIntrospectionResult:
    """Normalized RFC 7662 response used by opaque-token and hybrid validation."""

    active: bool
    subject: str | None = None
    client_id: str | None = None
    issuer: str | None = None
    audience: frozenset[str] = field(default_factory=frozenset)
    scopes: frozenset[str] = field(default_factory=frozenset)
    expires_at: datetime | None = None
    token_id: str | None = None
    claims: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "audience", _freeze_strings(self.audience))
        object.__setattr__(self, "scopes", _freeze_strings(self.scopes))
        object.__setattr__(self, "claims", _freeze_mapping(self.claims))
        if self.expires_at is not None:
            expiry = self.expires_at if self.expires_at.tzinfo else self.expires_at.replace(tzinfo=UTC)
            object.__setattr__(self, "expires_at", expiry.astimezone(UTC))


@dataclass(frozen=True, slots=True)
class AuthenticatedPrincipal:
    """Framework-neutral result of resource-server authentication."""

    subject: str
    client_id: str | None
    issuer: str
    audience: frozenset[str]
    scopes: frozenset[str]
    expires_at: datetime | None
    token_id: str | None = None
    claims: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.subject.strip() or not self.issuer.strip():
            raise OAuthConfigurationError("authenticated principal requires subject and issuer")
        object.__setattr__(self, "audience", _freeze_strings(self.audience))
        object.__setattr__(self, "scopes", _freeze_strings(self.scopes))
        object.__setattr__(self, "claims", _freeze_mapping(self.claims))

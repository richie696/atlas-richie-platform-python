"""Framework-neutral OAuth 2.1 client and resource-server contracts."""

from .client import IntrospectionClient, OAuthTokenClient, OAuthTokenRequester
from .dpop import DpopProofClaims, DpopProofFactory, DpopProofVerifier, DpopReplayStore, DpopValidationPolicy, InMemoryDpopReplayStore, access_token_hash, canonical_dpop_uri
from .errors import (
    OAuthConfigurationError,
    OAuthEndpointError,
    OAuthError,
    OAuthProtocolError,
    OAuthResourceMismatch,
    OAuthTokenValidationError,
)
from .id_token import IdTokenValidator, code_hash
from .logout import LogoutRequest, RpInitiatedLogout
from .metadata import HttpJwkSetSource, JwkSetSource, OAuthMetadataClient
from .models import (
    AuthenticatedPrincipal,
    OAuthAccessToken,
    OAuthAuthorizationServerMetadata,
    OAuthClientRegistration,
    OAuthClientCredentials,
    OAuthDeviceAuthorization,
    OAuthIntrospectionResult,
    OAuthProtectedResourceMetadata,
    OAuthTokenResponse,
    OidcUserInfo,
    ResourceIndicator,
)
from .pkce import PkcePair, PkceS256
from .policy import AllowHttpEndpointPolicy, HttpsOnlyEndpointPolicy, OAuthEndpointPolicy
from .resource import ResourceServerAuthenticator, TokenValidator
from .token_manager import OAuthTokenManager

__all__ = [
    "AllowHttpEndpointPolicy",
    "AuthenticatedPrincipal",
    "DpopProofClaims",
    "DpopProofFactory",
    "DpopProofVerifier",
    "DpopReplayStore",
    "DpopValidationPolicy",
    "HttpJwkSetSource",
    "HttpsOnlyEndpointPolicy",
    "IdTokenValidator",
    "InMemoryDpopReplayStore",
    "IntrospectionClient",
    "JwkSetSource",
    "LogoutRequest",
    "OAuthAccessToken",
    "OAuthAuthorizationServerMetadata",
    "OAuthClientRegistration",
    "OAuthClientCredentials",
    "OAuthDeviceAuthorization",
    "OAuthConfigurationError",
    "OAuthEndpointError",
    "OAuthEndpointPolicy",
    "OAuthError",
    "OAuthIntrospectionResult",
    "OAuthMetadataClient",
    "OAuthProtectedResourceMetadata",
    "OAuthProtocolError",
    "OAuthResourceMismatch",
    "OAuthTokenClient",
    "OAuthTokenManager",
    "OAuthTokenRequester",
    "OAuthTokenResponse",
    "OAuthTokenValidationError",
    "OidcUserInfo",
    "PkcePair",
    "PkceS256",
    "ResourceIndicator",
    "ResourceServerAuthenticator",
    "RpInitiatedLogout",
    "TokenValidator",
    "access_token_hash",
    "canonical_dpop_uri",
    "code_hash",
]

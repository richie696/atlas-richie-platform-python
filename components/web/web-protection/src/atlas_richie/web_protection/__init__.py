"""Framework-neutral request protection algorithms.

Zero runtime dependencies. Servlet/ASGI plumbing, response rendering and shared
storage are adapter concerns; this package only decides allow/deny.
"""

import importlib.metadata

from .idempotency import (
    IdempotencyDecision,
    IdempotencyGuard,
    IdempotencyStore,
    InMemoryIdempotencyStore,
    LongLivedPathBypass,
)
from .rate_limit import (
    ClientKeyResolver,
    CompositeKeyResolver,
    HeaderClientKeyResolver,
    IpClientKeyResolver,
    RateLimitDecision,
    RateLimitGuard,
    RateLimitProperties,
    RateLimitRoute,
    RateLimiter,
    ant_pattern_to_regex,
)
from .guards import (
    HEADER_NONCE,
    HEADER_SIGNATURE,
    HEADER_TIMESTAMP,
    ApiSignatureVerifier,
    RequestContext,
    RequestSizeDecision,
    RequestSizeGuard,
    SecretKeyProvider,
    SignatureDecision,
    canonicalize,
    hmac_sha256_hex,
)
from .matchers import BotUserAgentMatcher, IpBlacklistEntry, glob_to_regex
from .trackers import LoginAttemptTracker, NonceCache

__version__ = importlib.metadata.version("atlas-richie-web-protection")

__all__ = [
    "ClientKeyResolver",
    "IdempotencyDecision",
    "IdempotencyGuard",
    "IdempotencyStore",
    "InMemoryIdempotencyStore",
    "LongLivedPathBypass",
    "CompositeKeyResolver",
    "HeaderClientKeyResolver",
    "IpClientKeyResolver",
    "RateLimitDecision",
    "RateLimitGuard",
    "RateLimitProperties",
    "RateLimitRoute",
    "RateLimiter",
    "ant_pattern_to_regex",
    "HEADER_NONCE",
    "HEADER_SIGNATURE",
    "HEADER_TIMESTAMP",
    "ApiSignatureVerifier",
    "BotUserAgentMatcher",
    "IpBlacklistEntry",
    "LoginAttemptTracker",
    "NonceCache",
    "RequestContext",
    "RequestSizeDecision",
    "RequestSizeGuard",
    "SecretKeyProvider",
    "SignatureDecision",
    "__version__",
    "canonicalize",
    "glob_to_regex",
    "hmac_sha256_hex",
]

"""Framework-neutral request protection algorithms.

Zero runtime dependencies. Servlet/ASGI plumbing, response rendering and shared
storage are adapter concerns; this package only decides allow/deny.

`atlas_richie.web_protection.spi` —— 跨容器决策的统一编程面：请求上下文、决策事件、拦截器与拦截器链。
`atlas_richie.web_protection.interceptors` —— 把各个 guard 包装成 SPI 拦截器的适配层。
`atlas_richie.web_protection.tracing` —— trace ID 归一化（traceparent / X-Request-Id）。
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
from .spi import (
    CLIENT_IP_ATTRIBUTE,
    DECISION_ATTRIBUTE,
    GATEWAY_BYPASS_ATTRIBUTE,
    GATEWAY_ID_ATTRIBUTE,
    LOGIN_KEY_ATTRIBUTE,
    LONG_LIVED_ATTRIBUTE,
    DefaultWebInterceptorChain,
    MutableWebRequestContext,
    MutableWebRequestContextBuilder,
    WebDecisionSink,
    WebFilterDecision,
    WebInterceptor,
    WebInterceptorChain,
    WebRequestContext,
)
from .interceptors import (
    BotUserAgentInterceptor,
    GatewayBypassInterceptor,
    IdempotencyInterceptor,
    IpBlacklistInterceptor,
    LoginLockInterceptor,
    LongLivedBypassInterceptor,
    ProtectionInterceptor,
    RateLimitInterceptor,
    RequestSizeInterceptor,
    SignatureInterceptor,
    default_deny_body,
    header_map_from_context,
    is_long_lived,
)
from .tracing import TraceIdInterceptor, TraceIdParser

__version__ = importlib.metadata.version("atlas-richie-web-protection")

__all__ = [
    "CLIENT_IP_ATTRIBUTE",
    "DECISION_ATTRIBUTE",
    "GATEWAY_BYPASS_ATTRIBUTE",
    "GATEWAY_ID_ATTRIBUTE",
    "LOGIN_KEY_ATTRIBUTE",
    "LONG_LIVED_ATTRIBUTE",
    "BotUserAgentInterceptor",
    "BotUserAgentMatcher",
    "ClientKeyResolver",
    "CompositeKeyResolver",
    "DefaultWebInterceptorChain",
    "GatewayBypassInterceptor",
    "HEADER_NONCE",
    "HEADER_SIGNATURE",
    "HEADER_TIMESTAMP",
    "HeaderClientKeyResolver",
    "IdempotencyDecision",
    "IdempotencyGuard",
    "IdempotencyInterceptor",
    "IdempotencyStore",
    "InMemoryIdempotencyStore",
    "IpBlacklistEntry",
    "IpBlacklistInterceptor",
    "IpClientKeyResolver",
    "LoginAttemptTracker",
    "LoginLockInterceptor",
    "LongLivedBypassInterceptor",
    "LongLivedPathBypass",
    "MutableWebRequestContext",
    "MutableWebRequestContextBuilder",
    "NonceCache",
    "ProtectionInterceptor",
    "RateLimitDecision",
    "RateLimitGuard",
    "RateLimitInterceptor",
    "RateLimitProperties",
    "RateLimitRoute",
    "RateLimiter",
    "RequestContext",
    "RequestSizeDecision",
    "RequestSizeGuard",
    "RequestSizeInterceptor",
    "SecretKeyProvider",
    "SignatureDecision",
    "SignatureInterceptor",
    "TraceIdInterceptor",
    "TraceIdParser",
    "WebDecisionSink",
    "WebFilterDecision",
    "WebInterceptor",
    "WebInterceptorChain",
    "WebRequestContext",
    "__version__",
    "ant_pattern_to_regex",
    "canonicalize",
    "default_deny_body",
    "glob_to_regex",
    "header_map_from_context",
    "hmac_sha256_hex",
    "is_long_lived",
]

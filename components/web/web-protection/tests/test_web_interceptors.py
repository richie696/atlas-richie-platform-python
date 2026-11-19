"""guard → SPI 拦截器适配层测试（对位 Java web-core 的 A-4 / B 组拦截器单测）。"""

from __future__ import annotations

import json

import pytest

from atlas_richie.web_protection import (
    ApiSignatureVerifier,
    BotUserAgentMatcher,
    CompositeKeyResolver,
    HeaderClientKeyResolver,
    IdempotencyGuard,
    InMemoryIdempotencyStore,
    IpBlacklistEntry,
    IpClientKeyResolver,
    LongLivedPathBypass,
    LoginAttemptTracker,
    NonceCache,
    RateLimitGuard,
    RateLimitProperties,
    RateLimitRoute,
    RequestSizeGuard,
    canonicalize,
    hmac_sha256_hex,
)
from atlas_richie.web_protection.interceptors import (
    BotUserAgentInterceptor,
    GatewayBypassInterceptor,
    IdempotencyInterceptor,
    IpBlacklistInterceptor,
    LoginLockInterceptor,
    LongLivedBypassInterceptor,
    RateLimitInterceptor,
    RequestSizeInterceptor,
    SignatureInterceptor,
    default_deny_body,
    header_map_from_context,
)
from atlas_richie.web_protection.spi import (
    CLIENT_IP_ATTRIBUTE,
    DECISION_ATTRIBUTE,
    GATEWAY_BYPASS_ATTRIBUTE,
    GATEWAY_ID_ATTRIBUTE,
    LOGIN_KEY_ATTRIBUTE,
    LONG_LIVED_ATTRIBUTE,
    DefaultWebInterceptorChain,
    MutableWebRequestContext,
    WebFilterDecision,
)

pytestmark = pytest.mark.unit

SECRET = b"shared-secret"
NOW_MS = 1_700_000_000_000


class _Sink:
    def __init__(self) -> None:
        self.decisions: list[WebFilterDecision] = []

    def publish(self, decision: WebFilterDecision) -> None:
        self.decisions.append(decision)


class _AllowLimiter:
    def __init__(self, allow: bool = True) -> None:
        self.allow = allow
        self.calls: list[tuple[str, int, int]] = []

    def try_acquire(self, key: str, max_count: int, window_seconds: int) -> bool:
        self.calls.append((key, max_count, window_seconds))
        return self.allow


class _Keys:
    def secret_for(self, client_key: str) -> bytes | None:
        return SECRET if client_key == "partner" else None


def _ctx(path: str = "/", method: str = "GET", headers=None, *, ip=None, login_key=None):
    ctx = MutableWebRequestContext(method, path, headers or {})
    if ip is not None:
        ctx.set_attribute(CLIENT_IP_ATTRIBUTE, ip)
    if login_key is not None:
        ctx.set_attribute(LOGIN_KEY_ATTRIBUTE, login_key)
    return ctx


def _run(interceptors, ctx):
    """跑一条链，返回是否走到了链尾。"""
    reached_end: list[str] = []

    class _Tail:
        def intercept(self, context, chain) -> None:
            reached_end.append("tail")

    DefaultWebInterceptorChain([*interceptors, _Tail()]).proceed(ctx)
    return bool(reached_end)


def _rate_guard(allow: bool = True, route: RateLimitRoute | None = None):
    limiter = _AllowLimiter(allow)
    guard = RateLimitGuard(
        limiter,
        RateLimitProperties(routes=(route or RateLimitRoute("/api/orders", permits_per_second=2),)),
        CompositeKeyResolver(HeaderClientKeyResolver(), IpClientKeyResolver()),
    )
    return guard, limiter


def _verifier():
    return ApiSignatureVerifier(_Keys(), NonceCache(300), 60, clock=lambda: NOW_MS / 1000)


def _signed_headers(path="/api/orders", method="POST", nonce="n-1"):
    signature = hmac_sha256_hex(SECRET, canonicalize(method, path, NOW_MS, nonce))
    return {
        "x-client-key": "partner",
        "x-timestamp": str(NOW_MS),
        "x-nonce": nonce,
        "x-signature": signature,
    }


class TestIpBlacklistInterceptor:
    def test_blacklisted_ip_is_denied(self) -> None:
        ctx = _ctx(ip="203.0.113.9")
        _run([IpBlacklistInterceptor([IpBlacklistEntry("203.0.113.0/24")])], ctx)
        assert ctx.is_short_circuited is True
        assert ctx.response_status == 403
        decision = ctx.attribute(DECISION_ATTRIBUTE)
        assert isinstance(decision, WebFilterDecision)
        assert decision.interceptor == "IpBlacklistInterceptor"
        assert decision.reason == "ip_blacklisted"
        assert decision.status == 403
        assert decision.is_deny is True

    def test_allowed_ip_reaches_the_end_of_the_chain(self) -> None:
        ctx = _ctx(ip="198.51.100.1")
        reached = _run([IpBlacklistInterceptor([IpBlacklistEntry("203.0.113.0/24")])], ctx)
        assert reached is True
        assert ctx.is_short_circuited is False

    def test_deny_body_uses_the_default_renderer(self) -> None:
        ctx = _ctx(ip="203.0.113.9")
        _run([IpBlacklistInterceptor([IpBlacklistEntry("0.0.0.0/0")])], ctx)
        assert json.loads(ctx.short_circuit_body) == {"error": "ip_blacklisted"}


class TestGatewayBypassInterceptor:
    def test_gateway_header_sets_both_attributes(self) -> None:
        ctx = _ctx(headers={"x-forwarded-from-gateway": "edge-1"})
        _run([GatewayBypassInterceptor()], ctx)
        assert ctx.attribute(GATEWAY_BYPASS_ATTRIBUTE) is True
        assert ctx.attribute(GATEWAY_ID_ATTRIBUTE) == "edge-1"

    def test_absent_header_sets_nothing(self) -> None:
        ctx = _ctx()
        _run([GatewayBypassInterceptor()], ctx)
        assert ctx.attribute(GATEWAY_BYPASS_ATTRIBUTE) is None
        assert ctx.attribute(GATEWAY_ID_ATTRIBUTE) is None

    def test_disabled_header_name_never_bypasses(self) -> None:
        ctx = _ctx(headers={"x-forwarded-from-gateway": "edge-1"})
        _run([GatewayBypassInterceptor(None)], ctx)
        assert ctx.attribute(GATEWAY_BYPASS_ATTRIBUTE) is None


class TestLongLivedBypassInterceptor:
    def test_matching_path_sets_the_flag(self) -> None:
        ctx = _ctx("/sse/orders")
        _run([LongLivedBypassInterceptor(LongLivedPathBypass(["/sse/**"]))], ctx)
        assert ctx.attribute(LONG_LIVED_ATTRIBUTE) is True

    def test_non_matching_path_leaves_the_flag_unset(self) -> None:
        ctx = _ctx("/api/orders")
        _run([LongLivedBypassInterceptor(LongLivedPathBypass(["/sse/**"]))], ctx)
        assert ctx.attribute(LONG_LIVED_ATTRIBUTE) is None

    def test_request_level_interceptors_skip_long_lived_paths(self) -> None:
        guard, limiter = _rate_guard(allow=False)
        ctx = _ctx("/sse/orders", headers={"user-agent": "curl/8", "content-length": "999"})
        reached = _run(
            [
                LongLivedBypassInterceptor(LongLivedPathBypass(["/sse/**"])),
                BotUserAgentInterceptor([BotUserAgentMatcher("*curl*")]),
                RequestSizeInterceptor(RequestSizeGuard(100, 10_000)),
                IdempotencyInterceptor(IdempotencyGuard(InMemoryIdempotencyStore(60))),
                RateLimitInterceptor(guard),
                SignatureInterceptor(_verifier()),
            ],
            ctx,
        )
        assert reached is True
        assert ctx.is_short_circuited is False
        assert limiter.calls == []


class TestBotUserAgentInterceptor:
    def test_bot_is_denied(self) -> None:
        ctx = _ctx(headers={"user-agent": "curl/8.4.0"})
        _run([BotUserAgentInterceptor([BotUserAgentMatcher("*curl*")])], ctx)
        assert ctx.response_status == 403
        assert ctx.attribute(DECISION_ATTRIBUTE).reason == "bot_detected"

    def test_normal_agent_passes(self) -> None:
        ctx = _ctx(headers={"user-agent": "Mozilla/5.0"})
        reached = _run([BotUserAgentInterceptor([BotUserAgentMatcher("*curl*")])], ctx)
        assert reached is True


class TestRequestSizeInterceptor:
    def test_oversized_body_is_denied(self) -> None:
        ctx = _ctx(headers={"content-length": "500"})
        _run([RequestSizeInterceptor(RequestSizeGuard(100, 10_000))], ctx)
        assert ctx.response_status == 413
        assert ctx.attribute(DECISION_ATTRIBUTE).reason == "REQUEST_BODY_TOO_LARGE"

    def test_oversized_headers_are_denied(self) -> None:
        ctx = _ctx(headers={"x-long": "a" * 50})
        _run([RequestSizeInterceptor(RequestSizeGuard(1000, 10))], ctx)
        assert ctx.response_status == 431
        assert ctx.attribute(DECISION_ATTRIBUTE).reason == "REQUEST_HEADER_TOO_LARGE"

    def test_all_duplicate_header_values_are_counted(self) -> None:
        """ctx 保留同名 header 的全部值（与 Java collectHeaders 一致）。"""
        ctx = MutableWebRequestContext("GET", "/", {"x-a": ["a" * 40, "b" * 40]})
        _run([RequestSizeInterceptor(RequestSizeGuard(1000, 60))], ctx)
        assert ctx.response_status == 431


class TestLoginLockInterceptor:
    def test_locked_key_is_denied(self) -> None:
        tracker = LoginAttemptTracker(300, 1, 900)
        tracker.record_failure("203.0.113.9")
        ctx = _ctx("/login", login_key="203.0.113.9")
        _run([LoginLockInterceptor(tracker, login_paths=("/login",))], ctx)
        assert ctx.response_status == 429
        assert ctx.attribute(DECISION_ATTRIBUTE).reason == "account_locked"
        assert ctx.attribute(DECISION_ATTRIBUTE).key == "203.0.113.9"

    def test_unlocked_key_passes(self) -> None:
        tracker = LoginAttemptTracker(300, 1, 900)
        ctx = _ctx("/login", login_key="203.0.113.9")
        reached = _run([LoginLockInterceptor(tracker, login_paths=("/login",))], ctx)
        assert reached is True

    def test_non_login_path_is_not_checked(self) -> None:
        tracker = LoginAttemptTracker(300, 1, 900)
        tracker.record_failure("203.0.113.9")
        ctx = _ctx("/other", login_key="203.0.113.9")
        reached = _run([LoginLockInterceptor(tracker, login_paths=("/login",))], ctx)
        assert reached is True

    def test_missing_login_key_is_not_checked(self) -> None:
        tracker = LoginAttemptTracker(300, 1, 900)
        tracker.record_failure("203.0.113.9")
        ctx = _ctx("/login")
        reached = _run([LoginLockInterceptor(tracker, login_paths=("/login",))], ctx)
        assert reached is True


class TestIdempotencyInterceptor:
    def test_replay_is_denied(self) -> None:
        guard = IdempotencyGuard(InMemoryIdempotencyStore(60))
        first = _ctx(headers={"x-idempotency-key": "k1"})
        _run([IdempotencyInterceptor(guard)], first)
        assert first.is_short_circuited is False
        second = _ctx(headers={"x-idempotency-key": "k1"})
        _run([IdempotencyInterceptor(guard)], second)
        assert second.response_status == 409
        assert second.attribute(DECISION_ATTRIBUTE).reason == "idempotent_replay"
        assert second.attribute(DECISION_ATTRIBUTE).key == "k1"

    def test_first_submission_passes(self) -> None:
        guard = IdempotencyGuard(InMemoryIdempotencyStore(60))
        ctx = _ctx(headers={"x-idempotency-key": "k1"})
        reached = _run([IdempotencyInterceptor(guard)], ctx)
        assert reached is True


class TestRateLimitInterceptor:
    def test_rate_limited_request_is_denied_with_code_message_and_headers(self) -> None:
        route = RateLimitRoute(
            "/api/orders",
            deny_code="SLOW_DOWN",
            deny_message="慢一点 (key={key})",
            deny_headers={"Retry-After": "30"},
        )
        guard, _ = _rate_guard(allow=False, route=route)
        ctx = _ctx("/api/orders", "POST", {"x-client-key": "partner-1", "x-forwarded-from-gateway": "e"})
        _run([RateLimitInterceptor(guard)], ctx)
        assert ctx.response_status == 429
        assert json.loads(ctx.short_circuit_body) == {
            "error": "SLOW_DOWN",
            "message": "慢一点 (key=partner-1)",
        }
        assert ctx.response_headers()["Retry-After"] == "30"
        decision = ctx.attribute(DECISION_ATTRIBUTE)
        assert decision.interceptor == "RateLimitInterceptor"
        assert decision.key == "partner-1"
        assert decision.status == 429

    def test_reason_keeps_the_guard_granularity(self) -> None:
        """Java 的 rateLimitDeny 固定 rate_limit.exceeded；Python 保留细分原因。"""
        guard, _ = _rate_guard(allow=False)
        ctx = _ctx("/api/orders", "POST", {"x-client-key": "partner-1"})
        _run([RateLimitInterceptor(guard)], ctx)
        assert ctx.response_status == 401
        assert ctx.attribute(DECISION_ATTRIBUTE).reason == "gateway_identity_missing"

    def test_allowed_request_passes(self) -> None:
        guard, limiter = _rate_guard()
        ctx = _ctx("/api/orders", "POST", {"x-client-key": "partner-1", "x-forwarded-from-gateway": "e"})
        reached = _run([RateLimitInterceptor(guard)], ctx)
        assert reached is True
        assert limiter.calls == [("richie:web:rate-limit:partner-1:/api/orders", 2, 1)]

    def test_unmatched_route_never_touches_the_limiter(self) -> None:
        guard, limiter = _rate_guard()
        ctx = _ctx("/health")
        reached = _run([RateLimitInterceptor(guard)], ctx)
        assert reached is True
        assert limiter.calls == []


class TestSignatureInterceptor:
    def test_missing_signature_is_denied(self) -> None:
        ctx = _ctx("/api/orders", "POST", {"x-client-key": "partner"})
        _run([SignatureInterceptor(_verifier())], ctx)
        assert ctx.response_status == 401
        decision = ctx.attribute(DECISION_ATTRIBUTE)
        assert decision.interceptor == "SignatureInterceptor"
        assert decision.reason == "missing_header"
        assert decision.key == "partner"

    def test_valid_signature_passes(self) -> None:
        ctx = _ctx("/api/orders", "POST", _signed_headers())
        reached = _run([SignatureInterceptor(_verifier())], ctx)
        assert reached is True

    def test_gateway_bypass_skips_verification(self) -> None:
        ctx = _ctx("/api/orders", "POST", {"x-forwarded-from-gateway": "edge-1"})
        _run(
            [
                GatewayBypassInterceptor(),
                SignatureInterceptor(_verifier()),
            ],
            ctx,
        )
        assert ctx.is_short_circuited is False
        assert ctx.attribute(DECISION_ATTRIBUTE) is None

    def test_replayed_nonce_is_denied(self) -> None:
        verifier = _verifier()
        first = _ctx("/api/orders", "POST", _signed_headers())
        _run([SignatureInterceptor(verifier)], first)
        second = _ctx("/api/orders", "POST", _signed_headers())
        _run([SignatureInterceptor(verifier)], second)
        assert second.attribute(DECISION_ATTRIBUTE).reason == "nonce_replay"


class TestDecisionSink:
    def test_deny_publishes_the_decision(self) -> None:
        sink = _Sink()
        ctx = _ctx(ip="203.0.113.9")
        _run([IpBlacklistInterceptor([IpBlacklistEntry("0.0.0.0/0")], decision_sink=sink)], ctx)
        assert len(sink.decisions) == 1
        assert sink.decisions[0].reason == "ip_blacklisted"

    def test_allow_publishes_nothing(self) -> None:
        sink = _Sink()
        ctx = _ctx(ip="198.51.100.1")
        _run([IpBlacklistInterceptor([IpBlacklistEntry("203.0.113.0/24")], decision_sink=sink)], ctx)
        assert sink.decisions == []

    def test_only_the_first_deny_is_published(self) -> None:
        sink = _Sink()
        ctx = _ctx(ip="203.0.113.9", headers={"user-agent": "curl/8"})
        _run(
            [
                IpBlacklistInterceptor([IpBlacklistEntry("0.0.0.0/0")], decision_sink=sink),
                BotUserAgentInterceptor([BotUserAgentMatcher("*")], decision_sink=sink),
            ],
            ctx,
        )
        assert len(sink.decisions) == 1
        assert sink.decisions[0].interceptor == "IpBlacklistInterceptor"


class TestHeaderMapFromContext:
    def test_later_duplicate_wins(self) -> None:
        ctx = MutableWebRequestContext("GET", "/", {"x-a": ["first", "last"]})
        assert header_map_from_context(ctx) == {"x-a": "last"}

    def test_header_names_are_lowercase(self) -> None:
        ctx = MutableWebRequestContext("GET", "/", {"X-A": ["1"]})
        assert header_map_from_context(ctx) == {"x-a": "1"}

    def test_empty_context_yields_an_empty_map(self) -> None:
        assert header_map_from_context(MutableWebRequestContext("GET", "/")) == {}


class TestDefaultDenyBody:
    def test_body_shape(self) -> None:
        assert json.loads(default_deny_body("ip_blacklisted")) == {"error": "ip_blacklisted"}

    def test_reason_is_kept_verbatim(self) -> None:
        assert default_deny_body("REQUEST_BODY_TOO_LARGE") == '{"error": "REQUEST_BODY_TOO_LARGE"}'

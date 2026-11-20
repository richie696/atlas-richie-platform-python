"""ASGI 适配层的链驱动与决策事件测试（SPI 落地到适配层的那一层）。"""

from __future__ import annotations

import asyncio
import json

import pytest

from atlas_richie.web_protection import (
    ApiSignatureVerifier,
    BotUserAgentMatcher,
    CompositeKeyResolver,
    HeaderClientKeyResolver,
    IpBlacklistEntry,
    IpClientKeyResolver,
    LongLivedPathBypass,
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
)
from atlas_richie.web_protection.spi import (
    DefaultWebInterceptorChain,
    MutableWebRequestContext,
    WebFilterDecision,
)
from atlas_richie.web_protection_adapter_asgi import ProtectionASGIMiddleware

pytestmark = pytest.mark.unit

SECRET = b"shared-secret"
NOW_MS = 1_700_000_000_000


class _App:
    def __init__(self, status: int = 200) -> None:
        self.status = status
        self.calls = 0

    async def __call__(self, scope, receive, send) -> None:
        self.calls += 1
        await send({"type": "http.response.start", "status": self.status, "headers": []})
        await send({"type": "http.response.body", "body": b"ok", "more_body": False})


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


def _scope(path="/", method="GET", headers=None, client=("203.0.113.9", 1234), type_="http", query=b""):
    return {
        "type": type_,
        "method": method,
        "path": path,
        "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
        "client": client,
        "query_string": query,
    }


async def _run(middleware, scope):
    sent: list[dict] = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    await middleware(scope, receive, send)
    return sent


def _call(middleware, scope):
    return asyncio.run(_run(middleware, scope))


def _status(sent):
    return next(m["status"] for m in sent if m["type"] == "http.response.start")


def _body(sent):
    return b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")


def _headers(sent):
    start = next(m for m in sent if m["type"] == "http.response.start")
    return {k.decode().lower(): v.decode() for k, v in start["headers"]}


def _rate_guard(allow=True, route=None):
    limiter = _AllowLimiter(allow)
    guard = RateLimitGuard(
        limiter,
        RateLimitProperties(routes=(route or RateLimitRoute("/api/orders", permits_per_second=2),)),
        CompositeKeyResolver(HeaderClientKeyResolver(), IpClientKeyResolver()),
    )
    return guard, limiter


def _rl_headers(**overrides):
    base = {"x-client-key": "partner-1", "x-forwarded-from-gateway": "edge-1"}
    base.update(overrides)
    return base


class TestChainAssembly:
    def test_interceptors_are_exposed_in_execution_order(self) -> None:
        middleware = ProtectionASGIMiddleware(
            _App(),
            ip_blacklist=[IpBlacklistEntry("0.0.0.0/0")],
            bot_matchers=[BotUserAgentMatcher("*")],
            size_guard=RequestSizeGuard(100, 10_000),
            long_lived_bypass=LongLivedPathBypass(["/sse/**"]),
        )
        names = [type(i).__name__ for i in middleware.interceptors]
        assert names == [
            "TraceIdInterceptor",
            "IpBlacklistInterceptor",
            "GatewayBypassInterceptor",
            "LongLivedBypassInterceptor",
            "BotUserAgentInterceptor",
            "RequestSizeInterceptor",
        ]

    def test_no_guard_means_only_the_platform_layers(self) -> None:
        """trace 归一与网关身份是平台级基础设施，始终在链里（都只置标志，从不拒绝）。"""
        names = [type(i).__name__ for i in ProtectionASGIMiddleware(_App()).interceptors]
        assert names == ["TraceIdInterceptor", "GatewayBypassInterceptor"]

    def test_signature_interceptor_is_last(self) -> None:
        middleware = ProtectionASGIMiddleware(
            _App(),
            signature_verifier=ApiSignatureVerifier(_Keys(), NonceCache(300), 60),
            rate_limit_guard=_rate_guard()[0],
        )
        names = [type(i).__name__ for i in middleware.interceptors]
        assert names[-2:] == ["RateLimitInterceptor", "SignatureInterceptor"]


class TestDecisionEvents:
    def test_deny_publishes_a_decision(self) -> None:
        sink = _Sink()
        app = _App()
        middleware = ProtectionASGIMiddleware(
            app, ip_blacklist=[IpBlacklistEntry("0.0.0.0/0")], decision_sink=sink
        )
        _call(middleware, _scope())
        assert len(sink.decisions) == 1
        decision = sink.decisions[0]
        assert decision.interceptor == "IpBlacklistInterceptor"
        assert decision.status == 403
        assert decision.reason == "ip_blacklisted"
        assert decision.is_deny is True
        assert app.calls == 0

    def test_allowed_request_publishes_nothing(self) -> None:
        sink = _Sink()
        middleware = ProtectionASGIMiddleware(
            _App(), ip_blacklist=[IpBlacklistEntry("10.0.0.0/8")], decision_sink=sink
        )
        _call(middleware, _scope())
        assert sink.decisions == []

    def test_long_lived_path_publishes_nothing(self) -> None:
        sink = _Sink()
        app = _App()
        middleware = ProtectionASGIMiddleware(
            app,
            rate_limit_guard=_rate_guard(allow=False)[0],
            long_lived_bypass=LongLivedPathBypass(["/sse/**"]),
            decision_sink=sink,
        )
        _call(middleware, _scope("/sse/orders", "GET", _rl_headers()))
        assert app.calls == 1
        assert sink.decisions == []

    def test_gateway_bypass_publishes_no_signature_decision(self) -> None:
        sink = _Sink()
        middleware = ProtectionASGIMiddleware(
            _App(),
            signature_verifier=ApiSignatureVerifier(_Keys(), NonceCache(300), 60),
            decision_sink=sink,
        )
        _call(middleware, _scope("/api/orders", "POST", {"x-forwarded-from-gateway": "edge-1"}))
        assert sink.decisions == []

    def test_only_the_first_deny_is_published(self) -> None:
        sink = _Sink()
        middleware = ProtectionASGIMiddleware(
            _App(),
            ip_blacklist=[IpBlacklistEntry("0.0.0.0/0")],
            bot_matchers=[BotUserAgentMatcher("*")],
            decision_sink=sink,
        )
        _call(middleware, _scope(headers={"user-agent": "curl/8"}))
        assert len(sink.decisions) == 1
        assert sink.decisions[0].interceptor == "IpBlacklistInterceptor"

    def test_decision_sink_is_optional(self) -> None:
        middleware = ProtectionASGIMiddleware(_App(), ip_blacklist=[IpBlacklistEntry("0.0.0.0/0")])
        sent = _call(middleware, _scope())
        assert _status(sent) == 403


class TestShortCircuitWriteBack:
    def test_status_content_type_and_content_length(self) -> None:
        middleware = ProtectionASGIMiddleware(_App(), ip_blacklist=[IpBlacklistEntry("0.0.0.0/0")])
        sent = _call(middleware, _scope())
        assert _status(sent) == 403
        headers = _headers(sent)
        assert headers["content-type"] == "application/json; charset=utf-8"
        assert int(headers["content-length"]) == len(_body(sent))
        assert json.loads(_body(sent)) == {"error": "ip_blacklisted"}

    def test_custom_renderer_output_is_preserved_byte_for_byte(self) -> None:
        middleware = ProtectionASGIMiddleware(
            _App(),
            ip_blacklist=[IpBlacklistEntry("0.0.0.0/0")],
            deny_renderer=lambda status, reason: f"{status}:{reason}".encode(),
        )
        sent = _call(middleware, _scope())
        assert _body(sent) == b"403:ip_blacklisted"

    def test_non_utf8_renderer_output_survives_the_round_trip(self) -> None:
        """bytes → str → bytes 必须无损，否则自定义渲染器会被改写。"""
        payload = b"\xff\xfe raw bytes"

        def _renderer(status: int, reason: str) -> bytes:
            return payload

        middleware = ProtectionASGIMiddleware(
            _App(),
            ip_blacklist=[IpBlacklistEntry("0.0.0.0/0")],
            deny_renderer=_renderer,
        )
        sent = _call(middleware, _scope())
        assert _body(sent) == payload

    def test_rate_limit_deny_keeps_body_and_headers(self) -> None:
        route = RateLimitRoute(
            "/api/orders",
            deny_code="SLOW_DOWN",
            deny_message="慢一点 (key={key})",
            deny_headers={"Retry-After": "30"},
        )
        guard, _ = _rate_guard(allow=False, route=route)
        middleware = ProtectionASGIMiddleware(_App(), rate_limit_guard=guard)
        sent = _call(middleware, _scope("/api/orders", "POST", _rl_headers()))
        assert _status(sent) == 429
        assert json.loads(_body(sent)) == {"error": "SLOW_DOWN", "message": "慢一点 (key=partner-1)"}
        assert _headers(sent)["retry-after"] == "30"

    def test_duplicate_headers_are_all_counted(self) -> None:
        """ctx 保留同名 header 的全部值（与 Java collectHeaders 一致）。"""
        scope = _scope()
        scope["headers"] = [(b"x-a", b"a" * 40), (b"x-a", b"b" * 40)]
        middleware = ProtectionASGIMiddleware(_App(), size_guard=RequestSizeGuard(1000, 60))
        sent = _call(middleware, scope)
        assert _status(sent) == 431


class TestChainDrivenBehaviour:
    def test_deny_never_reaches_the_app(self) -> None:
        app = _App()
        middleware = ProtectionASGIMiddleware(app, ip_blacklist=[IpBlacklistEntry("0.0.0.0/0")])
        _call(middleware, _scope())
        assert app.calls == 0

    def test_non_http_scope_passes_through(self) -> None:
        app = _App()
        middleware = ProtectionASGIMiddleware(app, ip_blacklist=[IpBlacklistEntry("0.0.0.0/0")])
        _call(middleware, _scope(type_="websocket"))
        assert app.calls == 1

    def test_interceptors_can_be_driven_manually(self) -> None:
        """装配出的拦截器可脱离 ASGI 单独驱动（白盒验证 ctx 装配）。"""
        middleware = ProtectionASGIMiddleware(_App(), size_guard=RequestSizeGuard(100, 10_000))
        interceptor = next(
            i for i in middleware.interceptors if type(i).__name__ == "RequestSizeInterceptor"
        )
        ctx = MutableWebRequestContext("POST", "/", {"content-length": ["500"]})
        interceptor.intercept(ctx, DefaultWebInterceptorChain([]))
        assert ctx.is_short_circuited is True
        assert ctx.response_status == 413

    def test_gateway_interceptor_sets_the_bypass_flag_on_the_context(self) -> None:
        middleware = ProtectionASGIMiddleware(_App())
        interceptor = next(
            i for i in middleware.interceptors if type(i).__name__ == "GatewayBypassInterceptor"
        )
        ctx = MutableWebRequestContext("GET", "/", {"x-forwarded-from-gateway": "edge-1"})
        interceptor.intercept(ctx, DefaultWebInterceptorChain([]))
        assert ctx.attribute("platform.web.gateway-bypass") is True
        assert ctx.attribute("platform.web.gateway-id") == "edge-1"


class TestExistingBehaviourIsPreserved:
    """改造前的既有契约必须逐条保持。"""

    def test_rate_limit_still_runs_before_signature(self) -> None:
        guard, _ = _rate_guard(allow=False)

        class _CountingKeys:
            def __init__(self) -> None:
                self.calls = 0

            def secret_for(self, key):
                self.calls += 1
                return SECRET

        keys = _CountingKeys()
        signature = ApiSignatureVerifier(keys, NonceCache(300), 60, clock=lambda: NOW_MS / 1000)
        middleware = ProtectionASGIMiddleware(
            _App(), rate_limit_guard=guard, signature_verifier=signature
        )
        sent = _call(middleware, _scope("/api/orders", "POST", _rl_headers()))
        assert _status(sent) == 429
        assert keys.calls == 0

    def test_idempotency_still_runs_before_rate_limit(self) -> None:
        from atlas_richie.web_protection import IdempotencyGuard, InMemoryIdempotencyStore

        guard, limiter = _rate_guard(allow=True)
        middleware = ProtectionASGIMiddleware(
            _App(),
            idempotency_guard=IdempotencyGuard(InMemoryIdempotencyStore(60)),
            rate_limit_guard=guard,
        )
        scope = _scope("/api/orders", "POST", {**_rl_headers(), "x-idempotency-key": "k"})
        _call(middleware, scope)
        sent = _call(middleware, scope)
        assert _status(sent) == 409
        assert len(limiter.calls) == 1

    def test_ip_blacklist_still_wins_over_long_lived_bypass(self) -> None:
        app = _App()
        middleware = ProtectionASGIMiddleware(
            app,
            ip_blacklist=(IpBlacklistEntry("203.0.113.0/24"),),
            long_lived_bypass=LongLivedPathBypass(["/sse/**"]),
        )
        sent = _call(middleware, _scope("/sse/orders", "GET", client=("203.0.113.9", 1)))
        assert _status(sent) == 403
        assert app.calls == 0

    def test_valid_signature_still_passes(self) -> None:
        app = _App()
        signature = hmac_sha256_hex(SECRET, canonicalize("POST", "/api/orders", NOW_MS, "n-1"))
        headers = {
            "x-client-key": "partner",
            "x-timestamp": str(NOW_MS),
            "x-nonce": "n-1",
            "x-signature": signature,
        }
        middleware = ProtectionASGIMiddleware(
            app,
            signature_verifier=ApiSignatureVerifier(_Keys(), NonceCache(300), 60, clock=lambda: NOW_MS / 1000),
        )
        _call(middleware, _scope("/api/orders", "POST", headers))
        assert app.calls == 1


class TestInterceptorImports:
    """确保适配层用的是 web-protection 的同一套拦截器实现（不是复制品）。"""

    def test_adapter_uses_the_shared_interceptor_classes(self) -> None:
        assert IpBlacklistInterceptor.__module__.startswith("atlas_richie.web_protection.")
        assert SignatureInterceptor.__module__.startswith("atlas_richie.web_protection.")
        assert LoginLockInterceptor.__module__.startswith("atlas_richie.web_protection.")
        assert IdempotencyInterceptor.__module__.startswith("atlas_richie.web_protection.")
        assert BotUserAgentInterceptor.__module__.startswith("atlas_richie.web_protection.")
        assert GatewayBypassInterceptor.__module__.startswith("atlas_richie.web_protection.")
        assert LongLivedBypassInterceptor.__module__.startswith("atlas_richie.web_protection.")
        assert RequestSizeInterceptor.__module__.startswith("atlas_richie.web_protection.")
        assert RateLimitInterceptor.__module__.startswith("atlas_richie.web_protection.")

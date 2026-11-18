"""ASGI middleware tests, driven with raw scope/receive/send (no framework)."""

from __future__ import annotations

import asyncio
import json
import uuid

import pytest

from atlas_richie.web_protection import (
    ApiSignatureVerifier,
    BotUserAgentMatcher,
    IpBlacklistEntry,
    LoginAttemptTracker,
    NonceCache,
    RequestSizeGuard,
    canonicalize,
    hmac_sha256_hex,
)
from atlas_richie.web_protection_adapter_asgi import (
    ProtectionASGIMiddleware,
    client_ip,
    header_map,
)

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


def _scope(path="/", method="GET", headers=None, client=("203.0.113.9", 1234), type_="http"):
    return {
        "type": type_,
        "method": method,
        "path": path,
        "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
        "client": client,
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


class _Keys:
    def secret_for(self, client_key: str) -> bytes | None:
        return SECRET if client_key == "partner" else None


def _signed_headers(path="/api/orders", method="POST", nonce="n-1"):
    ts = NOW_MS
    signature = hmac_sha256_hex(SECRET, canonicalize(method, path, ts, nonce))
    return {
        "x-client-key": "partner",
        "x-timestamp": str(ts),
        "x-nonce": nonce,
        "x-signature": signature,
    }


def _verifier():
    return ApiSignatureVerifier(_Keys(), NonceCache(300), 60, clock=lambda: NOW_MS / 1000)


class TestPassthrough:
    def test_no_guards_is_passthrough(self) -> None:
        app = _App()
        sent = _call(ProtectionASGIMiddleware(app), _scope())
        assert app.calls == 1
        assert _status(sent) == 200

    @pytest.mark.parametrize("type_", ["lifespan", "websocket"])
    def test_non_http_scopes_pass_through(self, type_: str) -> None:
        app = _App()
        middleware = ProtectionASGIMiddleware(app, ip_blacklist=[IpBlacklistEntry("0.0.0.0/0")])
        _call(middleware, _scope(type_=type_))
        assert app.calls == 1, "guards must not apply to non-http scopes"


class TestIpBlacklist:
    def test_blacklisted_ip_denied(self) -> None:
        app = _App()
        middleware = ProtectionASGIMiddleware(app, ip_blacklist=[IpBlacklistEntry("203.0.113.0/24")])
        sent = _call(middleware, _scope())
        assert _status(sent) == 403
        assert json.loads(_body(sent)) == {"error": "ip_blacklisted"}
        assert app.calls == 0

    def test_other_ip_allowed(self) -> None:
        app = _App()
        middleware = ProtectionASGIMiddleware(app, ip_blacklist=[IpBlacklistEntry("10.0.0.0/8")])
        _call(middleware, _scope())
        assert app.calls == 1

    def test_forwarded_first_hop_used_when_trusted(self) -> None:
        app = _App()
        middleware = ProtectionASGIMiddleware(
            app, ip_blacklist=[IpBlacklistEntry("198.51.100.7")], trust_forwarded=True
        )
        sent = _call(middleware, _scope(headers={"x-forwarded-for": "198.51.100.7, 10.0.0.1"}))
        assert _status(sent) == 403

    def test_forwarded_ignored_by_default(self) -> None:
        app = _App()
        middleware = ProtectionASGIMiddleware(app, ip_blacklist=[IpBlacklistEntry("198.51.100.7")])
        _call(middleware, _scope(headers={"x-forwarded-for": "198.51.100.7"}))
        assert app.calls == 1, "client-supplied XFF must not be trusted by default"


class TestBotMatcher:
    def test_bot_denied(self) -> None:
        app = _App()
        middleware = ProtectionASGIMiddleware(app, bot_matchers=[BotUserAgentMatcher("*curl*")])
        sent = _call(middleware, _scope(headers={"user-agent": "curl/8.4.0"}))
        assert _status(sent) == 403
        assert json.loads(_body(sent)) == {"error": "bot_detected"}

    def test_normal_agent_allowed(self) -> None:
        app = _App()
        middleware = ProtectionASGIMiddleware(app, bot_matchers=[BotUserAgentMatcher("*curl*")])
        _call(middleware, _scope(headers={"user-agent": "Mozilla/5.0"}))
        assert app.calls == 1


class TestSizeGuard:
    def test_oversized_body_denied(self) -> None:
        app = _App()
        middleware = ProtectionASGIMiddleware(app, size_guard=RequestSizeGuard(100, 10_000))
        sent = _call(middleware, _scope(headers={"content-length": "500"}))
        assert _status(sent) == 413
        assert json.loads(_body(sent)) == {"error": "REQUEST_BODY_TOO_LARGE"}
        assert app.calls == 0

    def test_oversized_headers_denied(self) -> None:
        app = _App()
        middleware = ProtectionASGIMiddleware(app, size_guard=RequestSizeGuard(1000, 10))
        sent = _call(middleware, _scope(headers={"x-long": "a" * 50}))
        assert _status(sent) == 431

    def test_body_is_not_consumed(self) -> None:
        app = _App()
        middleware = ProtectionASGIMiddleware(app, size_guard=RequestSizeGuard(1000, 10_000))
        _call(middleware, _scope(headers={"content-length": "10"}))
        assert app.calls == 1


class TestSignature:
    def test_valid_signature_passes(self) -> None:
        app = _App()
        middleware = ProtectionASGIMiddleware(app, signature_verifier=_verifier())
        _call(middleware, _scope("/api/orders", "POST", _signed_headers()))
        assert app.calls == 1

    def test_missing_headers_denied(self) -> None:
        app = _App()
        middleware = ProtectionASGIMiddleware(app, signature_verifier=_verifier())
        sent = _call(middleware, _scope("/api/orders", "POST", {"x-client-key": "partner"}))
        assert _status(sent) == 401
        assert json.loads(_body(sent)) == {"error": "missing_header"}

    def test_bad_signature_denied(self) -> None:
        app = _App()
        headers = _signed_headers()
        headers["x-signature"] = "deadbeef"
        middleware = ProtectionASGIMiddleware(app, signature_verifier=_verifier())
        sent = _call(middleware, _scope("/api/orders", "POST", headers))
        assert json.loads(_body(sent)) == {"error": "signature_mismatch"}

    def test_non_ascii_signature_header_denied_not_crashed(self) -> None:
        """Regression: ASGI delivers headers latin-1 decoded, so a hostile
        signature can contain non-ASCII. That must be a 401, not a 500."""
        app = _App()
        middleware = ProtectionASGIMiddleware(app, signature_verifier=_verifier())
        scope = _scope("/api/orders", "POST", _signed_headers())
        scope["headers"] = [
            (k, b"ab\xff" if k == b"x-signature" else v) for k, v in scope["headers"]
        ]
        sent = _call(middleware, scope)
        assert _status(sent) == 401
        assert json.loads(_body(sent)) == {"error": "signature_mismatch"}
        assert app.calls == 0

    def test_replayed_nonce_denied(self) -> None:
        app = _App()
        middleware = ProtectionASGIMiddleware(app, signature_verifier=_verifier())
        _call(middleware, _scope("/api/orders", "POST", _signed_headers()))
        sent = _call(middleware, _scope("/api/orders", "POST", _signed_headers()))
        assert json.loads(_body(sent)) == {"error": "nonce_replay"}

    def test_gateway_bypass_header_skips_signature(self) -> None:
        app = _App()
        middleware = ProtectionASGIMiddleware(app, signature_verifier=_verifier())
        _call(middleware, _scope("/api/orders", "POST", {"x-forwarded-from-gateway": "1"}))
        assert app.calls == 1

    def test_default_bypass_header_matches_java_contract(self) -> None:
        """Regression: the default was x-gateway-verified, which no Java gateway
        sends, so the bypass silently never fired in a mixed deployment."""
        app = _App()
        middleware = ProtectionASGIMiddleware(app, signature_verifier=_verifier())
        headers = _signed_headers()
        headers["x-signature"] = "deadbeef"
        headers["X-Forwarded-From-Gateway"] = "edge-1"
        sent = _call(middleware, _scope("/api/orders", "POST", headers))
        assert app.calls == 1, "Java 契约头名必须触发 bypass（大小写不敏感）"

    def test_gateway_bypass_can_be_disabled(self) -> None:
        app = _App()
        middleware = ProtectionASGIMiddleware(
            app, signature_verifier=_verifier(), gateway_bypass_header=None
        )
        # A client key is present but no signature: with bypass disabled this must deny.
        sent = _call(
            middleware,
            _scope("/api/orders", "POST", {"x-forwarded-from-gateway": "1", "x-client-key": "partner"}),
        )
        assert _status(sent) == 401
        assert app.calls == 0

    def test_blank_client_key_passes_through(self) -> None:
        app = _App()
        middleware = ProtectionASGIMiddleware(app, signature_verifier=_verifier())
        _call(middleware, _scope("/api/orders", "POST"))
        assert app.calls == 1


class TestLoginTracker:
    def test_locked_key_rejected_before_app(self) -> None:
        app = _App()
        tracker = LoginAttemptTracker(300, 1, 900)
        tracker.record_failure("203.0.113.9")
        middleware = ProtectionASGIMiddleware(app, login_tracker=tracker)
        sent = _call(middleware, _scope("/login"))
        assert _status(sent) == 429
        assert json.loads(_body(sent)) == {"error": "account_locked"}
        assert app.calls == 0

    def test_downstream_401_records_failure(self) -> None:
        app = _App(status=401)
        tracker = LoginAttemptTracker(300, 2, 900)
        middleware = ProtectionASGIMiddleware(app, login_tracker=tracker)
        _call(middleware, _scope("/login"))
        assert tracker.is_locked("203.0.113.9") is False
        _call(middleware, _scope("/login"))
        assert tracker.is_locked("203.0.113.9") is True

    def test_downstream_2xx_records_success(self) -> None:
        tracker = LoginAttemptTracker(300, 2, 900)
        tracker.record_failure("203.0.113.9")
        middleware = ProtectionASGIMiddleware(_App(status=200), login_tracker=tracker)
        _call(middleware, _scope("/login"))
        assert tracker.size() == 0

    def test_non_login_path_is_not_tracked(self) -> None:
        tracker = LoginAttemptTracker(300, 1, 900)
        middleware = ProtectionASGIMiddleware(_App(status=401), login_tracker=tracker)
        _call(middleware, _scope("/other"))
        assert tracker.is_locked("203.0.113.9") is False

    def test_custom_login_key(self) -> None:
        tracker = LoginAttemptTracker(300, 1, 900)
        middleware = ProtectionASGIMiddleware(
            _App(status=401), login_tracker=tracker,
            login_key=lambda scope, headers: headers.get("x-user"),
        )
        _call(middleware, _scope("/login", headers={"x-user": "alice"}))
        assert tracker.is_locked("alice") is True
        assert tracker.is_locked("203.0.113.9") is False


class TestOrderingAndRendering:
    def test_ip_is_checked_before_bot_and_signature(self) -> None:
        app = _App()
        middleware = ProtectionASGIMiddleware(
            app,
            ip_blacklist=[IpBlacklistEntry("0.0.0.0/0")],
            bot_matchers=[BotUserAgentMatcher("*")],
            signature_verifier=_verifier(),
        )
        sent = _call(middleware, _scope(headers={"user-agent": "curl"}))
        assert json.loads(_body(sent)) == {"error": "ip_blacklisted"}

    def test_bot_is_checked_before_size(self) -> None:
        app = _App()
        middleware = ProtectionASGIMiddleware(
            app, bot_matchers=[BotUserAgentMatcher("*")], size_guard=RequestSizeGuard(1, 1)
        )
        sent = _call(middleware, _scope(headers={"user-agent": "x", "content-length": "99"}))
        assert json.loads(_body(sent)) == {"error": "bot_detected"}

    def test_custom_deny_renderer_and_status(self) -> None:
        app = _App()
        middleware = ProtectionASGIMiddleware(
            app,
            ip_blacklist=[IpBlacklistEntry("0.0.0.0/0")],
            deny_status_ip=418,
            deny_renderer=lambda status, reason: f"{status}:{reason}".encode(),
        )
        sent = _call(middleware, _scope())
        assert _status(sent) == 418
        assert _body(sent) == b"418:ip_blacklisted"

    def test_deny_sets_content_length(self) -> None:
        middleware = ProtectionASGIMiddleware(_App(), ip_blacklist=[IpBlacklistEntry("0.0.0.0/0")])
        sent = _call(middleware, _scope())
        start = next(m for m in sent if m["type"] == "http.response.start")
        headers = dict(start["headers"])
        assert int(headers[b"content-length"]) == len(_body(sent))


class TestHelpers:
    def test_header_map_lowercases_and_decodes(self) -> None:
        scope = _scope(headers={"X-Client-Key": "partner"})
        assert header_map(scope) == {"x-client-key": "partner"}

    def test_client_ip_from_scope(self) -> None:
        assert client_ip(_scope(), {}) == "203.0.113.9"

    def test_client_ip_absent(self) -> None:
        scope = _scope()
        scope["client"] = None
        assert client_ip(scope, {}) is None


class _AllowLimiter:
    def __init__(self, allow: bool = True) -> None:
        self.allow = allow
        self.calls: list[tuple[str, int, int]] = []

    def try_acquire(self, key: str, max_count: int, window_seconds: int) -> bool:
        self.calls.append((key, max_count, window_seconds))
        return self.allow


def _rate_guard(allow=True, route=None):
    from atlas_richie.web_protection import (
        CompositeKeyResolver,
        HeaderClientKeyResolver,
        IpClientKeyResolver,
        RateLimitGuard,
        RateLimitProperties,
        RateLimitRoute,
    )

    limiter = _AllowLimiter(allow)
    guard = RateLimitGuard(
        limiter,
        RateLimitProperties(routes=(route or RateLimitRoute("/api/orders", permits_per_second=2),)),
        CompositeKeyResolver(HeaderClientKeyResolver(), IpClientKeyResolver()),
    )
    return guard, limiter


from conftest import REDIS_URL  # noqa: E402


def _rl_headers(**overrides):
    base = {"x-client-key": "partner-1", "x-forwarded-from-gateway": "edge-1"}
    base.update(overrides)
    return base


class TestRateLimitMiddleware:
    def test_allowed_request_passes_through(self) -> None:
        app = _App()
        guard, limiter = _rate_guard()
        middleware = ProtectionASGIMiddleware(app, rate_limit_guard=guard)
        _call(middleware, _scope("/api/orders", "POST", _rl_headers()))
        assert app.calls == 1
        assert limiter.calls == [("richie:web:rate-limit:partner-1:/api/orders", 2, 1)]

    def test_rate_limited_returns_429_with_code_message_and_headers(self) -> None:
        from atlas_richie.web_protection import RateLimitRoute

        app = _App()
        route = RateLimitRoute(
            "/api/orders", deny_code="SLOW_DOWN",
            deny_message="慢一点 (key={key})", deny_headers={"Retry-After": "30"},
        )
        guard, _ = _rate_guard(allow=False, route=route)
        middleware = ProtectionASGIMiddleware(app, rate_limit_guard=guard)
        sent = _call(middleware, _scope("/api/orders", "POST", _rl_headers()))
        assert app.calls == 0
        assert _status(sent) == 429
        payload = json.loads(_body(sent))
        assert payload == {"error": "SLOW_DOWN", "message": "慢一点 (key=partner-1)"}
        header_names = {k.decode() for m in sent if m["type"] == "http.response.start"
                        for k, _ in m["headers"]}
        assert "retry-after" in {n.lower() for n in header_names}

    def test_gateway_identity_missing_returns_401(self) -> None:
        app = _App()
        guard, _ = _rate_guard()
        middleware = ProtectionASGIMiddleware(app, rate_limit_guard=guard)
        sent = _call(middleware, _scope("/api/orders", "POST", {"x-client-key": "k"}))
        assert _status(sent) == 401
        assert app.calls == 0

    def test_unmatched_route_is_passthrough(self) -> None:
        app = _App()
        guard, limiter = _rate_guard()
        middleware = ProtectionASGIMiddleware(app, rate_limit_guard=guard)
        _call(middleware, _scope("/health", "GET", _rl_headers()))
        assert app.calls == 1
        assert limiter.calls == []

    def test_rate_limit_runs_before_signature_verification(self) -> None:
        app = _App()
        guard, _ = _rate_guard(allow=False)
        from atlas_richie.web_protection import ApiSignatureVerifier, NonceCache

        class _CountingKeys:
            def __init__(self) -> None:
                self.calls = 0

            def secret_for(self, key):
                self.calls += 1
                return SECRET

        keys = _CountingKeys()
        signature = ApiSignatureVerifier(keys, NonceCache(300), 60, clock=lambda: NOW_MS / 1000)
        middleware = ProtectionASGIMiddleware(
            app, rate_limit_guard=guard, signature_verifier=signature
        )
        sent = _call(middleware, _scope("/api/orders", "POST", _rl_headers()))
        assert _status(sent) == 429, "限流应先于签名"
        assert keys.calls == 0, "被限流的请求不应再触发签名验证"

    def test_ip_blacklist_still_wins_over_rate_limit(self) -> None:
        app = _App()
        guard, _ = _rate_guard(allow=True)
        middleware = ProtectionASGIMiddleware(
            app,
            rate_limit_guard=guard,
            ip_blacklist=(IpBlacklistEntry("203.0.113.0/24"),),
        )
        sent = _call(
            middleware,
            _scope("/api/orders", "GET", _rl_headers(), client=("203.0.113.9", 1)),
        )
        assert _status(sent) == 403
        assert app.calls == 0

    def test_no_guard_is_passthrough(self) -> None:
        app = _App()
        _call(ProtectionASGIMiddleware(app), _scope("/api/orders", "POST", _rl_headers()))
        assert app.calls == 1

    def test_ip_fallback_when_no_client_key_header(self) -> None:
        app = _App()
        guard, limiter = _rate_guard()
        middleware = ProtectionASGIMiddleware(app, rate_limit_guard=guard)
        _call(
            middleware,
            _scope("/api/orders", "GET", {"x-forwarded-from-gateway": "e"}, client=("198.51.100.7", 5)),
        )
        assert app.calls == 1
        assert limiter.calls[0][0] == "richie:web:rate-limit:198.51.100.7:/api/orders"


@pytest.mark.integration
class TestRateLimitAgainstRedis:
    def _guard(self, registrar, permits):
        from atlas_richie.web_protection import (
            CompositeKeyResolver,
            HeaderClientKeyResolver,
            IpClientKeyResolver,
            RateLimitGuard,
            RateLimitProperties,
            RateLimitRoute,
        )

        return RateLimitGuard(
            registrar.limiter_ops(),
            RateLimitProperties(
                key_prefix=f"rl:{uuid.uuid4().hex[:8]}",
                routes=(RateLimitRoute("/api/orders", permits_per_second=permits),),
            ),
            CompositeKeyResolver(HeaderClientKeyResolver(), IpClientKeyResolver()),
        )

    def test_permits_exhaust_then_429(self, requires_redis) -> None:
        import redis as redis_lib
        from atlas_richie.cache_redis import RedisProviderRegistrar

        url = REDIS_URL
        client = redis_lib.Redis.from_url(url, decode_responses=True)
        try:
            client.ping()
        except redis_lib.exceptions.RedisError:
            pytest.skip(f"Redis not reachable at {url!r}")
        registrar = RedisProviderRegistrar(client, namespace=f"rl-test:{uuid.uuid4().hex[:8]}")
        app = _App()
        try:
            middleware = ProtectionASGIMiddleware(
                app, rate_limit_guard=self._guard(registrar, permits=3)
            )
            scope = _scope("/api/orders", "POST", _rl_headers())
            statuses = [_status(_call(middleware, scope)) for _ in range(5)]
            assert statuses[:3] == [200, 200, 200], "前 3 次应在配额内"
            assert statuses[3:] == [429, 429], "超出配额必须被限流"
            assert app.calls == 3
        finally:
            registrar.close()
            client.close()

    def test_window_reset_restores_permits(self, requires_redis) -> None:
        import time as _t
        import redis as redis_lib
        from atlas_richie.cache_redis import RedisProviderRegistrar

        client = redis_lib.Redis.from_url(REDIS_URL, decode_responses=True)
        registrar = RedisProviderRegistrar(client, namespace=f"rl-test:{uuid.uuid4().hex[:8]}")
        app = _App()
        try:
            middleware = ProtectionASGIMiddleware(
                app, rate_limit_guard=self._guard(registrar, permits=1)
            )
            scope = _scope("/api/orders", "POST", _rl_headers())
            assert _status(_call(middleware, scope)) == 200
            assert _status(_call(middleware, scope)) == 429
            _t.sleep(2.0)  # 窗口 1 秒，越过整个窗口
            assert _status(_call(middleware, scope)) == 200, "窗口滚动后配额应恢复"
        finally:
            registrar.close()
            client.close()


class TestIdempotencyMiddleware:
    def _guard(self):
        from atlas_richie.web_protection import IdempotencyGuard, InMemoryIdempotencyStore

        return IdempotencyGuard(InMemoryIdempotencyStore(60))

    def test_first_submission_passes(self) -> None:
        app = _App()
        middleware = ProtectionASGIMiddleware(app, idempotency_guard=self._guard())
        sent = _call(middleware, _scope("/api/orders", "POST", {"x-idempotency-key": "k1"}))
        assert app.calls == 1

    def test_replay_denied_409(self) -> None:
        app = _App()
        middleware = ProtectionASGIMiddleware(app, idempotency_guard=self._guard())
        scope = _scope("/api/orders", "POST", {"x-idempotency-key": "k1"})
        _call(middleware, scope)
        sent = _call(middleware, scope)
        assert _status(sent) == 409
        assert app.calls == 1
        assert json.loads(_body(sent)) == {"error": "idempotent_replay"}

    def test_no_header_passes(self) -> None:
        app = _App()
        middleware = ProtectionASGIMiddleware(app, idempotency_guard=self._guard())
        _call(middleware, _scope("/api/orders", "POST"))
        _call(middleware, _scope("/api/orders", "POST"))
        assert app.calls == 2, "无幂等键的请求不受去重约束"

    def test_idempotency_runs_before_rate_limit(self) -> None:
        app = _App()
        guard, limiter = _rate_guard(allow=True)
        middleware = ProtectionASGIMiddleware(
            app, idempotency_guard=self._guard(), rate_limit_guard=guard
        )
        scope = _scope("/api/orders", "POST", {**_rl_headers(), "x-idempotency-key": "k"})
        _call(middleware, scope)
        sent = _call(middleware, scope)
        assert _status(sent) == 409, "重复提交应先于限流被拒"
        assert len(limiter.calls) == 1, "被幂等拒绝的请求不应消耗限流配额"


class TestLongLivedBypassMiddleware:
    def test_sse_path_skips_guards(self) -> None:
        from atlas_richie.web_protection import LongLivedPathBypass

        app = _App()
        guard, limiter = _rate_guard(allow=False)
        middleware = ProtectionASGIMiddleware(
            app,
            rate_limit_guard=guard,
            long_lived_bypass=LongLivedPathBypass(["/sse/**"]),
        )
        sent = _call(middleware, _scope("/sse/orders", "GET", _rl_headers()))
        assert app.calls == 1, "SSE 长流应跳过限流直接放行"
        assert limiter.calls == []

    def test_non_long_lived_path_still_guarded(self) -> None:
        from atlas_richie.web_protection import LongLivedPathBypass

        app = _App()
        guard, _ = _rate_guard(allow=False)
        middleware = ProtectionASGIMiddleware(
            app,
            rate_limit_guard=guard,
            long_lived_bypass=LongLivedPathBypass(["/sse/**"]),
        )
        sent = _call(middleware, _scope("/api/orders", "POST", _rl_headers()))
        assert _status(sent) == 429
        assert app.calls == 0

    def test_bypass_skips_signature_too(self) -> None:
        from atlas_richie.web_protection import LongLivedPathBypass

        app = _App()
        middleware = ProtectionASGIMiddleware(
            app,
            signature_verifier=_verifier(),
            long_lived_bypass=LongLivedPathBypass(["/ws/**"]),
        )
        # 无签名头，但长连接路径豁免 → 放行
        _call(middleware, _scope("/ws/chat", "GET", {"x-client-key": "partner"}))
        assert app.calls == 1

    def test_ip_blacklist_still_applies_to_long_lived(self) -> None:
        from atlas_richie.web_protection import LongLivedPathBypass

        app = _App()
        middleware = ProtectionASGIMiddleware(
            app,
            ip_blacklist=(IpBlacklistEntry("203.0.113.0/24"),),
            long_lived_bypass=LongLivedPathBypass(["/sse/**"]),
        )
        sent = _call(
            middleware,
            _scope("/sse/orders", "GET", client=("203.0.113.9", 1)),
        )
        assert _status(sent) == 403, "IP 黑名单先于长连接豁免，仍应生效"
        assert app.calls == 0

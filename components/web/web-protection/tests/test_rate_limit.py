"""分布式限流决策：路由匹配、身份/key 校验、Redis 键与拒绝响应。"""

from __future__ import annotations

import re

import pytest

from atlas_richie.web_protection import (
    CompositeKeyResolver,
    HeaderClientKeyResolver,
    IpClientKeyResolver,
    RateLimitDecision,
    RateLimitGuard,
    RateLimitProperties,
    RateLimitRoute,
    ant_pattern_to_regex,
)

pytestmark = pytest.mark.unit


class FakeLimiter:
    def __init__(self, allow: bool = True) -> None:
        self.allow = allow
        self.calls: list[tuple[str, int, int]] = []

    def try_acquire(self, key: str, max_count: int, window_seconds: int) -> bool:
        self.calls.append((key, max_count, window_seconds))
        return self.allow


def _guard(limiter=None, *, routes=(), **props_overrides) -> tuple[RateLimitGuard, FakeLimiter]:
    limiter = limiter if limiter is not None else FakeLimiter()
    props = RateLimitProperties(routes=tuple(routes), **props_overrides)
    guard = RateLimitGuard(
        limiter, props,
        CompositeKeyResolver(HeaderClientKeyResolver(), IpClientKeyResolver()),
    )
    return guard, limiter


def _headers(**overrides) -> dict[str, str]:
    base = {"x-client-key": "partner-1", "x-forwarded-from-gateway": "edge-1"}
    base.update(overrides)
    return base


class TestAntPattern:
    @pytest.mark.parametrize(
        ("pattern", "path", "expected"),
        [
            ("/api/orders", "/api/orders", True),
            ("/api/orders", "/api/orders/1", False),
            ("/api/*", "/api/orders", True),
            ("/api/*", "/api/orders/1", False),
            ("/api/**", "/api/orders/1/items", True),
            ("/api/?.txt", "/api/a.txt", True),
            ("/api/?.txt", "/api/.txt", False),
            ("/api/{id}", "/api/42", True),
            ("/api/{id}", "/api/42/items", False),
            ("/api/v?/list", "/api/v1/list", True),
            ("/a*b", "/axxb", True),
            ("/a*b", "/a/b", False),
            ("**", "/anything/at/all", True),
        ],
    )
    def test_matching(self, pattern, path, expected) -> None:
        assert bool(ant_pattern_to_regex(pattern).match(path)) is expected

    def test_special_regex_characters_in_pattern_do_not_match_as_regex(self) -> None:
        compiled = ant_pattern_to_regex("/a.b")
        assert compiled.match("/a.b") is not None
        assert compiled.match("/axb") is None, "'.' 应按字面量处理"


class TestRouteMatching:
    def test_unmatched_path_is_not_limited(self) -> None:
        guard, limiter = _guard(routes=[RateLimitRoute("/api/orders")])
        assert guard.check("/health", _headers(), ip="1.2.3.4") is None
        assert limiter.calls == [], "未匹配路由不得触碰 Redis"

    def test_exact_match(self) -> None:
        guard, _ = _guard(routes=[RateLimitRoute("/api/orders")])
        decision = guard.check("/api/orders", _headers(), ip="1.2.3.4")
        assert decision is not None and decision.allowed

    def test_exact_match_wins_over_pattern(self) -> None:
        routes = [
            RateLimitRoute("/api/orders", permits_per_second=7),
            RateLimitRoute("/api/**", permits_per_second=99),
        ]
        guard, limiter = _guard(routes=routes)
        guard.check("/api/orders", _headers(), ip="1.2.3.4")
        assert limiter.calls[0][1] == 7, "精确路由优先于模式路由"

    def test_pattern_match(self) -> None:
        guard, _ = _guard(routes=[RateLimitRoute("/api/**")])
        decision = guard.check("/api/orders/1", _headers(), ip="1.2.3.4")
        assert decision is not None and decision.pattern == "/api/**"

    def test_first_route_wins_among_patterns(self) -> None:
        routes = [
            RateLimitRoute("/api/a/**", permits_per_second=5),
            RateLimitRoute("/api/**", permits_per_second=9),
        ]
        guard, limiter = _guard(routes=routes)
        guard.check("/api/a/x", _headers(), ip="1.2.3.4")
        assert limiter.calls[0][1] == 5

    def test_empty_path_no_route(self) -> None:
        guard, _ = _guard(routes=[RateLimitRoute("**")])
        assert guard.check("", _headers()) is None


class TestIdentityAndKey:
    def test_gateway_identity_required_by_default(self) -> None:
        guard, limiter = _guard(routes=[RateLimitRoute("/api/orders")])
        decision = guard.check("/api/orders", {"x-client-key": "k"}, ip="1.2.3.4")
        assert decision is not None
        assert decision.reason == "gateway_identity_missing"
        assert decision.status == 401
        assert limiter.calls == []

    def test_gateway_identity_optional_when_disabled(self) -> None:
        guard, limiter = _guard(
            routes=[RateLimitRoute("/api/orders")], require_gateway_identity=False
        )
        decision = guard.check("/api/orders", {"x-client-key": "k"}, ip="1.2.3.4")
        assert decision is not None and decision.allowed

    def test_identity_header_is_case_insensitive(self) -> None:
        guard, _ = _guard(routes=[RateLimitRoute("/api/orders")])
        decision = guard.check(
            "/api/orders",
            {"x-client-key": "k", "X-Forwarded-From-Gateway": "edge"},
            ip="1.2.3.4",
        )
        assert decision is not None and decision.allowed

    def test_blank_identity_rejected(self) -> None:
        guard, _ = _guard(routes=[RateLimitRoute("/api/orders")])
        decision = guard.check(
            "/api/orders", {"x-client-key": "k", "x-forwarded-from-gateway": "  "}, ip="1.2.3.4"
        )
        assert decision is not None
        assert decision.reason == "gateway_identity_missing"

    def test_unresolvable_client_key_rejected(self) -> None:
        guard, limiter = _guard(routes=[RateLimitRoute("/api/orders")])
        decision = guard.check(
            "/api/orders", {"x-forwarded-from-gateway": "edge"}, ip=None
        )
        assert decision is not None
        assert decision.reason == "client_unidentified"
        assert limiter.calls == []

    def test_oversized_client_key_rejected(self) -> None:
        guard, _ = _guard(routes=[RateLimitRoute("/api/orders")])
        big = "x" * 257
        decision = guard.check(
            "/api/orders", {"x-client-key": big, "x-forwarded-from-gateway": "e"}, ip=None
        )
        assert decision is not None
        assert decision.reason == "client_unidentified"

    def test_composite_falls_back_to_ip(self) -> None:
        guard, _ = _guard(routes=[RateLimitRoute("/api/orders")])
        decision = guard.check(
            "/api/orders", {"x-forwarded-from-gateway": "e"}, ip="203.0.113.9"
        )
        assert decision is not None
        assert decision.client_key == "203.0.113.9"

    def test_header_wins_over_ip(self) -> None:
        guard, _ = _guard(routes=[RateLimitRoute("/api/orders")])
        decision = guard.check("/api/orders", _headers(), ip="203.0.113.9")
        assert decision is not None
        assert decision.client_key == "partner-1"


class TestLimiterContract:
    def test_default_permits_and_window(self) -> None:
        guard, limiter = _guard(routes=[RateLimitRoute("/api/orders")])
        guard.check("/api/orders", _headers(), ip="1.2.3.4")
        key, permits, window = limiter.calls[0]
        assert permits == 50
        assert window == 1

    def test_route_overrides_permits_and_window(self) -> None:
        route = RateLimitRoute("/api/orders", permits_per_second=3, window_seconds=10)
        guard, limiter = _guard(routes=[route])
        guard.check("/api/orders", _headers(), ip="1.2.3.4")
        assert limiter.calls[0][1:] == (3, 10)

    def test_redis_key_format(self) -> None:
        guard, limiter = _guard(routes=[RateLimitRoute("/api/orders")])
        guard.check("/api/orders", _headers(), ip="1.2.3.4")
        assert limiter.calls[0][0] == "richie:web:rate-limit:partner-1:/api/orders"

    def test_custom_key_prefix(self) -> None:
        guard, limiter = _guard(routes=[RateLimitRoute("/a")], key_prefix="tenant:rl")
        guard.check("/a", _headers(), ip="1.2.3.4")
        assert limiter.calls[0][0].startswith("tenant:rl:")

    def test_key_includes_pattern_so_routes_do_not_share_quota(self) -> None:
        routes = [RateLimitRoute("/a"), RateLimitRoute("/b")]
        guard, limiter = _guard(routes=routes)
        guard.check("/a", _headers(), ip="1.2.3.4")
        guard.check("/b", _headers(), ip="1.2.3.4")
        assert limiter.calls[0][0] != limiter.calls[1][0]

    def test_none_limiter_rejected(self) -> None:
        with pytest.raises(ValueError):
            RateLimitGuard(None, RateLimitProperties(), IpClientKeyResolver())


class TestDenyResponse:
    def test_rate_limited_decision_defaults(self) -> None:
        guard, _ = _guard(limiter=FakeLimiter(allow=False), routes=[RateLimitRoute("/api/orders")])
        decision = guard.check("/api/orders", _headers(), ip="1.2.3.4")
        assert decision is not None and not decision.allowed
        assert decision.reason == "rate_limited"
        assert decision.status == 429
        assert decision.code == "RATE_LIMITED"
        assert decision.message == "请求过于频繁，请稍后再试 (key=partner-1)"
        assert decision.client_key == "partner-1"

    def test_route_overrides_deny_response(self) -> None:
        route = RateLimitRoute(
            "/api/orders",
            deny_status=503,
            deny_code="SLOW_DOWN",
            deny_message="慢一点 (key={key})",
            deny_headers={"Retry-After": "30"},
        )
        guard, _ = _guard(limiter=FakeLimiter(allow=False), routes=[route])
        decision = guard.check("/api/orders", _headers(), ip="1.2.3.4")
        assert decision is not None
        assert decision.status == 503
        assert decision.code == "SLOW_DOWN"
        assert decision.message == "慢一点 (key=partner-1)"
        assert decision.headers == {"Retry-After": "30"}

    def test_message_without_key_placeholder(self) -> None:
        route = RateLimitRoute("/a", deny_message="too many")
        guard, _ = _guard(limiter=FakeLimiter(allow=False), routes=[route])
        decision = guard.check("/a", _headers(), ip="1.2.3.4")
        assert decision is not None
        assert decision.message == "too many"

    def test_properties_level_headers_apply(self) -> None:
        guard, _ = _guard(
            limiter=FakeLimiter(allow=False),
            routes=[RateLimitRoute("/a")],
            deny_headers={"X-Limit": "1"},
        )
        decision = guard.check("/a", _headers(), ip="1.2.3.4")
        assert decision is not None
        assert decision.headers == {"X-Limit": "1"}


class TestValidation:
    @pytest.mark.parametrize(
        "kwargs",
        [
            {"pattern": ""},
            {"pattern": "/a", "permits_per_second": 0},
            {"pattern": "/a", "window_seconds": 0},
            {"pattern": "/a", "window_seconds": -1},
        ],
    )
    def test_invalid_route_rejected(self, kwargs) -> None:
        with pytest.raises(ValueError):
            RateLimitRoute(**kwargs)

    def test_blank_pattern_rejected(self) -> None:
        with pytest.raises(ValueError):
            RateLimitRoute("   ")

    @pytest.mark.parametrize(
        "overrides",
        [
            {"permits_per_second": 0},
            {"window_seconds": 0},
            {"max_client_key_length": 0},
            {"gateway_identity_header": "  "},
        ],
    )
    def test_invalid_properties_rejected(self, overrides) -> None:
        with pytest.raises(ValueError):
            RateLimitProperties(**overrides)

class TestJavaDefaults:
    def test_defaults_match_java(self) -> None:
        props = RateLimitProperties()
        assert props.key_prefix == "richie:web:rate-limit"
        assert props.permits_per_second == 50
        assert props.window_seconds == 1
        assert props.deny_status == 429
        assert props.deny_code == "RATE_LIMITED"
        assert props.require_gateway_identity is True
        assert props.gateway_identity_header == "X-Forwarded-From-Gateway"
        assert props.max_client_key_length == 256

    def test_decision_allow_shape(self) -> None:
        guard, _ = _guard(routes=[RateLimitRoute("/a")])
        decision = guard.check("/a", _headers(), ip="1.2.3.4")
        assert decision is not None
        assert decision.allowed
        assert decision.status == 401  # 无意义字段，仅确认默认存在
        assert decision.client_key == "partner-1"
        assert decision.pattern == "/a"
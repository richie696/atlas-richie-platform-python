"""分布式限流决策（对位 Java `DistributedRateLimitInterceptor` 的算法部分）。

Java 的拦截器依赖 Spring 的 `WebRequestContext` / `AntPathMatcher` /
`ApiResult`；这里抽出可独立测试的纯决策核心：路由匹配（精确优先、
Ant 模式次之）→ 网关身份检查 → client key 解析与校验 → Redis 键构造 →
`LimiterOps.try_acquire`。驱动由调用方注入（cache-redis 的
`RedisLimiterManager` 已实现同一契约），本模块零第三方依赖。

拒绝响应可逐路由覆盖 status/code/message/headers；`{key}` 占位符替换为实际
client key。未匹配任何路由返回 None（放行且不触碰限流器）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Mapping, Protocol, runtime_checkable

def ant_pattern_to_regex(pattern: str) -> re.Pattern[str]:
    """Ant 风格路径模式：`**` 跨目录、`*`/`?` 不跨 `/`、`{var}` 为一段。"""
    escaped = re.escape(pattern).replace(r"\*\*", "\x00").replace(r"\*", "\x01")
    escaped = escaped.replace(r"\?", "\x02")
    for token, replacement in (("\x00", ".*"), ("\x01", "[^/]*"), ("\x02", "[^/]")):
        escaped = escaped.replace(token, replacement)
    escaped = re.sub(
        r"\\\{[^/}]+\\\}", "[^/]+", escaped
    )
    return re.compile(f"^{escaped}$")


@dataclass(frozen=True, slots=True)
class RateLimitRoute:
    pattern: str
    permits_per_second: int = 50
    window_seconds: int | None = None
    deny_status: int | None = None
    deny_code: str | None = None
    deny_message: str | None = None
    deny_headers: Mapping[str, str] | None = None

    def __post_init__(self) -> None:
        if not self.pattern or not self.pattern.strip():
            raise ValueError("route pattern must not be blank")
        if self.permits_per_second < 1:
            raise ValueError("permits_per_second must be >= 1")
        if self.window_seconds is not None and self.window_seconds < 1:
            raise ValueError("window_seconds must be >= 1")

    @property
    def is_exact(self) -> bool:
        return not any(c in self.pattern for c in "*?{")


@dataclass(frozen=True, slots=True)
class RateLimitProperties:
    key_prefix: str = "richie:web:rate-limit"
    permits_per_second: int = 50
    window_seconds: int = 1
    deny_status: int = 429
    deny_code: str = "RATE_LIMITED"
    deny_message: str = "请求过于频繁，请稍后再试 (key={key})"
    deny_headers: Mapping[str, str] = field(default_factory=dict)
    require_gateway_identity: bool = True
    gateway_identity_header: str = "X-Forwarded-From-Gateway"
    max_client_key_length: int = 256
    routes: tuple[RateLimitRoute, ...] = ()

    def __post_init__(self) -> None:
        if self.permits_per_second < 1:
            raise ValueError("permits_per_second must be >= 1")
        if self.window_seconds < 1:
            raise ValueError("window_seconds must be >= 1")
        if self.max_client_key_length < 1:
            raise ValueError("max_client_key_length must be >= 1")
        if not self.gateway_identity_header.strip():
            raise ValueError("gateway_identity_header must not be blank")
        object.__setattr__(self, "routes", tuple(self.routes or ()))


@runtime_checkable
class RateLimiter(Protocol):
    """`LimiterOps` 的最小面：固定窗口计数。"""

    def try_acquire(self, key: str, max_count: int, window_seconds: int) -> bool: ...


@runtime_checkable
class ClientKeyResolver(Protocol):
    def resolve(self, method: str, path: str, headers: Mapping[str, str], ip: str | None) -> str | None: ...


class HeaderClientKeyResolver:
    """Client key 来自指定 header（对位 Java `HeaderBasedKeyResolver`）。"""

    def __init__(self, header: str = "x-client-key") -> None:
        self._header = header.lower()

    def resolve(self, method: str, path: str, headers: Mapping[str, str], ip: str | None) -> str | None:
        value = headers.get(self._header)
        return value.strip() if value else None


class IpClientKeyResolver:
    """Client key 取请求 IP（对位 Java `IpDimension`）。"""

    def resolve(self, method: str, path: str, headers: Mapping[str, str], ip: str | None) -> str | None:
        return ip


class CompositeKeyResolver:
    """依次尝试多个来源，取第一个非空结果（对位 Java `CompositeKeyResolver`）。"""

    def __init__(self, *resolvers: ClientKeyResolver) -> None:
        self._resolvers = tuple(resolvers)

    def resolve(self, method: str, path: str, headers: Mapping[str, str], ip: str | None) -> str | None:
        for resolver in self._resolvers:
            value = resolver.resolve(method, path, headers, ip)
            if value:
                return value
        return None


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    """`reason == "rate_limited"` 之外的拒绝均为 4xx 未识别；None 表示放行。"""

    reason: str
    status: int = 401
    code: str = ""
    message: str = ""
    headers: Mapping[str, str] = field(default_factory=dict)
    client_key: str | None = None
    pattern: str | None = None

    @property
    def allowed(self) -> bool:
        return self.reason == "allow"


class RateLimitGuard:
    def __init__(
        self,
        limiter: RateLimiter,
        properties: RateLimitProperties,
        key_resolver: ClientKeyResolver,
    ) -> None:
        if limiter is None:
            raise ValueError("limiter must not be None")
        self._limiter = limiter
        self._props = properties
        self._resolver = key_resolver
        self._compiled = {
            route.pattern: ant_pattern_to_regex(route.pattern)
            for route in properties.routes
            if not route.is_exact
        }

    @property
    def properties(self) -> RateLimitProperties:
        return self._props

    def check(
        self,
        path: str,
        headers: Mapping[str, str],
        *,
        method: str = "GET",
        ip: str | None = None,
    ) -> RateLimitDecision | None:
        """None = 该路径未配置限流路由，直接放行且不触碰 Redis。"""
        # ASGI 的 header_map 已小写；独立使用时统一一次，让解析器不依赖调用方大小写。
        headers = {k.lower(): v for k, v in headers.items()}
        route = self._match_route(path)
        if route is None:
            return None
        if self._props.require_gateway_identity:
            identity = headers.get(self._identity_header())
            if not identity or not identity.strip():
                return RateLimitDecision(
                    reason="gateway_identity_missing", status=401, pattern=route.pattern
                )
        client_key = self._resolver.resolve(method, path, headers, ip)
        if not client_key or not client_key.strip():
            return RateLimitDecision(
                reason="client_unidentified", status=401, pattern=route.pattern
            )
        if len(client_key) > self._props.max_client_key_length:
            return RateLimitDecision(
                reason="client_unidentified", status=401, pattern=route.pattern
            )
        permits = route.permits_per_second
        window = (
            route.window_seconds
            if route.window_seconds is not None
            else self._props.window_seconds
        )
        key = self.build_redis_key(client_key, route.pattern)
        if not self._limiter.try_acquire(key, permits, window):
            return self._rate_limited(client_key, route)
        return RateLimitDecision(reason="allow", client_key=client_key, pattern=route.pattern)

    def _identity_header(self) -> str:
        return self._props.gateway_identity_header.lower()

    def _match_route(self, path: str) -> RateLimitRoute | None:
        if not path:
            return None
        for route in self._props.routes:
            if route.is_exact and path == route.pattern:
                return route
        for route in self._props.routes:
            if not route.is_exact and self._compiled[route.pattern].match(path):
                return route
        return None

    def build_redis_key(self, client_key: str, pattern: str) -> str:
        return f"{self._props.key_prefix}:{client_key}:{pattern}"

    def _rate_limited(self, client_key: str, route: RateLimitRoute) -> RateLimitDecision:
        status = route.deny_status or self._props.deny_status
        code = route.deny_code or self._props.deny_code
        template = route.deny_message or self._props.deny_message
        message = template.replace("{key}", client_key)
        headers = dict(route.deny_headers or self._props.deny_headers or {})
        return RateLimitDecision(
            reason="rate_limited",
            status=status,
            code=code,
            message=message,
            headers=headers,
            client_key=client_key,
            pattern=route.pattern,
        )


__all__ = [
    "ant_pattern_to_regex",
    "RateLimitRoute",
    "RateLimitProperties",
    "RateLimiter",
    "ClientKeyResolver",
    "HeaderClientKeyResolver",
    "IpClientKeyResolver",
    "CompositeKeyResolver",
    "RateLimitDecision",
    "RateLimitGuard",
]
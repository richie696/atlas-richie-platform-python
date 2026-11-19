"""防护拦截器：把 web-protection 的 guard 包成 SPI 拦截器（对位 Java `protection` 包）。

Java 侧每个防护拦截器自己持有一份「拒绝语义」（状态码 / 原因 / 响应头 /
body 模板），并把决策写进统一决策事件；Python 侧沿用同一形状：

- deny → 写决策 → 写响应头 → 短路标记 → **不调** `chain.proceed(ctx)`
- allow → 调 `chain.proceed(ctx)`

短路不是抛异常（与 Java 一致）；抛出的异常由适配层兜底成 5xx。

与 Java 拦截器的对应关系：

| Python 拦截器 | Java 对应 |
| --- | --- |
| `IpBlacklistInterceptor` | `AnomalyDetectionInterceptor` 的 IP 黑名单分支 |
| `BotUserAgentInterceptor` | `AnomalyDetectionInterceptor` 的 bot UA 分支 |
| `GatewayBypassInterceptor` | `PlatformProtectionInterceptor` 的网关身份分支 |
| `RequestSizeInterceptor` | `PlatformProtectionInterceptor` 的体积分支 |
| `LongLivedBypassInterceptor` | `LongLivedPathBypass`（由 `PlatformProtectionInterceptor` 置位） |
| `LoginLockInterceptor` | `BruteForceInterceptor` |
| `SignatureInterceptor` | `ApiSignatureInterceptor` |
| `IdempotencyInterceptor` | `business.IdempotencyInterceptor` |
| `RateLimitInterceptor` | `web-rate-limiter.DistributedRateLimitInterceptor` |

Java 侧还有 `CircuitBreakerInterceptor`（熔断），不在本轮范围：熔断依赖
熔断器状态机，不属于 web-protection 的请求级 guard。

长连接旁路
    长连接拦截器只负责在 ctx 上打标志，后续请求级拦截器**自查**该标志后跳过
    —— 与 Java 的 attribute 自查模式一致，也与改造前「长连接直接放行」的
    行为一致（IP 黑名单仍先于长连接判定生效）。
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping

from .guards import ApiSignatureVerifier, RequestSizeGuard
from .idempotency import IdempotencyGuard, LongLivedPathBypass
from .matchers import BotUserAgentMatcher, IpBlacklistEntry
from .rate_limit import RateLimitGuard
from .spi import (
    CLIENT_IP_ATTRIBUTE,
    DECISION_ATTRIBUTE,
    GATEWAY_BYPASS_ATTRIBUTE,
    GATEWAY_ID_ATTRIBUTE,
    LOGIN_KEY_ATTRIBUTE,
    LONG_LIVED_ATTRIBUTE,
    WebDecisionSink,
    WebFilterDecision,
    WebInterceptorChain,
    WebRequestContext,
)
from .trackers import LoginAttemptTracker

BodyRenderer = Callable[[int, str], str]


def default_deny_body(reason: str) -> str:
    """默认拒绝 body：`{"error": reason}`。"""
    return json.dumps({"error": reason}, ensure_ascii=False)


def _default_renderer(status: int, reason: str) -> str:
    """默认 body 渲染器（与适配层的渲染器同签名）。"""
    return default_deny_body(reason)


def header_map_from_context(ctx: WebRequestContext) -> dict[str, str]:
    """把 ctx 的多值 header 压成单值 map（同名后者覆盖前者）。

    与 ASGI 适配层 `header_map()` 的单值语义保持一致（后来的同名 header
    覆盖先前的）；注意 ctx 自身的 `header()` 返回的是**第一个**值（与 Java
    的 `getHeader()` 一致），两者在重复 header 场景下取值不同。
    """
    result: dict[str, str] = {}
    for name in ctx.header_names():
        values = ctx.headers(name)
        if values:
            result[name] = values[-1]
    return result


def is_long_lived(ctx: WebRequestContext) -> bool:
    """当前请求是否命中长连接旁路。"""
    return bool(ctx.attribute(LONG_LIVED_ATTRIBUTE))


class ProtectionInterceptor:
    """拦截器基类：统一 deny 的三步（决策 → 响应头 → 短路）。

    子类只需在判定拒绝时调用 `_deny_with_reason()` 或 `_deny()`，
    不用自己拼短路逻辑。
    """

    def __init__(
        self,
        *,
        decision_sink: WebDecisionSink | None = None,
        body_renderer: BodyRenderer | None = None,
    ) -> None:
        self._sink = decision_sink
        self._renderer = body_renderer or _default_renderer

    @property
    def decision_sink(self) -> WebDecisionSink | None:
        return self._sink

    def _deny(
        self,
        ctx: WebRequestContext,
        decision: WebFilterDecision,
        body: str,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        """统一的拒绝路径：写决策 → 写响应头 → 标记短路 → 投递决策事件。"""
        ctx.set_attribute(DECISION_ATTRIBUTE, decision)
        for name, value in (headers or {}).items():
            ctx.add_response_header(name, str(value))
        ctx.mark_short_circuit(decision.status, body)
        if self._sink is not None:
            self._sink.publish(decision)

    def _deny_with_reason(
        self,
        ctx: WebRequestContext,
        status: int,
        reason: str,
        key: str | None = None,
        headers: Mapping[str, str] | None = None,
        body: str | None = None,
    ) -> None:
        """按 `WebFilterDecision` 的四字段构造决策并拒绝。"""
        decision = WebFilterDecision(type(self).__name__, key, status, reason)
        self._deny(ctx, decision, self._renderer(status, reason) if body is None else body, headers)


class IpBlacklistInterceptor(ProtectionInterceptor):
    """IP / CIDR 黑名单（对位 Java `AnomalyDetectionInterceptor` 的 IP 分支）。"""

    def __init__(
        self,
        entries: Iterable[IpBlacklistEntry],
        *,
        deny_status: int = 403,
        decision_sink: WebDecisionSink | None = None,
        body_renderer: BodyRenderer | None = None,
    ) -> None:
        super().__init__(decision_sink=decision_sink, body_renderer=body_renderer)
        self._entries = tuple(entries or ())
        self._deny_status = deny_status

    def intercept(self, ctx: WebRequestContext, chain: WebInterceptorChain) -> None:
        client_ip = ctx.attribute(CLIENT_IP_ATTRIBUTE)
        if client_ip and any(entry.matches(client_ip) for entry in self._entries):
            self._deny_with_reason(ctx, self._deny_status, "ip_blacklisted")
            return
        chain.proceed(ctx)


class GatewayBypassInterceptor:
    """把网关身份写进 ctx（对位 Java `PlatformProtectionInterceptor`）。

    Java 侧该逻辑硬编码在 `PlatformProtectionInterceptor` 里且不可关闭；
    Python 侧把头名做成可配置（默认头名与 Java 契约一致），命中后在 ctx 上
    置 `GATEWAY_BYPASS_ATTRIBUTE` 与 `GATEWAY_ID_ATTRIBUTE`，由需要
    旁路的拦截器自查该标志。
    """

    def __init__(self, header_name: str | None = "x-forwarded-from-gateway") -> None:
        self._header = header_name.lower() if header_name else None

    def intercept(self, ctx: WebRequestContext, chain: WebInterceptorChain) -> None:
        if self._header is not None:
            gateway_id = ctx.header(self._header)
            if gateway_id is not None:
                ctx.set_attribute(GATEWAY_BYPASS_ATTRIBUTE, True)
                ctx.set_attribute(GATEWAY_ID_ATTRIBUTE, gateway_id)
        chain.proceed(ctx)


class LongLivedBypassInterceptor:
    """长连接（SSE / WebSocket）路径旁路（对位 Java `LongLivedPathBypass`）。

    只打标志，不拒绝；后续请求级拦截器自查该标志后跳过。
    """

    def __init__(self, bypass: LongLivedPathBypass) -> None:
        self._bypass = bypass

    def intercept(self, ctx: WebRequestContext, chain: WebInterceptorChain) -> None:
        if self._bypass.matches(ctx.path):
            ctx.set_attribute(LONG_LIVED_ATTRIBUTE, True)
        chain.proceed(ctx)


class BotUserAgentInterceptor(ProtectionInterceptor):
    """bot User-Agent 拦截（对位 Java `AnomalyDetectionInterceptor` 的 bot 分支）。"""

    def __init__(
        self,
        matchers: Iterable[BotUserAgentMatcher],
        *,
        deny_status: int = 403,
        decision_sink: WebDecisionSink | None = None,
        body_renderer: BodyRenderer | None = None,
    ) -> None:
        super().__init__(decision_sink=decision_sink, body_renderer=body_renderer)
        self._matchers = tuple(matchers or ())
        self._deny_status = deny_status

    def intercept(self, ctx: WebRequestContext, chain: WebInterceptorChain) -> None:
        if is_long_lived(ctx):
            chain.proceed(ctx)
            return
        user_agent = ctx.header("user-agent")
        if any(matcher.matches(user_agent) for matcher in self._matchers):
            self._deny_with_reason(ctx, self._deny_status, "bot_detected")
            return
        chain.proceed(ctx)


class RequestSizeInterceptor(ProtectionInterceptor):
    """请求体积拦截（对位 Java `PlatformProtectionInterceptor` 的体积分支）。

    直接复用 `RequestSizeGuard`：ctx 满足它的 `RequestContext` 协议
    （`header` / `header_names` / `headers`），无需额外适配层。
    """

    def __init__(
        self,
        guard: RequestSizeGuard,
        *,
        decision_sink: WebDecisionSink | None = None,
        body_renderer: BodyRenderer | None = None,
    ) -> None:
        super().__init__(decision_sink=decision_sink, body_renderer=body_renderer)
        self._guard = guard

    def intercept(self, ctx: WebRequestContext, chain: WebInterceptorChain) -> None:
        if is_long_lived(ctx):
            chain.proceed(ctx)
            return
        decision = self._guard.check(ctx)
        if decision is not None:
            self._deny_with_reason(ctx, decision.status, decision.reason)
            return
        chain.proceed(ctx)


class LoginLockInterceptor(ProtectionInterceptor):
    """登录锁定检查（对位 Java `BruteForceInterceptor`）。

    锁定 key 由适配层算好后写进 ctx（`LOGIN_KEY_ATTRIBUTE`），拦截器只读
    ctx，不依赖任何框架类型。
    """

    def __init__(
        self,
        tracker: LoginAttemptTracker,
        *,
        login_paths: Iterable[str] = (),
        deny_status: int = 429,
        decision_sink: WebDecisionSink | None = None,
        body_renderer: BodyRenderer | None = None,
    ) -> None:
        super().__init__(decision_sink=decision_sink, body_renderer=body_renderer)
        self._tracker = tracker
        self._login_paths = frozenset(login_paths or ())
        self._deny_status = deny_status

    def intercept(self, ctx: WebRequestContext, chain: WebInterceptorChain) -> None:
        if is_long_lived(ctx):
            chain.proceed(ctx)
            return
        if ctx.path not in self._login_paths:
            chain.proceed(ctx)
            return
        key = ctx.attribute(LOGIN_KEY_ATTRIBUTE)
        if key is None:
            chain.proceed(ctx)
            return
        if not self._tracker.is_locked(key):
            chain.proceed(ctx)
            return
        self._deny_with_reason(ctx, self._deny_status, "account_locked", key=key)


class IdempotencyInterceptor(ProtectionInterceptor):
    """幂等防重拦截（对位 Java `business.IdempotencyInterceptor`）。"""

    def __init__(
        self,
        guard: IdempotencyGuard,
        *,
        decision_sink: WebDecisionSink | None = None,
        body_renderer: BodyRenderer | None = None,
    ) -> None:
        super().__init__(decision_sink=decision_sink, body_renderer=body_renderer)
        self._guard = guard

    def intercept(self, ctx: WebRequestContext, chain: WebInterceptorChain) -> None:
        if is_long_lived(ctx):
            chain.proceed(ctx)
            return
        decision = self._guard.check(header_map_from_context(ctx))
        if decision is not None:
            self._deny_with_reason(ctx, decision.status, decision.reason, key=decision.key)
            return
        chain.proceed(ctx)


class RateLimitInterceptor(ProtectionInterceptor):
    """分布式限流拦截（对位 Java `DistributedRateLimitInterceptor`）。

    与 Java 的差异：Java 的 `WebFilterDecision.rateLimitDeny()` 把 reason
    固定为 `rate_limit.exceeded`；Python 侧保留 guard 的细分原因
    （`rate_limited` / `gateway_identity_missing` /
    `client_unidentified`），便于区分「配额耗尽」与「身份缺失」。
    """

    def __init__(
        self,
        guard: RateLimitGuard,
        *,
        decision_sink: WebDecisionSink | None = None,
        body_renderer: BodyRenderer | None = None,
    ) -> None:
        super().__init__(decision_sink=decision_sink, body_renderer=body_renderer)
        self._guard = guard

    def intercept(self, ctx: WebRequestContext, chain: WebInterceptorChain) -> None:
        if is_long_lived(ctx):
            chain.proceed(ctx)
            return
        decision = self._guard.check(
            ctx.path,
            header_map_from_context(ctx),
            method=ctx.method,
            ip=ctx.attribute(CLIENT_IP_ATTRIBUTE),
        )
        if decision is None or decision.allowed:
            chain.proceed(ctx)
            return
        body = json.dumps(
            {"error": decision.code or decision.reason, "message": decision.message},
            ensure_ascii=False,
        )
        web_decision = WebFilterDecision(
            type(self).__name__, decision.client_key, decision.status, decision.reason
        )
        self._deny(ctx, web_decision, body, decision.headers)


class SignatureInterceptor(ProtectionInterceptor):
    """HMAC 签名校验拦截（对位 Java `ApiSignatureInterceptor`）。

    网关身份旁路读 `GATEWAY_BYPASS_ATTRIBUTE` 标志（由
    `GatewayBypassInterceptor` 置位）。
    """

    def __init__(
        self,
        verifier: ApiSignatureVerifier,
        *,
        client_key_header: str = "x-client-key",
        deny_status: int = 401,
        decision_sink: WebDecisionSink | None = None,
        body_renderer: BodyRenderer | None = None,
    ) -> None:
        super().__init__(decision_sink=decision_sink, body_renderer=body_renderer)
        self._verifier = verifier
        self._client_key_header = client_key_header.lower()
        self._deny_status = deny_status

    def intercept(self, ctx: WebRequestContext, chain: WebInterceptorChain) -> None:
        if is_long_lived(ctx):
            chain.proceed(ctx)
            return
        bypassed = bool(ctx.attribute(GATEWAY_BYPASS_ATTRIBUTE))
        decision = self._verifier.verify(
            method=ctx.method,
            path=ctx.path,
            client_key=ctx.header(self._client_key_header),
            timestamp=ctx.header("x-timestamp"),
            nonce=ctx.header("x-nonce"),
            signature=ctx.header("x-signature"),
            gateway_bypassed=bypassed,
        )
        if decision is None:
            chain.proceed(ctx)
            return
        self._deny_with_reason(
            ctx, self._deny_status, decision.reason, key=decision.client_key
        )


__all__ = [
    "BotUserAgentInterceptor",
    "BodyRenderer",
    "GatewayBypassInterceptor",
    "IdempotencyInterceptor",
    "IpBlacklistInterceptor",
    "LoginLockInterceptor",
    "LongLivedBypassInterceptor",
    "ProtectionInterceptor",
    "RateLimitInterceptor",
    "RequestSizeInterceptor",
    "SignatureInterceptor",
    "default_deny_body",
    "header_map_from_context",
    "is_long_lived",
]

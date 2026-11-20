"""ASGI middleware applying web-protection guards to incoming requests.

跨容器决策统一走 SPI 拦截器链，本模块是**唯一** ASGI 适配点（对位 Java 的
`InterceptingFilter`）：把 ASGI scope 装配成 `WebRequestContext`，驱动
`DefaultWebInterceptorChain`，短路则按 ctx 的状态 / 响应头 / body 写回。

检查顺序（cheap → expensive）与改造前一致：
trace 归一 → IP 黑名单 → 网关身份 → 长连接旁路 → bot UA → 请求体积 →
登录锁定 → 幂等 → 限流 → 签名 → app

trace 归一在最前（对位 Java 的 `OtelTracingInterceptor`，ORDER=50），让
`ctx.trace_id` 尽早可用；响应头 `X-Trace-Id` 在正常与短路两条路径都会写回。

登录失败学习（下游 2xx / 401 / 403 记成功或失败）仍是**后置副作用**：Java 侧
对应 Java 的 `RequestLifecycleHookInterceptor` —— 属 BACKLOG 的另一项，Python 侧暂留在适配层。

与 Java 的差异：
- Java 的网关身份旁路硬编码不可关；Python 侧保留可配置（默认头名与 Java 契约一致）
- Java 的决策经 HookBus 发布；Python 侧投递到可选的 `WebDecisionSink`
- Java 的限流决策 reason 固定 `rate_limit.exceeded`；Python 侧保留 guard 的细分原因
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Iterable, Sequence
from typing import Any
from urllib.parse import parse_qsl

from atlas_richie.web_protection import (
    ApiSignatureVerifier,
    BotUserAgentMatcher,
    IdempotencyGuard,
    IpBlacklistEntry,
    LongLivedPathBypass,
    LoginAttemptTracker,
    RateLimitGuard,
    RequestSizeGuard,
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
    default_deny_body as _default_deny_body_text,
)
from atlas_richie.web_protection.spi import (
    CLIENT_IP_ATTRIBUTE,
    LOGIN_KEY_ATTRIBUTE,
    DefaultWebInterceptorChain,
    MutableWebRequestContext,
    WebDecisionSink,
    WebInterceptor,
)
from atlas_richie.web_protection.tracing import TraceIdInterceptor

Message = dict[str, Any]
Scope = dict[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]

DEFAULT_LOGIN_PATHS = ("/login", "/api/user/login", "/oauth2/token")

# 拒绝 body 渲染器：适配层用 bytes，SPI 用 str（归一后写入 ctx）。
DenyRenderer = Callable[[int, str], bytes]


def header_map(scope: Scope) -> dict[str, str]:
    """ASGI headers are lowercase byte pairs; later duplicates win."""
    result: dict[str, str] = {}
    for name, value in scope.get("headers", []) or []:
        key = name.decode("latin-1").lower() if isinstance(name, bytes) else str(name).lower()
        val = value.decode("latin-1") if isinstance(value, bytes) else str(value)
        result[key] = val
    return result


def _header_multi_map(scope: Scope) -> dict[str, list[str]]:
    """ASGI headers → 多值 map，保留同名 header 的全部值。"""
    result: dict[str, list[str]] = {}
    for name, value in scope.get("headers", []) or []:
        key = name.decode("latin-1").lower() if isinstance(name, bytes) else str(name).lower()
        val = value.decode("latin-1") if isinstance(value, bytes) else str(value)
        result.setdefault(key, []).append(val)
    return result


def _query_params(scope: Scope) -> dict[str, list[str]]:
    """ASGI query string → 多值 map。"""
    raw = scope.get("query_string", b"") or b""
    if isinstance(raw, bytes):
        raw = raw.decode("latin-1")
    if not raw:
        return {}
    result: dict[str, list[str]] = {}
    for name, value in parse_qsl(raw, keep_blank_values=True):
        result.setdefault(name, []).append(value)
    return result


def client_ip(scope: Scope, headers: dict[str, str], *, trust_forwarded: bool = False) -> str | None:
    if trust_forwarded:
        forwarded = headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",", 1)[0].strip()
    client = scope.get("client")
    return client[0] if client else None


def default_deny_body(reason: str) -> bytes:
    return _default_deny_body_text(reason).encode("utf-8")


def _merge_platform_headers(message: Message, ctx: MutableWebRequestContext) -> Message:
    """把 ctx 上的平台响应头并入下游响应（同名以平台为准）。

    Java 侧 ctx 响应头只在**短路**路径写回 servlet 响应，正常路径靠容器层的
    `TraceIdInjectValve` 注入；Python 的 ASGI 中间件就是容器层，故在此补齐 ——
    否则正常响应的 `X-Trace-Id` 永远到不了客户端。

    同名以平台为准：线上看到的 `X-Trace-Id` 永远等于 `ctx.trace_id`，两者不
    分叉。平台头只有 trace 归一等少数几个，不会碰到应用自己的 content-* 头。
    """
    platform_headers = ctx.response_headers()
    if not platform_headers:
        return message
    headers = list(message.get("headers", []))
    for name, value in platform_headers.items():
        encoded_name = name.encode("latin-1", "replace")
        encoded_value = str(value).encode("utf-8")
        replaced = False
        for index, (existing_name, _) in enumerate(headers):
            decoded = (
                existing_name.decode("latin-1")
                if isinstance(existing_name, bytes)
                else str(existing_name)
            )
            if decoded.lower() == name.lower():
                headers[index] = (encoded_name, encoded_value)
                replaced = True
                break
        if not replaced:
            headers.append((encoded_name, encoded_value))
    merged = dict(message)
    merged["headers"] = headers
    return merged


def _as_text_renderer(renderer: Callable[[int, str], bytes]) -> Callable[[int, str], str]:
    """把适配层的 bytes 渲染器归一为 SPI 的 str 渲染器。

    SPI 侧的 body 是 str，适配层的渲染器返回 bytes。`surrogateescape` 是
    唯一能无损往返任意字节的编解码方式：decode 出的孤立代理码位在 encode 时
    还原成原字节，因此自定义渲染器的输出字节与改造前完全一致。
    """

    def _render(status: int, reason: str) -> str:
        body = renderer(status, reason)
        if isinstance(body, bytes):
            return body.decode("utf-8", "surrogateescape")
        return str(body)

    return _render


class ProtectionASGIMiddleware:
    """Wrap an ASGI app with the configured protections.

    每个 guard 都是可选的；一个都不配时中间件是透传。
    `deny_renderer(status, reason) -> bytes` 自定义拒绝 body。
    `decision_sink` 接收每次 deny 的 `WebFilterDecision` 事件。
    """

    def __init__(
        self,
        app: Callable[[Scope, Receive, Send], Awaitable[None]],
        *,
        ip_blacklist: Sequence[IpBlacklistEntry] = (),
        bot_matchers: Sequence[BotUserAgentMatcher] = (),
        size_guard: RequestSizeGuard | None = None,
        signature_verifier: ApiSignatureVerifier | None = None,
        rate_limit_guard: RateLimitGuard | None = None,
        idempotency_guard: IdempotencyGuard | None = None,
        long_lived_bypass: LongLivedPathBypass | None = None,
        login_tracker: LoginAttemptTracker | None = None,
        login_paths: Iterable[str] = DEFAULT_LOGIN_PATHS,
        login_key: Callable[[Scope, dict[str, str]], str | None] | None = None,
        client_key_header: str = "x-client-key",
        trust_forwarded: bool = False,
        gateway_bypass_header: str | None = "x-forwarded-from-gateway",
        deny_renderer: Callable[[int, str], bytes] | None = None,
        deny_status_ip: int = 403,
        deny_status_bot: int = 403,
        deny_status_signature: int = 401,
        deny_status_locked: int = 429,
        decision_sink: WebDecisionSink | None = None,
        enable_trace_id: bool = True,
    ) -> None:
        self.app = app
        self._ip_blacklist = tuple(ip_blacklist)
        self._bot_matchers = tuple(bot_matchers)
        self._size_guard = size_guard
        self._signature = signature_verifier
        self._rate_limit = rate_limit_guard
        self._idempotency = idempotency_guard
        self._long_lived = long_lived_bypass
        self._login_tracker = login_tracker
        self._login_paths = frozenset(login_paths)
        self._login_key = login_key or (lambda scope, headers: client_ip(scope, headers, trust_forwarded=trust_forwarded))
        self._client_key_header = client_key_header.lower()
        self._trust_forwarded = trust_forwarded
        self._gateway_bypass_header = gateway_bypass_header.lower() if gateway_bypass_header else None
        self._deny_renderer = deny_renderer or (lambda status, reason: default_deny_body(reason))
        self._deny_status_ip = deny_status_ip
        self._deny_status_bot = deny_status_bot
        self._deny_status_signature = deny_status_signature
        self._deny_status_locked = deny_status_locked
        self._decision_sink = decision_sink
        self._enable_trace_id = enable_trace_id
        self._interceptors = self._build_interceptors()

    # ───────────────────────── 拦截器链装配 ─────────────────────────

    def _build_interceptors(self) -> tuple[WebInterceptor, ...]:
        """按注册顺序装配拦截器链（cheap → expensive）。

        顺序与改造前的内联检查顺序逐项对齐，见模块 docstring。
        """
        renderer = _as_text_renderer(self._deny_renderer)
        sink = self._decision_sink
        interceptors: list[WebInterceptor] = []
        if self._enable_trace_id:
            # Java ORDER=50：trace 归一必须最早，后续拦截器才能读到 ctx.trace_id
            interceptors.append(TraceIdInterceptor())
        if self._ip_blacklist:
            interceptors.append(
                IpBlacklistInterceptor(
                    self._ip_blacklist,
                    deny_status=self._deny_status_ip,
                    decision_sink=sink,
                    body_renderer=renderer,
                )
            )
        if self._gateway_bypass_header is not None:
            interceptors.append(GatewayBypassInterceptor(self._gateway_bypass_header))
        if self._long_lived is not None:
            interceptors.append(LongLivedBypassInterceptor(self._long_lived))
        if self._bot_matchers:
            interceptors.append(
                BotUserAgentInterceptor(
                    self._bot_matchers,
                    deny_status=self._deny_status_bot,
                    decision_sink=sink,
                    body_renderer=renderer,
                )
            )
        if self._size_guard is not None:
            interceptors.append(
                RequestSizeInterceptor(self._size_guard, decision_sink=sink, body_renderer=renderer)
            )
        if self._login_tracker is not None:
            interceptors.append(
                LoginLockInterceptor(
                    self._login_tracker,
                    login_paths=self._login_paths,
                    deny_status=self._deny_status_locked,
                    decision_sink=sink,
                    body_renderer=renderer,
                )
            )
        if self._idempotency is not None:
            interceptors.append(
                IdempotencyInterceptor(self._idempotency, decision_sink=sink, body_renderer=renderer)
            )
        if self._rate_limit is not None:
            interceptors.append(
                RateLimitInterceptor(self._rate_limit, decision_sink=sink, body_renderer=renderer)
            )
        if self._signature is not None:
            interceptors.append(
                SignatureInterceptor(
                    self._signature,
                    client_key_header=self._client_key_header,
                    deny_status=self._deny_status_signature,
                    decision_sink=sink,
                    body_renderer=renderer,
                )
            )
        return tuple(interceptors)

    @property
    def interceptors(self) -> tuple[WebInterceptor, ...]:
        """当前装配的拦截器链（按执行顺序，只读）。"""
        return self._interceptors

    # ───────────────────────── 请求处理 ─────────────────────────

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = header_map(scope)
        path = scope.get("path", "")
        ip = client_ip(scope, headers, trust_forwarded=self._trust_forwarded)

        ctx = MutableWebRequestContext(
            method=scope.get("method", "GET"),
            path=path,
            headers=_header_multi_map(scope),
            query_params=_query_params(scope),
        )
        ctx.set_attribute(CLIENT_IP_ATTRIBUTE, ip)
        if self._login_tracker is not None:
            ctx.set_attribute(LOGIN_KEY_ATTRIBUTE, self._login_key(scope, headers))

        chain = DefaultWebInterceptorChain(self._interceptors)
        try:
            chain.proceed(ctx)

            if ctx.is_short_circuited:
                await self._write_short_circuit(send, ctx)
                return

            await self._call_app(scope, receive, send, ctx, path)
        finally:
            ctx.close()

    async def _call_app(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
        ctx: MutableWebRequestContext,
        path: str,
    ) -> None:
        """调用下游 app，并按需记录登录成功 / 失败。"""
        tracker = self._login_tracker
        key = ctx.attribute(LOGIN_KEY_ATTRIBUTE) if tracker is not None else None
        tracking = tracker is not None and key is not None and path in self._login_paths
        if not tracking and not ctx.response_headers():
            await self.app(scope, receive, send)
            return

        async def send_with_context(message: Message) -> None:
            if message.get("type") == "http.response.start":
                status = int(message.get("status", 200))
                ctx.set_response_status(status)
                if tracking:
                    if 200 <= status < 300:
                        tracker.record_success(key)
                    elif status in (401, 403):
                        tracker.record_failure(key)
                message = _merge_platform_headers(message, ctx)
            await send(message)

        await self.app(scope, receive, send_with_context)

    async def _write_short_circuit(self, send: Send, ctx: MutableWebRequestContext) -> None:
        """把短路响应写回：状态码 / 响应头 / body。"""
        status = ctx.response_status
        body_text = ctx.short_circuit_body
        raw = b"" if body_text is None else body_text.encode("utf-8", "surrogateescape")
        response_headers = ctx.response_headers()
        headers: list[tuple[bytes, bytes]] = []
        if body_text is not None and not any(
            name.lower() == "content-type" for name in response_headers
        ):
            headers.append((b"content-type", b"application/json; charset=utf-8"))
        for name, value in response_headers.items():
            headers.append((name.encode("latin-1", "replace"), str(value).encode("utf-8")))
        headers.append((b"content-length", str(len(raw)).encode("latin-1")))
        await send({
            "type": "http.response.start",
            "status": status,
            "headers": headers,
        })
        await send({"type": "http.response.body", "body": raw, "more_body": False})


__all__ = [
    "DEFAULT_LOGIN_PATHS",
    "ProtectionASGIMiddleware",
    "client_ip",
    "default_deny_body",
    "header_map",
]

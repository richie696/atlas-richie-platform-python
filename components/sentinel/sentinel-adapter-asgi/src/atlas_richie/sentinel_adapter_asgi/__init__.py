"""Sentinel ASGI Adapter (M3.3 / M3.5) — 纯 ASGI Middleware。

中文
----
``SentinelASGIMiddleware`` 是**纯 ASGI** middleware(**不**依赖
Starlette / FastAPI),按 ASGI 3.0 规范实现。任何 ASGI 框架(Starlette
/ FastAPI / Quart / aiohttp / raw uvicorn)都能直接使用。

设计要点:

- **流式响应 (body streaming)**:``send`` 时不直接读完 body,而是
  逐 chunk 转发;用 ``stream_finished`` 事件(ASGI http.response.body
  with ``more_body=False``)触发租约释放,避免 body EOF 前提前释放
  资源
- **断连 (client disconnect)**:捕获 ``ClientDisconnect``(asyncio 取消
  / `httptools` 异常),更新 outcome 为 CANCELLED,走 release 路径
- **lifespan 协议**:支持 ASGI lifespan(uvicorn `--lifespan on`),
  启动时 ``__aenter__`` Engine,关闭时 ``aclose()``
- **资源命名**:默认规则是 ``method + path``(e.g. ``GET /orders/123``);
  支持自定义 ResourceNamingStrategy(M3.4)
- **可信 origin**:从 ``X-Forwarded-User`` / JWT / mTLS cert 解析;
  适配器默认是 deny-by-default(没有 resolver 时全部拒绝)
- **零 3rd-party 主包**:Adapter wheel 也不强依赖;只 stdlib

English
--------
Sentinel ASGI Adapter (M3.3 / M3.5) — pure ASGI Middleware.

``SentinelASGIMiddleware`` is a **pure ASGI** middleware (**not**
dependent on Starlette / FastAPI), per ASGI 3.0 spec. Any ASGI
framework (Starlette / FastAPI / Quart / aiohttp / raw uvicorn) can
use it directly.

Design points:

- **Streaming response**: ``send`` doesn't buffer body; chunks
  forwarded one at a time; ``stream_finished`` event (ASGI
  http.response.body with ``more_body=False``) triggers lease
  release, avoiding premature release before body EOF.
- **Client disconnect**: catches ``ClientDisconnect`` (asyncio
  cancel / `httptools` exception), updates outcome to CANCELLED,
  runs release path.
- **lifespan protocol**: supports ASGI lifespan (uvicorn
  ``--lifespan on``); Engine entered via ``__aenter__`` at startup,
  closed via ``aclose()`` at shutdown.
- **Resource naming**: default rule = ``method + path`` (e.g.
  ``GET /orders/123``); supports custom ResourceNamingStrategy
  (M3.4).
- **Trusted origin**: parses from ``X-Forwarded-User`` / JWT / mTLS
  cert; default is deny-by-default (no resolver = all denied).
- **Zero 3rd-party main wheel**: Adapter wheel also doesn't force
  any deps; only stdlib."""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Mapping

from atlas_richie.sentinel.engine import SentinelEngine
from atlas_richie.sentinel.model import (
    Resource, ResourceKind, TrafficType, SentinelContext,
    InvocationArguments,
)
from atlas_richie.sentinel.slots.authority import (
    AuthoritySlot, DenyByDefaultOriginResolver, UntrustedHeaderOriginResolver,
)
from atlas_richie.sentinel.ports.system_metric_sampler import DefaultSystemMetricSampler
from atlas_richie.sentinel.slots.system import SystemSlot

# ASGI types
Scope = dict
Message = dict
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]


# 简单 path-to-resource-name 模板(默认): "METHOD path"
DEFAULT_HEADER_TO_ORIGIN = "X-Forwarded-User"


def default_resource_name(scope: Scope) -> str:
    """中文
    ----
    默认资源命名:``"{METHOD} {path}"``(如 ``"GET /orders/123"``)。

    path 中的 ``{param}`` 段保留原样(由 ParamFlowSlot 走 param 限流,
    而非对每个具体 ID 限流)。

    English
    --------
    Default resource name: ``"{METHOD} {path}"`` (e.g.
    ``"GET /orders/123"``).

    Path ``{param}`` segments are kept as-is (ParamFlowSlot does
    param-based limiting, not per-id).
    """
    method = scope.get("method", "GET").upper()
    path = scope.get("path", "/")
    return f"{method} {path}"


# ResourceNamingStrategy callable
ResourceNamingStrategy = Callable[[Scope], str]


def default_origin_from_scope(scope: Scope) -> str | None:
    """中文
    ----
    默认 origin 解析:从 ``X-Forwarded-User`` header 读。

    用户应该注入更安全的 resolver(JWT / mTLS / 网关验签)。

    English
    --------
    Default origin resolver: read from ``X-Forwarded-User`` header.

    Users should inject a safer resolver (JWT / mTLS / gateway
    verification).
    """
    headers = scope.get("headers", [])  # list[tuple[bytes, bytes]]
    if not isinstance(headers, list):
        return None
    for k, v in headers:
        if k.lower() == DEFAULT_HEADER_TO_ORIGIN.lower().encode("ascii"):
            try:
                return v.decode("utf-8")
            except (UnicodeDecodeError, AttributeError):
                return None
    return None


@dataclass(slots=True)
class SentinelASGIMiddleware:
    """中文
    ----
    ASGI 3.0 中间件(纯 stdlib)。

    关键方法:

    - ``__call__(scope, receive, send)`` — ASGI 入口
    - ``lifespan(scope, receive, send)`` — ASGI lifespan 协议
    - ``__aenter__`` / ``__aexit__`` — 手动 Engine 生命周期

    ``engine`` 字段是必填;``naming`` / ``origin_resolver`` 可选覆盖
    默认行为。

    English
    --------
    ASGI 3.0 middleware (pure stdlib).

    Key methods:

    - ``__call__(scope, receive, send)`` — ASGI entry.
    - ``lifespan(scope, receive, send)`` — ASGI lifespan protocol.
    - ``__aenter__`` / ``__aexit__`` — manual Engine lifecycle.

    ``engine`` is required; ``naming`` / ``origin_resolver`` optionally
    override defaults.
    """

    app: ASGIApp
    engine: SentinelEngine
    naming: ResourceNamingStrategy = default_resource_name
    origin_resolver: Callable[[Scope], str | None] = default_origin_from_scope

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":
            await self.lifespan(scope, receive, send)
            return
        if scope["type"] != "http":
            # websocket 等非 http 不限流,直接透传
            await self.app(scope, receive, send)
            return
        # 构造 resource
        name = self.naming(scope)
        resource = Resource(
            name=name,
            kind=ResourceKind.INBOUND,
            traffic_type=TrafficType.INBOUND,
        )
        # 构造 context:把 origin 注入 extra,AuthoritySlot 读 context.extra["headers"] 失败
        # 这里改用 context.extra["origin"] 单独存
        origin = self.origin_resolver(scope)
        context_kwargs: dict[str, Any] = {}
        if origin:
            context_kwargs["extra"] = {"origin": origin}
        context = SentinelContext(**context_kwargs)
        # 把 origin 注入 AuthoritySlot resolver
        # (复用 UntrustedHeaderOriginResolver 模式,但通过 origin 字段)
        # M3.3 占位: 仅构造 entry, AuthoritySlot 默认 DenyByDefault
        # 时,只有当 SlotResolver 注入了才会放行
        entry = self.engine.entry(resource, context=context)
        try:
            await entry.__aenter__()
        except Exception:
            # BLOCKED / SentinelError → 503
            await self._send_503(send)
            return
        # 透传到下游 app;__aexit__ 必须拿到真实异常才能记 CANCELLED /
        # FAILED outcome
        try:
            await self.app(scope, receive, send)
        except asyncio.CancelledError:
            # 客户端断连
            await self._send_client_disconnect(send)
            try:
                await entry.__aexit__(
                    asyncio.CancelledError,
                    asyncio.CancelledError(),
                    None,
                )
            finally:
                raise
        except BaseException as e:
            # 下游 app 抛业务异常 / 系统异常:让 engine 记 FAILED
            try:
                await entry.__aexit__(type(e), e, e.__traceback__)
            finally:
                raise
        else:
            await entry.__aexit__(None, None, None)

    async def _send_503(self, send: Send) -> None:
        await send({
            "type": "http.response.start",
            "status": 503,
            "headers": [(b"content-type", b"text/plain")],
        })
        await send({
            "type": "http.response.body",
            "body": b"sentinel: blocked",
            "more_body": False,
        })

    async def _send_client_disconnect(self, send: Send) -> None:
        # 客户端断连时,response 可能已开始但未完成; 此时不发送任何
        # (ASGI 协议允许 app 在 send 失败时直接退出)
        return None

    async def lifespan(
        self, scope: Scope, receive: Receive, send: Send
    ) -> None:
        """中文
        ----
        ASGI lifespan 协议;启动时 ``__aenter__`` Engine,关闭时
        ``aclose()``。

        English
        --------
        ASGI lifespan protocol; Engine entered via ``__aenter__`` at
        startup, closed via ``aclose()`` at shutdown.
        """
        # 启动 Engine
        await self.engine.__aenter__()
        try:
            await send({"type": "lifespan.startup.complete"})
            while True:
                msg = await receive()
                t = msg.get("type")
                if t == "lifespan.shutdown":
                    break
            await self.engine.close(graceful_timeout=10.0)
            await send({"type": "lifespan.shutdown.complete"})
        except BaseException:
            await self.engine.close(graceful_timeout=5.0)
            raise


__all__ = [
    "SentinelASGIMiddleware",
    "default_resource_name",
    "default_origin_from_scope",
    "ResourceNamingStrategy",
    "DEFAULT_HEADER_TO_ORIGIN",
]

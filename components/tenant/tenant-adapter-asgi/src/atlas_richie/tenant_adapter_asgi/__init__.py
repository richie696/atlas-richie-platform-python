"""ASGI 租户身份中间件（对位 Java `TenantIdentityFilter`）。

解析 → 拒绝或绑定 → 放行。绑定用 `TenantContext.bind`（contextvars，
请求结束自动恢复，异常也恢复——租户上下文不得泄漏到下一个请求）。

非 HTTP scope（lifespan / websocket）直接透传：websocket 的租户握手是
独立协议，不在本中间件范围。
"""

from __future__ import annotations

import json
from typing import Any, Awaitable, Callable, MutableMapping

from atlas_richie.tenant_core import TenantContext, TenantIdentityResolver

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]


def header_map(scope: Scope) -> dict[str, str]:
    return {
        k.decode("latin-1").lower(): v.decode("latin-1")
        for k, v in scope.get("headers", [])
    }


class TenantASGIMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        resolver: TenantIdentityResolver,
        *,
        deny_status: int = 401,
    ) -> None:
        if resolver is None:
            raise ValueError("resolver must not be None")
        self.app = app
        self._resolver = resolver
        self._deny_status = deny_status

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        resolution = self._resolver.resolve(path, header_map(scope))
        if resolution.denied:
            await self._deny(send, resolution.error_code, resolution.error_message)
            return
        if resolution.principal is None:
            await self.app(scope, receive, send)
            return
        with TenantContext.bind(resolution.principal):
            await self.app(scope, receive, send)

    async def _deny(self, send: Send, code: str | None, message: str | None) -> None:
        body = json.dumps(
            {"error": code or "TENANT_AUTH_MISSING_TOKEN", "message": message or ""},
            ensure_ascii=False,
        ).encode("utf-8")
        await send({
            "type": "http.response.start",
            "status": self._deny_status,
            "headers": [
                (b"content-type", b"application/json; charset=utf-8"),
                (b"content-length", str(len(body)).encode("latin-1")),
            ],
        })
        await send({"type": "http.response.body", "body": body, "more_body": False})


__all__ = ["TenantASGIMiddleware", "header_map"]
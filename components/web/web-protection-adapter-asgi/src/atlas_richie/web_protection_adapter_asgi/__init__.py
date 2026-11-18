"""ASGI middleware applying web-protection guards to incoming requests.

These guards are **server-side** protections, so the integration point is ASGI
middleware — not the `atlas_richie.http` interceptor chain, which is a client
facade. Pure ASGI: no Starlette or framework dependency.

Check order is cheap-to-expensive: IP blacklist, bot User-Agent, request size,
then HMAC signature. Login attempt tracking both gates locked keys and learns
from the downstream response status.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Iterable, Sequence
from typing import Any

from atlas_richie.web_protection import (
    ApiSignatureVerifier,
    BotUserAgentMatcher,
    IpBlacklistEntry,
    LoginAttemptTracker,
    RequestSizeGuard,
)

Message = dict[str, Any]
Scope = dict[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]

DEFAULT_LOGIN_PATHS = ("/login", "/api/user/login", "/oauth2/token")


def header_map(scope: Scope) -> dict[str, str]:
    """ASGI headers are lowercase byte pairs; later duplicates win."""
    result: dict[str, str] = {}
    for name, value in scope.get("headers", []) or []:
        key = name.decode("latin-1").lower() if isinstance(name, bytes) else str(name).lower()
        val = value.decode("latin-1") if isinstance(value, bytes) else str(value)
        result[key] = val
    return result


def client_ip(scope: Scope, headers: dict[str, str], *, trust_forwarded: bool = False) -> str | None:
    if trust_forwarded:
        forwarded = headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",", 1)[0].strip()
    client = scope.get("client")
    return client[0] if client else None


def default_deny_body(reason: str) -> bytes:
    return json.dumps({"error": reason}, ensure_ascii=False).encode("utf-8")


class ProtectionASGIMiddleware:
    """Wrap an ASGI app with the configured protections.

    Every guard is optional; with none configured the middleware is a passthrough.
    `deny_renderer(status, reason) -> bytes` customises the rejection body.
    """

    def __init__(
        self,
        app: Callable[[Scope, Receive, Send], Awaitable[None]],
        *,
        ip_blacklist: Sequence[IpBlacklistEntry] = (),
        bot_matchers: Sequence[BotUserAgentMatcher] = (),
        size_guard: RequestSizeGuard | None = None,
        signature_verifier: ApiSignatureVerifier | None = None,
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
    ) -> None:
        self.app = app
        self._ip_blacklist = tuple(ip_blacklist)
        self._bot_matchers = tuple(bot_matchers)
        self._size_guard = size_guard
        self._signature = signature_verifier
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

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = header_map(scope)
        path = scope.get("path", "")
        ip = client_ip(scope, headers, trust_forwarded=self._trust_forwarded)

        if ip is not None and any(entry.matches(ip) for entry in self._ip_blacklist):
            await self._deny(send, self._deny_status_ip, "ip_blacklisted")
            return

        user_agent = headers.get("user-agent")
        if any(matcher.matches(user_agent) for matcher in self._bot_matchers):
            await self._deny(send, self._deny_status_bot, "bot_detected")
            return

        if self._size_guard is not None:
            decision = self._size_guard.check(_ScopeRequestContext(headers))
            if decision is not None:
                await self._deny(send, decision.status, decision.reason)
                return

        is_login_path = path in self._login_paths
        login_key = self._login_key(scope, headers) if self._login_tracker is not None else None
        if self._login_tracker is not None and login_key is not None:
            if self._login_tracker.is_locked(login_key):
                await self._deny(send, self._deny_status_locked, "account_locked")
                return

        if self._signature is not None:
            bypassed = (
                self._gateway_bypass_header is not None
                and self._gateway_bypass_header in headers
            )
            decision = self._signature.verify(
                method=scope.get("method", "GET"),
                path=path,
                client_key=headers.get(self._client_key_header),
                timestamp=headers.get("x-timestamp"),
                nonce=headers.get("x-nonce"),
                signature=headers.get("x-signature"),
                gateway_bypassed=bypassed,
            )
            if decision is not None:
                await self._deny(send, self._deny_status_signature, decision.reason)
                return

        if self._login_tracker is None or login_key is None or not is_login_path:
            await self.app(scope, receive, send)
            return

        tracker = self._login_tracker
        key = login_key

        async def send_tracking(message: Message) -> None:
            if message.get("type") == "http.response.start":
                status = int(message.get("status", 200))
                if 200 <= status < 300:
                    tracker.record_success(key)
                elif status in (401, 403):
                    tracker.record_failure(key)
            await send(message)

        await self.app(scope, receive, send_tracking)

    async def _deny(self, send: Send, status: int, reason: str) -> None:
        body = self._deny_renderer(status, reason)
        await send({
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json; charset=utf-8"),
                (b"content-length", str(len(body)).encode("latin-1")),
            ],
        })
        await send({"type": "http.response.body", "body": body, "more_body": False})


class _ScopeRequestContext:
    """Adapts ASGI headers to the `RequestContext` Protocol the size guard expects."""

    def __init__(self, headers: dict[str, str]) -> None:
        self._headers = headers

    def header(self, name: str) -> str | None:
        return self._headers.get(name.lower())

    def header_names(self) -> list[str]:
        return list(self._headers)

    def headers(self, name: str) -> list[str]:
        value = self._headers.get(name.lower())
        return [value] if value is not None else []


__all__ = [
    "DEFAULT_LOGIN_PATHS",
    "ProtectionASGIMiddleware",
    "client_ip",
    "default_deny_body",
    "header_map",
]

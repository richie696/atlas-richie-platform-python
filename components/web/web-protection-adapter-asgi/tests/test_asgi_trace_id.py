"""ASGI 适配层的 trace 归一端到端测试（`X-Trace-Id` 落线 + 链序）。"""

from __future__ import annotations

import asyncio
import re

import pytest

from atlas_richie.web_protection import IpBlacklistEntry, TraceIdParser
from atlas_richie.web_protection.tracing import TraceIdInterceptor
from atlas_richie.web_protection_adapter_asgi import ProtectionASGIMiddleware

pytestmark = pytest.mark.unit

TRACEPARENT = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
HEX32 = re.compile(r"^[0-9a-f]{32}$")


class _App:
    def __init__(self, status: int = 200, headers: list[tuple[bytes, bytes]] | None = None) -> None:
        self.status = status
        self.headers = headers or []
        self.calls = 0

    async def __call__(self, scope, receive, send) -> None:
        self.calls += 1
        await send({
            "type": "http.response.start",
            "status": self.status,
            "headers": list(self.headers),
        })
        await send({"type": "http.response.body", "body": b"ok", "more_body": False})


def _scope(path="/", method="GET", headers=None, client=("203.0.113.9", 1234)):
    return {
        "type": "http",
        "method": method,
        "path": path,
        "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
        "client": client,
        "query_string": b"",
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


def _headers(sent):
    start = next(m for m in sent if m["type"] == "http.response.start")
    return {k.decode().lower(): v.decode() for k, v in start["headers"]}


class TestChainOrder:
    def test_trace_interceptor_runs_first(self) -> None:
        """Java ORDER=50：trace 归一必须早于防护 A 组。"""
        middleware = ProtectionASGIMiddleware(
            _App(), ip_blacklist=[IpBlacklistEntry("0.0.0.0/0")]
        )
        names = [type(i).__name__ for i in middleware.interceptors]
        assert names[0] == "TraceIdInterceptor"
        assert names[1] == "IpBlacklistInterceptor"

    def test_trace_interceptor_can_be_disabled(self) -> None:
        middleware = ProtectionASGIMiddleware(_App(), enable_trace_id=False)
        names = [type(i).__name__ for i in middleware.interceptors]
        assert "TraceIdInterceptor" not in names

    def test_disabled_trace_leaves_no_response_header(self) -> None:
        middleware = ProtectionASGIMiddleware(_App(), enable_trace_id=False)
        sent = _call(middleware, _scope())
        assert "x-trace-id" not in _headers(sent)


class TestResponseHeader:
    def test_pass_through_response_carries_the_trace_id(self) -> None:
        middleware = ProtectionASGIMiddleware(_App())
        sent = _call(middleware, _scope())
        assert "x-trace-id" in _headers(sent)

    def test_traceparent_is_honored_end_to_end(self) -> None:
        middleware = ProtectionASGIMiddleware(_App())
        sent = _call(middleware, _scope(headers={"traceparent": TRACEPARENT}))
        assert _headers(sent)["x-trace-id"] == TRACE_ID

    def test_request_id_fallback_is_honored(self) -> None:
        middleware = ProtectionASGIMiddleware(_App())
        sent = _call(middleware, _scope(headers={"X-Request-Id": "client-trace-abc"}))
        trace_id = _headers(sent)["x-trace-id"]
        assert len(trace_id) == 32
        assert trace_id.startswith("client-trace-abc")

    def test_generated_trace_id_is_32_hex(self) -> None:
        middleware = ProtectionASGIMiddleware(_App())
        sent = _call(middleware, _scope())
        assert HEX32.match(_headers(sent)["x-trace-id"])

    def test_deny_response_also_carries_the_trace_id(self) -> None:
        middleware = ProtectionASGIMiddleware(
            _App(), ip_blacklist=[IpBlacklistEntry("0.0.0.0/0")]
        )
        sent = _call(middleware, _scope(headers={"traceparent": TRACEPARENT}))
        assert _headers(sent)["x-trace-id"] == TRACE_ID

    def test_application_headers_survive_the_merge(self) -> None:
        app = _App(headers=[(b"content-type", b"application/json"), (b"x-app", b"keep")])
        middleware = ProtectionASGIMiddleware(app)
        sent = _call(middleware, _scope())
        headers = _headers(sent)
        assert headers["content-type"] == "application/json"
        assert headers["x-app"] == "keep"
        assert "x-trace-id" in headers

    def test_platform_header_wins_over_the_application_one(self) -> None:
        """线上看到的 `X-Trace-Id` 永远等于 `ctx.trace_id`，两者不分叉。"""
        app = _App(headers=[(b"x-trace-id", b"app-owned")])
        middleware = ProtectionASGIMiddleware(app)
        sent = _call(middleware, _scope(headers={"traceparent": TRACEPARENT}))
        assert _headers(sent)["x-trace-id"] == TRACE_ID


class TestParserContract:
    def test_response_header_name_is_stable(self) -> None:
        assert TraceIdParser.RESPONSE_TRACE_ID_HEADER == "X-Trace-Id"

    def test_interceptor_is_the_shared_implementation(self) -> None:
        assert TraceIdInterceptor.__module__.startswith("atlas_richie.web_protection.")

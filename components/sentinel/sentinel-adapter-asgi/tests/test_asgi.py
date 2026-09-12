"""SentinelASGIMiddleware full coverage tests (M3.5).

中文
----
覆盖 PLANNING §M3.5 全部要求:

- **普通响应** (request → response.start + response.body) → SUCCEEDED
- **流式响应** (more_body=True 多 chunk) → SUCCEEDED,lease 在
  ``more_body=False`` 时释放
- **断连** (client disconnect / receive 抛 CancelledError) → CANCELLED
  outcome + lease 仍释放
- **取消** (asyncio task cancel) → CANCELLED outcome
- **业务异常** (downstream app raise) → FAILED outcome + lease 释放
- **lifespan 协议** (startup.complete + shutdown.complete) → Engine 正确
  进入 READY / SHUTDOWN
- **资源命名** (default + custom) → Resource.name 正确
- **origin 解析** (header + custom resolver) → context.extra["origin"]
  设置正确
- **BLOCKED 路径** (engine rejects) → 503 + sentinel: blocked body
- **websocket / 非 http 透传** (scope.type != "http") → 走 downstream

English
--------
SentinelASGIMiddleware full coverage tests (M3.5).

Covers PLANNING §M3.5 fully:

- **Normal response** (request → response.start + body) → SUCCEEDED.
- **Streaming response** (more_body=True multi-chunk) → SUCCEEDED,
  lease released on ``more_body=False``.
- **Client disconnect** (receive raises CancelledError) → CANCELLED
  outcome + lease still released.
- **Task cancellation** (asyncio task cancel) → CANCELLED outcome.
- **Business exception** (downstream app raises) → FAILED outcome +
  lease released.
- **Lifespan protocol** (startup.complete + shutdown.complete) →
  Engine correctly transitions to READY / SHUTDOWN.
- **Resource naming** (default + custom) → Resource.name correct.
- **Origin resolution** (header + custom resolver) →
  context.extra["origin"] set correctly.
- **BLOCKED path** (engine rejects) → 503 + ``sentinel: blocked`` body.
- **WebSocket / non-http passthrough** (scope.type != "http") → goes
  to downstream.
"""

from __future__ import annotations

import asyncio
import json
import unittest
from typing import Any
from unittest.mock import AsyncMock

import pytest

from atlas_richie.sentinel.engine import SentinelEngine
from atlas_richie.sentinel.errors import SentinelBlockedError
from atlas_richie.sentinel.model.enums import BlockReason
from atlas_richie.sentinel.model.outcome import OutcomeKind
from atlas_richie.sentinel.model.resource import Resource
from atlas_richie.sentinel_adapter_asgi import (
    DEFAULT_HEADER_TO_ORIGIN,
    SentinelASGIMiddleware,
    default_origin_from_scope,
    default_resource_name,
)


# ---------------------------------------------------------------------------
# ASGI test utilities
# ---------------------------------------------------------------------------


def _make_http_scope(
    method: str = "GET",
    path: str = "/",
    headers: list[tuple[bytes, bytes]] | None = None,
) -> dict[str, Any]:
    return {
        "type": "http",
        "method": method,
        "path": path,
        "headers": headers or [],
        "query_string": b"",
        "scheme": "http",
        "server": ("testserver", 80),
    }


def _make_lifespan_scope() -> dict[str, Any]:
    return {"type": "lifespan"}


class _MessageRecorder:
    """Captures all send() messages emitted by an ASGI app."""

    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []

    async def __call__(self, message: dict[str, Any]) -> None:
        self.messages.append(message)

    def body_chunks(self) -> list[bytes]:
        return [m.get("body", b"") for m in self.messages if m["type"] == "http.response.body"]

    def status(self) -> int | None:
        for m in self.messages:
            if m["type"] == "http.response.start":
                return m.get("status")
        return None

    def content_type(self) -> str | None:
        for m in self.messages:
            if m["type"] == "http.response.start":
                for k, v in m.get("headers", []):
                    if k.lower() == b"content-type":
                        return v.decode("latin-1")
        return None


async def _one_shot_receive(body: bytes = b"") -> dict[str, Any]:
    """Build a one-shot receive callable for http.request."""
    return {"type": "http.request", "body": body, "more_body": False}


# ---------------------------------------------------------------------------
# Downstream app fixtures
# ---------------------------------------------------------------------------


async def _ok_app(scope: dict, receive: Any, send: Any) -> None:
    """A minimal ASGI app that returns 200 OK with a JSON body."""
    # Drain the request body.
    while True:
        msg = await receive()
        if msg.get("type") == "http.request" and not msg.get("more_body"):
            break
    body = json.dumps({"hello": "world"}).encode("utf-8")
    await send({
        "type": "http.response.start",
        "status": 200,
        "headers": [(b"content-type", b"application/json")],
    })
    await send({
        "type": "http.response.body",
        "body": body,
        "more_body": False,
    })


async def _streaming_app(scope: dict, receive: Any, send: Any) -> None:
    """ASGI app that streams the body in 3 chunks."""
    # Drain request.
    while True:
        msg = await receive()
        if msg.get("type") == "http.request" and not msg.get("more_body"):
            break
    await send({
        "type": "http.response.start",
        "status": 200,
        "headers": [(b"content-type", b"text/plain")],
    })
    for chunk in (b"hello ", b"streaming ", b"world"):
        await send({
            "type": "http.response.body",
            "body": chunk,
            "more_body": True,
        })
    await send({
        "type": "http.response.body",
        "body": b"!",
        "more_body": False,
    })


async def _boom_app(scope: dict, receive: Any, send: Any) -> None:
    """ASGI app that raises after sending the response start."""
    await send({
        "type": "http.response.start",
        "status": 200,
        "headers": [(b"content-type", b"text/plain")],
    })
    raise RuntimeError("downstream boom")


async def _lifespan_app(scope: dict, receive: Any, send: Any) -> None:
    """A no-op downstream app (used in lifespan tests)."""
    pass


# ---------------------------------------------------------------------------
# SEN-ASGI-001: Normal response
# ---------------------------------------------------------------------------


class NormalResponseTest(unittest.IsolatedAsyncioTestCase):
    async def test_ok_response_passes_through(self) -> None:
        engine = SentinelEngine()
        async with engine:
            mw = SentinelASGIMiddleware(app=_ok_app, engine=engine)
            recorder = _MessageRecorder()
            await mw(
                _make_http_scope(method="GET", path="/orders"),
                _one_shot_receive,
                recorder,
            )
        self.assertEqual(recorder.status(), 200)
        self.assertEqual(recorder.content_type(), "application/json")
        self.assertEqual(b"".join(recorder.body_chunks()), b'{"hello": "world"}')

    async def test_engine_outcome_succeeded(self) -> None:
        engine = SentinelEngine()
        captured: dict[str, Any] = {}
        async with engine:
            mw = SentinelASGIMiddleware(app=_ok_app, engine=engine)
            recorder = _MessageRecorder()
            await mw(
                _make_http_scope(),
                _one_shot_receive,
                recorder,
            )
            captured["last"] = engine.last_outcome
        self.assertIsNotNone(captured["last"])
        self.assertEqual(captured["last"].kind, OutcomeKind.SUCCEEDED)

    async def test_in_flight_returns_to_zero_after_response(self) -> None:
        engine = SentinelEngine()
        async with engine:
            mw = SentinelASGIMiddleware(app=_ok_app, engine=engine)
            await mw(
                _make_http_scope(),
                _one_shot_receive,
                _MessageRecorder(),
            )
        self.assertEqual(engine.in_flight, 0)

    async def test_default_resource_name(self) -> None:
        # "GET /orders/123" is the default resource name.
        engine = SentinelEngine()
        captured: dict[str, Any] = {}
        async with engine:
            mw = SentinelASGIMiddleware(app=_ok_app, engine=engine)
            # Patch engine.entry to capture the resource name.
            original_entry = engine.entry

            def capturing_entry(resource: Resource, **kwargs: Any) -> Any:
                captured["name"] = resource.name
                return original_entry(resource, **kwargs)

            engine.entry = capturing_entry  # type: ignore[assignment]
            await mw(
                _make_http_scope(method="POST", path="/orders/123"),
                _one_shot_receive,
                _MessageRecorder(),
            )
        self.assertEqual(captured["name"], "POST /orders/123")

    def test_default_resource_name_helper(self) -> None:
        self.assertEqual(
            default_resource_name(_make_http_scope(method="GET", path="/x")),
            "GET /x",
        )

    async def test_custom_resource_naming(self) -> None:
        captured: dict[str, Any] = {}

        def custom_naming(scope: dict) -> str:
            return f"CUSTOM:{scope.get('path', '/')}"

        engine = SentinelEngine()
        async with engine:
            mw = SentinelASGIMiddleware(
                app=_ok_app, engine=engine, naming=custom_naming
            )
            original_entry = engine.entry

            def capturing_entry(resource: Resource, **kwargs: Any) -> Any:
                captured["name"] = resource.name
                return original_entry(resource, **kwargs)

            engine.entry = capturing_entry  # type: ignore[assignment]
            await mw(
                _make_http_scope(),
                _one_shot_receive,
                _MessageRecorder(),
            )
        self.assertEqual(captured["name"], "CUSTOM:/")


# ---------------------------------------------------------------------------
# SEN-ASGI-001: Streaming response
# ---------------------------------------------------------------------------


class StreamingResponseTest(unittest.IsolatedAsyncioTestCase):
    async def test_streaming_body_forwarded_in_order(self) -> None:
        engine = SentinelEngine()
        async with engine:
            mw = SentinelASGIMiddleware(app=_streaming_app, engine=engine)
            recorder = _MessageRecorder()
            await mw(
                _make_http_scope(),
                _one_shot_receive,
                recorder,
            )
        body_chunks = recorder.body_chunks()
        # 4 chunks total: 3 with more_body=True + 1 final.
        self.assertEqual(len(body_chunks), 4)
        self.assertEqual(b"".join(body_chunks), b"hello streaming world!")

    async def test_streaming_outcome_is_succeeded(self) -> None:
        engine = SentinelEngine()
        async with engine:
            mw = SentinelASGIMiddleware(app=_streaming_app, engine=engine)
            await mw(
                _make_http_scope(),
                _one_shot_receive,
                _MessageRecorder(),
            )
        self.assertEqual(engine.last_outcome.kind, OutcomeKind.SUCCEEDED)
        # Lease released (in_flight back to 0).
        self.assertEqual(engine.in_flight, 0)


# ---------------------------------------------------------------------------
# SEN-ASGI-001: Client disconnect / task cancellation
# ---------------------------------------------------------------------------


class ClientDisconnectTest(unittest.IsolatedAsyncioTestCase):
    async def test_receive_cancelled_error_marks_cancelled(self) -> None:
        # The middleware calls app(scope, receive, send). If receive()
        # raises CancelledError, the engine should record CANCELLED.
        async def app_disconnect(scope: dict, receive: Any, send: Any) -> None:
            # Simulate a client that disconnects before the body is sent.
            raise asyncio.CancelledError("client gone")

        engine = SentinelEngine()
        async with engine:
            mw = SentinelASGIMiddleware(
                app=app_disconnect, engine=engine
            )
            recorder = _MessageRecorder()
            # Middleware should not crash; it must re-raise CancelledError
            # after handling.
            with self.assertRaises(asyncio.CancelledError):
                await mw(
                    _make_http_scope(),
                    _one_shot_receive,
                    recorder,
                )
        # The engine recorded CANCELLED on last_outcome.
        self.assertIsNotNone(engine.last_outcome)
        self.assertEqual(engine.last_outcome.kind, OutcomeKind.CANCELLED)

    async def test_task_cancel_during_app_marks_cancelled(self) -> None:
        async def slow_app(scope: dict, receive: Any, send: Any) -> None:
            # Sleep long enough for the test to cancel the task.
            await asyncio.sleep(10)
            await send({
                "type": "http.response.start",
                "status": 200,
                "headers": [],
            })

        engine = SentinelEngine()
        async with engine:
            mw = SentinelASGIMiddleware(app=slow_app, engine=engine)

            async def run() -> None:
                await mw(
                    _make_http_scope(),
                    _one_shot_receive,
                    _MessageRecorder(),
                )

            task = asyncio.create_task(run())
            await asyncio.sleep(0.05)  # let the app start
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        # Outcome should be CANCELLED.
        self.assertIsNotNone(engine.last_outcome)
        self.assertEqual(engine.last_outcome.kind, OutcomeKind.CANCELLED)


# ---------------------------------------------------------------------------
# SEN-ASGI-001: Business exception in downstream
# ---------------------------------------------------------------------------


class BusinessExceptionTest(unittest.IsolatedAsyncioTestCase):
    async def test_downstream_runtime_error_marks_failed(self) -> None:
        engine = SentinelEngine()
        async with engine:
            mw = SentinelASGIMiddleware(app=_boom_app, engine=engine)
            recorder = _MessageRecorder()
            with self.assertRaises(RuntimeError):
                await mw(
                    _make_http_scope(),
                    _one_shot_receive,
                    recorder,
                )
        # The boom sent a response.start before raising; the engine
        # should still record FAILED on the outcome (the app raised
        # before sending the body EOF).
        self.assertIsNotNone(engine.last_outcome)
        # Either FAILED (caught) or outcome kind is FAILED, because
        # the downstream app raised mid-flight.
        self.assertEqual(engine.last_outcome.kind, OutcomeKind.FAILED)

    async def test_in_flight_returns_to_zero_on_exception(self) -> None:
        engine = SentinelEngine()
        async with engine:
            mw = SentinelASGIMiddleware(app=_boom_app, engine=engine)
            with self.assertRaises(RuntimeError):
                await mw(
                    _make_http_scope(),
                    _one_shot_receive,
                    _MessageRecorder(),
                )
        self.assertEqual(engine.in_flight, 0)


# ---------------------------------------------------------------------------
# SEN-ASGI-001: Lifespan protocol
# ---------------------------------------------------------------------------


class LifespanTest(unittest.IsolatedAsyncioTestCase):
    async def test_lifespan_startup_then_shutdown(self) -> None:
        engine = SentinelEngine()
        mw = SentinelASGIMiddleware(app=_lifespan_app, engine=engine)
        recorder = _MessageRecorder()
        shutdown = asyncio.Event()
        received: list[str] = []

        async def receive() -> dict[str, Any]:
            if shutdown.is_set():
                return {"type": "lifespan.shutdown"}
            # Wait for the test to set the shutdown event.
            await shutdown.wait()
            return {"type": "lifespan.shutdown"}

        # Run the lifespan handler in a task; trigger shutdown after
        # startup.complete is observed.
        async def run_lifespan() -> None:
            await mw.lifespan(_make_lifespan_scope(), receive, recorder)

        task = asyncio.create_task(run_lifespan())
        await asyncio.sleep(0.05)
        shutdown.set()
        await task
        # Engine is now SHUTDOWN.
        self.assertEqual(engine.state.value, "shutdown")
        # Recorder got lifespan.startup.complete + lifespan.shutdown.complete
        # in order.
        types = [m["type"] for m in recorder.messages]
        self.assertIn("lifespan.startup.complete", types)
        self.assertIn("lifespan.shutdown.complete", types)
        self.assertLess(
            types.index("lifespan.startup.complete"),
            types.index("lifespan.shutdown.complete"),
        )

    async def test_lifespan_closes_engine_on_shutdown(self) -> None:
        engine = SentinelEngine()
        mw = SentinelASGIMiddleware(app=_lifespan_app, engine=engine)
        recorder = _MessageRecorder()
        shutdown = asyncio.Event()

        async def receive() -> dict[str, Any]:
            await shutdown.wait()
            return {"type": "lifespan.shutdown"}

        task = asyncio.create_task(
            mw.lifespan(_make_lifespan_scope(), receive, recorder)
        )
        await asyncio.sleep(0.05)
        self.assertEqual(engine.state.value, "ready")
        shutdown.set()
        await task
        self.assertEqual(engine.state.value, "shutdown")


# ---------------------------------------------------------------------------
# SEN-ASGI-001: BLOCKED path → 503
# ---------------------------------------------------------------------------


class BlockedPathTest(unittest.IsolatedAsyncioTestCase):
    async def test_engine_rejects_returns_503(self) -> None:
        # Build an engine whose slot raises SentinelBlockedError so
        # the middleware sees a BLOCKED path.
        from atlas_richie.sentinel.engine.slot import ORDER_FLOW, Slot
        from atlas_richie.sentinel.model.argument import InvocationArguments
        from atlas_richie.sentinel.model.context import SentinelContext
        from atlas_richie.sentinel.model.decision import SlotLease
        from atlas_richie.sentinel.model.outcome import Outcome
        from atlas_richie.sentinel.model.resource import Resource

        class _BlockSlot:
            @property
            def order(self) -> int:
                return ORDER_FLOW

            def enter(self, **_kw: Any) -> SlotLease:
                raise SentinelBlockedError(
                    "test block",
                    block_reason=BlockReason.FLOW,
                    resource=Resource("GET /x"),
                    stable_code="FLOW_TEST",
                    rule_id="r1",
                )

            def on_entry_complete(self, _o: Outcome) -> None:
                pass

        engine = SentinelEngine()
        async with engine:
            engine.add_slot(_BlockSlot())  # type: ignore[arg-type]
            mw = SentinelASGIMiddleware(app=_ok_app, engine=engine)
            recorder = _MessageRecorder()
            await mw(
                _make_http_scope(),
                _one_shot_receive,
                recorder,
            )
        # 503 + sentinel: blocked body.
        self.assertEqual(recorder.status(), 503)
        self.assertEqual(b"".join(recorder.body_chunks()), b"sentinel: blocked")


# ---------------------------------------------------------------------------
# SEN-ASGI-001: Origin resolution
# ---------------------------------------------------------------------------


class OriginResolutionTest(unittest.IsolatedAsyncioTestCase):
    def test_default_resolver_reads_x_forwarded_user(self) -> None:
        scope = _make_http_scope(
            headers=[(b"x-forwarded-user", b"alice")]
        )
        self.assertEqual(default_origin_from_scope(scope), "alice")

    def test_default_resolver_returns_none_when_missing(self) -> None:
        scope = _make_http_scope()
        self.assertIsNone(default_origin_from_scope(scope))

    def test_default_resolver_handles_uppercase_header(self) -> None:
        # Headers are case-insensitive per ASGI / WSGI spec.
        scope = _make_http_scope(headers=[(b"X-Forwarded-User", b"bob")])
        self.assertEqual(default_origin_from_scope(scope), "bob")

    def test_default_resolver_handles_non_utf8_value(self) -> None:
        # Non-UTF8 bytes → returns None (don't crash).
        scope = _make_http_scope(headers=[(b"x-forwarded-user", b"\xff\xfe")])
        self.assertIsNone(default_origin_from_scope(scope))

    async def test_origin_passed_to_engine_context(self) -> None:
        captured: dict[str, Any] = {}

        # Capture the context handed to a slot.
        from atlas_richie.sentinel.engine.slot import ORDER_FLOW, Slot
        from atlas_richie.sentinel.model.argument import InvocationArguments
        from atlas_richie.sentinel.model.context import SentinelContext
        from atlas_richie.sentinel.model.decision import NoopSlotLease
        from atlas_richie.sentinel.model.outcome import Outcome

        class _CaptureSlot:
            @property
            def order(self) -> int:
                return ORDER_FLOW

            def enter(
                self, *, resource: Resource, context: SentinelContext, args: InvocationArguments | None
            ) -> NoopSlotLease:
                captured["extra"] = dict(context.extra)
                return NoopSlotLease(resource=resource)

            def on_entry_complete(self, _o: Outcome) -> None:
                pass

        engine = SentinelEngine()
        async with engine:
            engine.add_slot(_CaptureSlot())  # type: ignore[arg-type]
            mw = SentinelASGIMiddleware(app=_ok_app, engine=engine)
            await mw(
                _make_http_scope(headers=[(b"x-forwarded-user", b"carol")]),
                _one_shot_receive,
                _MessageRecorder(),
            )
        self.assertEqual(captured["extra"].get("origin"), "carol")


# ---------------------------------------------------------------------------
# SEN-ASGI-001: Non-http (websocket / lifespan etc.) passthrough
# ---------------------------------------------------------------------------


class NonHttpPassthroughTest(unittest.IsolatedAsyncioTestCase):
    async def test_websocket_passes_through(self) -> None:
        # Scope type=websocket should be passed to the downstream app
        # without engine.entry involvement.
        from atlas_richie.sentinel.engine.slot import ORDER_FLOW, Slot
        from atlas_richie.sentinel.model.argument import InvocationArguments
        from atlas_richie.sentinel.model.context import SentinelContext
        from atlas_richie.sentinel.model.decision import NoopSlotLease
        from atlas_richie.sentinel.model.outcome import Outcome

        class _ExpectNoEntrySlot:
            @property
            def order(self) -> int:
                return ORDER_FLOW

            def enter(
                self, *, resource: Resource, context: SentinelContext, args: InvocationArguments | None
            ) -> NoopSlotLease:
                raise AssertionError("slot should not be called for websocket")

            def on_entry_complete(self, _o: Outcome) -> None:
                pass

        # WebSocket-style downstream app.
        ws_called = False

        async def ws_app(scope: dict, receive: Any, send: Any) -> None:
            nonlocal ws_called
            ws_called = True
            # Send a ws accept.
            await send({"type": "websocket.accept"})

        engine = SentinelEngine()
        async with engine:
            engine.add_slot(_ExpectNoEntrySlot())  # type: ignore[arg-type]
            mw = SentinelASGIMiddleware(app=ws_app, engine=engine)
            recorder = _MessageRecorder()
            ws_scope = {"type": "websocket", "path": "/ws"}
            await mw(ws_scope, AsyncMock(), recorder)
        self.assertTrue(ws_called)
        # No engine entry was made.
        self.assertEqual(engine.in_flight, 0)


if __name__ == "__main__":
    unittest.main()

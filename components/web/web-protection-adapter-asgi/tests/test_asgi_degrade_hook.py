"""ASGI 适配层的降级接线与事件派发端到端测试。"""

from __future__ import annotations

import asyncio
import json

import pytest

from atlas_richie.web_protection import (
    DegradeConfig,
    DegradeEvaluator,
    DefaultDegradeStrategyRegistry,
    DefaultHookBus,
    Fallback,
    IpBlacklistEntry,
    RequestCompletedEvent,
    RouteFallback,
)
from atlas_richie.web_protection.degrade import (
    ATTR_HIT_STRATEGY,
    STRATEGY_NAME_ROUTE,
)
from atlas_richie.web_protection_adapter_asgi import ProtectionASGIMiddleware

pytestmark = pytest.mark.unit


class _App:
    def __init__(
        self,
        status: int = 200,
        body: bytes = b"ok",
        error: Exception | None = None,
        delay: float = 0.0,
    ) -> None:
        self.status = status
        self.body = body
        self.error = error
        self.delay = delay
        self.calls = 0

    async def __call__(self, scope, receive, send) -> None:
        self.calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error is not None:
            raise self.error
        await send({
            "type": "http.response.start",
            "status": self.status,
            "headers": [(b"content-type", b"text/plain")],
        })
        await send({"type": "http.response.body", "body": self.body, "more_body": False})


def _scope(path="/api/orders", method="GET"):
    return {
        "type": "http",
        "method": method,
        "path": path,
        "headers": [],
        "client": ("203.0.113.9", 1234),
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


def _status(sent):
    start = next(m for m in sent if m["type"] == "http.response.start")
    return start["status"]


def _body(sent):
    return b"".join(
        m.get("body", b"") for m in sent if m["type"] == "http.response.body"
    )


def _headers(sent):
    start = next(m for m in sent if m["type"] == "http.response.start")
    return {k.decode().lower(): v.decode() for k, v in start["headers"]}


class _Collector:
    def __init__(self) -> None:
        self.events: list[RequestCompletedEvent] = []

    def on_event(self, event: RequestCompletedEvent) -> None:
        self.events.append(event)


def _degrade_evaluator(latency_threshold_ms: int = 3000, require_route_match: bool = True):
    config = DegradeConfig(
        routes={"/api/orders": RouteFallback(pattern="/api/orders")},
        fallback=Fallback(),
    )
    registry = DefaultDegradeStrategyRegistry()
    return DegradeEvaluator(
        registry,
        config,
        latency_threshold_ms,
        require_route_match=require_route_match,
    )


class TestRequestCompletedEvent:
    def test_published_on_success(self) -> None:
        bus = DefaultHookBus()
        collector = _Collector()
        bus.subscribe(RequestCompletedEvent, collector)
        middleware = ProtectionASGIMiddleware(_App(), hook_bus=bus)
        sent = _call(middleware, _scope())
        assert _status(sent) == 200
        assert len(collector.events) == 1
        event = collector.events[0]
        assert event.path == "/api/orders"
        assert event.response_status == 200
        assert event.short_circuited is False
        assert event.has_error is False

    def test_published_on_short_circuit(self) -> None:
        bus = DefaultHookBus()
        collector = _Collector()
        bus.subscribe(RequestCompletedEvent, collector)
        middleware = ProtectionASGIMiddleware(
            _App(),
            ip_blacklist=[IpBlacklistEntry("203.0.113.0/24")],
            hook_bus=bus,
        )
        sent = _call(middleware, _scope())
        assert _status(sent) == 403
        assert len(collector.events) == 1
        assert collector.events[0].short_circuited is True
        assert collector.events[0].response_status == 403

    def test_published_on_exception(self) -> None:
        bus = DefaultHookBus()
        collector = _Collector()
        bus.subscribe(RequestCompletedEvent, collector)
        middleware = ProtectionASGIMiddleware(
            _App(error=RuntimeError("boom")), hook_bus=bus
        )
        with pytest.raises(RuntimeError):
            _call(middleware, _scope())
        assert len(collector.events) == 1
        assert collector.events[0].has_error is True

    def test_not_published_without_bus(self) -> None:
        middleware = ProtectionASGIMiddleware(_App())
        sent = _call(middleware, _scope())
        assert _status(sent) == 200


class TestDegradeWiring:
    def test_exception_triggers_degrade_response(self) -> None:
        middleware = ProtectionASGIMiddleware(
            _App(error=RuntimeError("boom")),
            degrade_evaluator=_degrade_evaluator(),
        )
        sent = _call(middleware, _scope())
        assert _status(sent) == 503
        payload = json.loads(_body(sent))
        assert payload["success"] is False
        assert payload["code"] == "DEGRADED"
        assert payload["msg"] == "服务降级中 (exception)"

    def test_normal_path_passes_through(self) -> None:
        middleware = ProtectionASGIMiddleware(
            _App(), degrade_evaluator=_degrade_evaluator()
        )
        sent = _call(middleware, _scope())
        assert _status(sent) == 200
        assert _body(sent) == b"ok"

    def test_unmatched_route_does_not_degrade(self) -> None:
        middleware = ProtectionASGIMiddleware(
            _App(error=RuntimeError("boom")),
            degrade_evaluator=_degrade_evaluator(),
        )
        with pytest.raises(RuntimeError):
            _call(middleware, _scope("/api/other"))

    def test_latency_trigger_degrades(self) -> None:
        """业务耗时超阈值 → 按 HIGH_LATENCY 降级（Java 规则是严格大于）。"""
        middleware = ProtectionASGIMiddleware(
            _App(delay=0.08), degrade_evaluator=_degrade_evaluator(latency_threshold_ms=10)
        )
        sent = _call(middleware, _scope())
        assert _status(sent) == 503
        assert json.loads(_body(sent))["msg"] == "服务降级中 (high-latency)"

    def test_latency_below_threshold_does_not_degrade(self) -> None:
        middleware = ProtectionASGIMiddleware(
            _App(delay=0.01), degrade_evaluator=_degrade_evaluator(latency_threshold_ms=3000)
        )
        sent = _call(middleware, _scope())
        assert _status(sent) == 200
        assert _body(sent) == b"ok"

    def test_degrade_response_keeps_platform_headers(self) -> None:
        middleware = ProtectionASGIMiddleware(
            _App(error=RuntimeError("boom")),
            degrade_evaluator=_degrade_evaluator(),
        )
        sent = _call(middleware, _scope())
        headers = _headers(sent)
        assert "x-trace-id" in headers

    def test_degrade_disabled_keeps_exception(self) -> None:
        middleware = ProtectionASGIMiddleware(_App(error=RuntimeError("boom")))
        with pytest.raises(RuntimeError):
            _call(middleware, _scope())


class TestExtraInterceptors:
    def test_extra_interceptors_appended_after_platform_guards(self) -> None:
        class _Extra:
            def intercept(self, ctx, chain) -> None:
                chain.proceed(ctx)

        middleware = ProtectionASGIMiddleware(
            _App(),
            ip_blacklist=[IpBlacklistEntry("0.0.0.0/0")],
            extra_interceptors=[_Extra()],
        )
        names = [type(i).__name__ for i in middleware.interceptors]
        assert names[-1] == "_Extra"
        assert names.index("_Extra") > names.index("IpBlacklistInterceptor")

    def test_extra_interceptor_can_short_circuit(self) -> None:
        class _Deny:
            def intercept(self, ctx, chain) -> None:
                ctx.mark_short_circuit(429, "denied")

        middleware = ProtectionASGIMiddleware(
            _App(), extra_interceptors=[_Deny()]
        )
        sent = _call(middleware, _scope())
        assert _status(sent) == 429
        assert _body(sent) == b"denied"

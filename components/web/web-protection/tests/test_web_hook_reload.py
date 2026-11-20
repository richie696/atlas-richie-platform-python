"""事件总线与热更新注册表测试（对位 Java `web.core.hook` / `web.core.reload`）。"""

from __future__ import annotations

import pytest

from atlas_richie.web_protection.hook import (
    DefaultHookBus,
    HookEvent,
    RequestCompletedEvent,
)
from atlas_richie.web_protection.reload import (
    DefaultHotReloadRegistry,
    ReloadEvent,
    reloadable_name,
)
from atlas_richie.web_protection.spi import MutableWebRequestContext

pytestmark = pytest.mark.unit


class _Collector:
    def __init__(self) -> None:
        self.events: list[HookEvent] = []

    def on_event(self, event) -> None:
        self.events.append(event)


class _Boom:
    def on_event(self, event) -> None:
        raise RuntimeError("subscriber blew up")


class _Reloadable:
    def __init__(self, state: str = "v1") -> None:
        self.state = state
        self.accepted: list[str] = []

    def current_state(self) -> str:
        return self.state

    def accept(self, new_state: str) -> None:
        self.accepted.append(new_state)


class _NamedReloadable(_Reloadable):
    def name(self) -> str:
        return "custom-name"


class TestHookBus:
    def test_publish_reaches_subscribers(self) -> None:
        bus = DefaultHookBus()
        collector = _Collector()
        bus.subscribe(RequestCompletedEvent, collector)
        event = RequestCompletedEvent.of(MutableWebRequestContext("GET", "/"), 1000)
        bus.publish(event)
        assert collector.events == [event]

    def test_fan_out_to_multiple_subscribers(self) -> None:
        bus = DefaultHookBus()
        first, second = _Collector(), _Collector()
        bus.subscribe(RequestCompletedEvent, first)
        bus.subscribe(RequestCompletedEvent, second)
        bus.publish(RequestCompletedEvent.of(MutableWebRequestContext("GET", "/"), 1))
        assert len(first.events) == 1 and len(second.events) == 1

    def test_exact_type_dispatch_only(self) -> None:
        """按事件**精确类型**分发（对位 Java 的 `event.getClass()`）。"""
        bus = DefaultHookBus()
        collector = _Collector()
        bus.subscribe(HookEvent, collector)
        bus.publish(RequestCompletedEvent.of(MutableWebRequestContext("GET", "/"), 1))
        assert collector.events == []

    def test_subscriber_exception_is_isolated(self) -> None:
        bus = DefaultHookBus()
        survivor = _Collector()
        bus.subscribe(RequestCompletedEvent, _Boom())
        bus.subscribe(RequestCompletedEvent, survivor)
        bus.publish(RequestCompletedEvent.of(MutableWebRequestContext("GET", "/"), 1))
        assert len(survivor.events) == 1

    def test_unsubscribe_stops_delivery(self) -> None:
        bus = DefaultHookBus()
        collector = _Collector()
        subscription = bus.subscribe(RequestCompletedEvent, collector)
        subscription.close()
        bus.publish(RequestCompletedEvent.of(MutableWebRequestContext("GET", "/"), 1))
        assert collector.events == []

    def test_close_is_idempotent(self) -> None:
        bus = DefaultHookBus()
        subscription = bus.subscribe(RequestCompletedEvent, _Collector())
        subscription.close()
        subscription.close()

    def test_diagnostic_view_format(self) -> None:
        bus = DefaultHookBus()
        bus.subscribe(RequestCompletedEvent, _Collector())
        bus.subscribe(RequestCompletedEvent, _Collector())
        assert bus.diagnostic_view() == ["RequestCompletedEvent→2"]

    def test_publish_none_is_ignored(self) -> None:
        bus = DefaultHookBus()
        bus.publish(None)

    def test_subscribe_none_rejected(self) -> None:
        bus = DefaultHookBus()
        with pytest.raises(ValueError):
            bus.subscribe(None, _Collector())
        with pytest.raises(ValueError):
            bus.subscribe(RequestCompletedEvent, None)

    def test_publish_without_subscribers_is_silent(self) -> None:
        bus = DefaultHookBus()
        bus.publish(RequestCompletedEvent.of(MutableWebRequestContext("GET", "/"), 1))


class TestRequestCompletedEvent:
    def test_of_reads_context(self) -> None:
        ctx = MutableWebRequestContext(method="POST", path="/api/orders")
        ctx.set_response_status(503)
        ctx.set_client_key("client-1")
        ctx.set_trace_id("trace-1")
        ctx.mark_short_circuit(503, "degraded")
        ctx.set_error(RuntimeError("boom"))
        event = RequestCompletedEvent.of(ctx, 5_000_000)
        assert event.method == "POST"
        assert event.path == "/api/orders"
        assert event.response_status == 503
        assert event.short_circuited is True
        assert event.has_error is True
        assert event.client_key == "client-1"
        assert event.trace_id == "trace-1"

    def test_duration_millis_is_integer(self) -> None:
        ctx = MutableWebRequestContext("GET", "/")
        event = RequestCompletedEvent.of(ctx, ctx.start_nanos + 2_500_000)
        assert event.duration_millis() == 2
        assert isinstance(event.duration_millis(), int)


class TestHotReloadRegistry:
    def test_register_and_get(self) -> None:
        registry = DefaultHotReloadRegistry()
        target = _Reloadable()
        registry.register("cfg", target)
        assert registry.get("cfg") is target
        assert registry.names() == frozenset({"cfg"})

    def test_register_same_name_overwrites(self) -> None:
        registry = DefaultHotReloadRegistry()
        first, second = _Reloadable(), _Reloadable()
        registry.register("cfg", first)
        registry.register("cfg", second)
        assert registry.get("cfg") is second

    def test_unregister(self) -> None:
        registry = DefaultHotReloadRegistry()
        registry.register("cfg", _Reloadable())
        registry.unregister("cfg")
        assert registry.get("cfg") is None
        assert registry.names() == frozenset()

    def test_blank_name_rejected(self) -> None:
        registry = DefaultHotReloadRegistry()
        with pytest.raises(ValueError):
            registry.register(" ", _Reloadable())

    def test_none_reloadable_rejected(self) -> None:
        registry = DefaultHotReloadRegistry()
        with pytest.raises(ValueError):
            registry.register("cfg", None)

    def test_reload_applies_current_state(self) -> None:
        registry = DefaultHotReloadRegistry()
        target = _Reloadable("v2")
        registry.register("cfg", target)
        assert registry.reload("cfg") is True
        assert target.accepted == ["v2"]

    def test_reload_unknown_name_returns_false(self) -> None:
        registry = DefaultHotReloadRegistry()
        assert registry.reload("missing") is False

    def test_reload_all_counts_successes(self) -> None:
        registry = DefaultHotReloadRegistry()
        registry.register("a", _Reloadable())
        registry.register("b", _Reloadable())
        assert registry.reload_all() == 2

    def test_reload_publishes_event(self) -> None:
        bus = DefaultHookBus()
        collector = _Collector()
        bus.subscribe(ReloadEvent, collector)
        registry = DefaultHotReloadRegistry(bus)
        registry.register("cfg", _Reloadable())
        registry.reload("cfg")
        assert len(collector.events) == 1
        event = collector.events[0]
        assert event.name == "cfg"
        assert event.timestamp > 0

    def test_reload_without_hook_bus_is_silent(self) -> None:
        registry = DefaultHotReloadRegistry()
        registry.register("cfg", _Reloadable())
        assert registry.reload("cfg") is True

    def test_reloadable_name_falls_back_to_class_name(self) -> None:
        assert reloadable_name(_Reloadable()) == "_Reloadable"
        assert reloadable_name(_NamedReloadable()) == "custom-name"

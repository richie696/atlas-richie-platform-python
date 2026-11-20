"""看门狗 SPI 测试（对位 Java `web.core.hang` 的调度与三档分级）。"""

from __future__ import annotations

import logging
import threading
import time

import pytest

from atlas_richie.web_protection.hang import (
    MAX_STACK_FRAMES,
    HangDetectionInterceptor,
    HangEvent,
    WatchdogScheduler,
    stack_of,
)
from atlas_richie.web_protection.hang.interceptor import _OneShot
from atlas_richie.web_protection.hook import DefaultHookBus
from atlas_richie.web_protection.spi import (
    LONG_LIVED_ATTRIBUTE,
    MutableWebRequestContext,
)

pytestmark = pytest.mark.unit


class _Chain:
    """最小拦截器链（只实现 proceed）。"""

    def __init__(self, action=None) -> None:
        self._action = action

    def proceed(self, ctx) -> None:
        if self._action is not None:
            self._action()

    @property
    def interceptors(self):
        return ()


class _Collector:
    def __init__(self) -> None:
        self.events: list[HangEvent] = []
        self.received = threading.Event()

    def on_event(self, event: HangEvent) -> None:
        self.events.append(event)
        self.received.set()


@pytest.fixture()
def scheduler():
    instance = WatchdogScheduler(max_workers=2)
    yield instance
    instance.shutdown()


class TestWatchdogScheduler:
    def test_fires_after_threshold(self, scheduler) -> None:
        fired = threading.Event()
        scheduler.schedule(30, fired.set)
        assert fired.wait(timeout=2.0) is True

    def test_cancel_prevents_firing(self, scheduler) -> None:
        fired = threading.Event()
        handle = scheduler.schedule(80, fired.set)
        assert handle.cancel() is True
        time.sleep(0.2)
        assert fired.is_set() is False

    def test_cancel_twice_returns_false(self, scheduler) -> None:
        handle = scheduler.schedule(80, lambda: None)
        assert handle.cancel() is True
        assert handle.cancel() is False

    def test_is_cancelled_reflects_flag(self, scheduler) -> None:
        handle = scheduler.schedule(80, lambda: None)
        assert handle.is_cancelled() is False
        handle.cancel()
        assert handle.is_cancelled() is True

    def test_fired_handle_cannot_be_cancelled(self, scheduler) -> None:
        fired = threading.Event()
        handle = scheduler.schedule(20, fired.set)
        assert fired.wait(timeout=2.0) is True
        time.sleep(0.05)
        assert handle.is_fired() is True
        assert handle.cancel() is False

    def test_shutdown_is_idempotent(self, scheduler) -> None:
        scheduler.shutdown()
        scheduler.shutdown()
        assert scheduler.is_shutdown is True

    def test_schedule_after_shutdown_raises(self, scheduler) -> None:
        scheduler.shutdown()
        with pytest.raises(RuntimeError):
            scheduler.schedule(10, lambda: None)

    def test_non_positive_threshold_rejected(self, scheduler) -> None:
        with pytest.raises(ValueError):
            scheduler.schedule(0, lambda: None)

    def test_none_callback_rejected(self, scheduler) -> None:
        with pytest.raises(ValueError):
            scheduler.schedule(10, None)

    def test_default_singleton_is_shared(self) -> None:
        assert WatchdogScheduler.get_default() is WatchdogScheduler.get_default()


class TestHangEvent:
    def test_stack_of_caps_frames(self) -> None:
        stack = stack_of(threading.current_thread())
        assert len(stack) <= MAX_STACK_FRAMES
        assert all(isinstance(frame, str) for frame in stack)

    def test_stack_of_unknown_thread_is_empty(self) -> None:
        class _Fake:
            ident = 999999999

        assert stack_of(_Fake()) == ()


class TestHangDetectionInterceptor:
    def test_rejects_non_positive_thresholds(self) -> None:
        with pytest.raises(ValueError):
            HangDetectionInterceptor(0, 10, 20)
        with pytest.raises(ValueError):
            HangDetectionInterceptor(10, 0, 20)
        with pytest.raises(ValueError):
            HangDetectionInterceptor(10, 20, 0)

    def test_rejects_unordered_thresholds(self) -> None:
        with pytest.raises(ValueError):
            HangDetectionInterceptor(30, 20, 40)
        with pytest.raises(ValueError):
            HangDetectionInterceptor(10, 40, 20)

    def test_long_lived_path_skips_watchdog(self, scheduler) -> None:
        collector = _Collector()
        bus = DefaultHookBus()
        bus.subscribe(HangEvent, collector)
        interceptor = HangDetectionInterceptor(
            20, 30, 40, scheduler=scheduler, hook_bus=bus
        )
        ctx = MutableWebRequestContext(method="GET", path="/sse/stream")
        ctx.set_attribute(LONG_LIVED_ATTRIBUTE, True)
        interceptor.intercept(ctx, _Chain())
        time.sleep(0.15)
        assert ctx.attribute(interceptor.WATCH_HANDLE_ATTRIBUTE) is None
        assert collector.events == []

    def test_watch_handle_registered_and_cancelled(self, scheduler) -> None:
        interceptor = HangDetectionInterceptor(50, 100, 200, scheduler=scheduler)
        ctx = MutableWebRequestContext(method="GET", path="/api/orders")
        interceptor.intercept(ctx, _Chain())
        handle = ctx.attribute(interceptor.WATCH_HANDLE_ATTRIBUTE)
        assert handle is not None
        assert handle.is_cancelled() is True

    def test_warn_level_publishes_event(self, scheduler) -> None:
        collector = _Collector()
        bus = DefaultHookBus()
        bus.subscribe(HangEvent, collector)
        interceptor = HangDetectionInterceptor(
            20, 200, 400, scheduler=scheduler, hook_bus=bus
        )
        ctx = MutableWebRequestContext(method="GET", path="/api/orders")
        ctx.set_trace_id("trace-1")
        interceptor.intercept(ctx, _Chain(lambda: time.sleep(0.15)))
        assert collector.received.wait(timeout=2.0) is True
        event = collector.events[0]
        assert event.path == "/api/orders"
        assert event.method == "GET"
        assert event.trace_id == "trace-1"
        assert event.threshold_millis == 20
        assert ctx.attribute(interceptor.HANG_LEVEL_ATTRIBUTE) == "WARN"

    def test_one_shot_gate_blocks_second_call(self) -> None:
        """同一档只触发一次（对位 Java 的 `AtomicBoolean.compareAndSet` 背压）。"""
        gate = _OneShot()
        assert gate.try_acquire() is True
        assert gate.try_acquire() is False

    def test_each_level_publishes_at_most_once(self, scheduler) -> None:
        """一轮请求里每个档位最多一条事件。"""
        collector = _Collector()
        bus = DefaultHookBus()
        bus.subscribe(HangEvent, collector)
        interceptor = HangDetectionInterceptor(
            20, 30, 40, scheduler=scheduler, hook_bus=bus
        )
        ctx = MutableWebRequestContext(method="GET", path="/api/orders")
        interceptor.intercept(ctx, _Chain(lambda: time.sleep(0.15)))
        time.sleep(0.15)
        thresholds = [event.threshold_millis for event in collector.events]
        assert len(thresholds) == len(set(thresholds))

    def test_kill_level_invokes_interrupter(self, scheduler) -> None:
        collector = _Collector()
        bus = DefaultHookBus()
        bus.subscribe(HangEvent, collector)
        killed: list[threading.Thread] = []
        interceptor = HangDetectionInterceptor(
            20, 30, 40,
            scheduler=scheduler,
            hook_bus=bus,
            kill_interrupter=killed.append,
        )
        ctx = MutableWebRequestContext(method="GET", path="/api/orders")
        interceptor.intercept(ctx, _Chain(lambda: time.sleep(0.2)))
        time.sleep(0.2)
        assert killed, "kill 档应调用 interrupter"
        assert ctx.attribute(interceptor.HANG_LEVEL_ATTRIBUTE) in ("DUMP", "KILL_SWITCH")

    def test_dump_level_logs_thread_snapshot(self, scheduler, caplog) -> None:
        collector = _Collector()
        bus = DefaultHookBus()
        bus.subscribe(HangEvent, collector)
        interceptor = HangDetectionInterceptor(
            20, 30, 400, dump_enabled=True, scheduler=scheduler, hook_bus=bus
        )
        ctx = MutableWebRequestContext(method="GET", path="/api/orders")
        with caplog.at_level(logging.WARNING):
            interceptor.intercept(ctx, _Chain(lambda: time.sleep(0.15)))
            time.sleep(0.1)
        assert any("thread dump" in record.getMessage() for record in caplog.records)

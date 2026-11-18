"""同步重试、去抖、命名注册表。"""

from __future__ import annotations

import threading
import time
from datetime import timedelta

import pytest

from atlas_richie.concurrency_core import (
    Debouncer,
    NamedRegistry,
    Retryer,
    RetryExhaustedError,
)

pytestmark = pytest.mark.unit


class TestRetryer:
    def test_success_on_first_attempt(self) -> None:
        calls: list[int] = []

        def task():
            calls.append(1)
            return "ok"

        assert Retryer.of(timedelta(0)).execute(task, sleep=lambda s: None) == "ok"
        assert len(calls) == 1

    def test_retries_then_succeeds(self) -> None:
        attempts: list[int] = []

        def task():
            attempts.append(1)
            if len(attempts) < 3:
                raise ConnectionError("transient")
            return "ok"

        result = Retryer.of(timedelta(0)).max_attempts(5).execute(task, sleep=lambda s: None)
        assert result == "ok"
        assert len(attempts) == 3

    def test_exhaustion_raises_with_last_error(self) -> None:
        error = ConnectionError("still down")

        def task():
            raise error

        with pytest.raises(RetryExhaustedError) as info:
            Retryer.of(timedelta(0)).max_attempts(3).execute(task, sleep=lambda s: None)
        assert info.value.last_error is error
        assert "3 attempts" in str(info.value)

    def test_non_matching_exception_reraised_immediately(self) -> None:
        calls: list[int] = []

        def task():
            calls.append(1)
            raise ValueError("permanent")

        with pytest.raises(ValueError, match="permanent"):
            Retryer.of(timedelta(0)).retry_on(ConnectionError).execute(task, sleep=lambda s: None)
        assert len(calls) == 1, "不匹配 retryOn 的异常不得消耗重试"

    def test_retry_on_subclasses_match(self) -> None:
        attempts: list[int] = []

        def task():
            attempts.append(1)
            if len(attempts) < 2:
                raise TimeoutError("slow")
            return "ok"

        result = Retryer.of(timedelta(0)).retry_on(OSError).execute(task, sleep=lambda s: None)
        assert result == "ok"  # TimeoutError 是 OSError 子类

    def test_backoff_is_exponential_and_capped(self) -> None:
        slept: list[float] = []

        def task():
            raise ConnectionError("down")

        with pytest.raises(RetryExhaustedError):
            (
                Retryer.of(timedelta(milliseconds=100))
                .max_attempts(5)
                .max_backoff(timedelta(milliseconds=350))
                .execute(task, sleep=slept.append)
            )
        assert slept == [0.1, 0.2, 0.35, 0.35], "指数增长且封顶"

    def test_jitter_stays_within_half_to_full(self) -> None:
        slept: list[float] = []

        def task():
            raise ConnectionError("down")

        with pytest.raises(RetryExhaustedError):
            (
                Retryer.of(timedelta(milliseconds=100))
                .max_attempts(4)
                .jitter(True)
                .execute(task, sleep=slept.append)
            )
        for value, full in zip(slept, [0.1, 0.2, 0.4]):
            assert full / 2 <= value <= full

    def test_fallback_on_exhaustion(self) -> None:
        def task():
            raise ConnectionError("down")

        result = Retryer.of(timedelta(0)).execute_with_fallback(task, "default", sleep=lambda s: None)
        assert result == "default"

    def test_fallback_not_used_on_success(self) -> None:
        result = Retryer.of(timedelta(0)).execute_with_fallback(lambda: "real", "default")
        assert result == "real"

    def test_fallback_on_non_retryable_exception(self) -> None:
        def task():
            raise ValueError("permanent")

        assert Retryer.of(timedelta(0)).execute_with_fallback(task, "default") == "default"

    def test_cancelled_before_attempt(self) -> None:
        calls: list[int] = []

        def task():
            calls.append(1)
            return "ok"

        with pytest.raises(RetryExhaustedError, match="cancelled"):
            Retryer.of(timedelta(0)).execute(task, cancelled=lambda: True)
        assert calls == []

    def test_default_max_attempts_is_three(self) -> None:
        attempts: list[int] = []

        def task():
            attempts.append(1)
            raise ConnectionError("down")

        with pytest.raises(RetryExhaustedError):
            Retryer.of(timedelta(0)).execute(task, sleep=lambda s: None)
        assert len(attempts) == 3

    @pytest.mark.parametrize("kwargs", [
        {"initial_backoff": timedelta(seconds=-1)},
    ])
    def test_negative_initial_backoff_rejected(self, kwargs) -> None:
        with pytest.raises(ValueError):
            Retryer.of(**kwargs)

    def test_invalid_max_attempts_rejected(self) -> None:
        with pytest.raises(ValueError):
            Retryer.of(timedelta(0)).max_attempts(0)

    def test_empty_retry_on_rejected(self) -> None:
        with pytest.raises(ValueError):
            Retryer.of(timedelta(0)).retry_on()

    def test_non_callable_task_rejected(self) -> None:
        with pytest.raises(ValueError):
            Retryer.of(timedelta(0)).execute(None)


class TestDebouncer:
    def test_fires_after_delay(self) -> None:
        fired = threading.Event()
        with Debouncer.of(timedelta(milliseconds=30), fired.set) as debouncer:
            debouncer.trigger()
            assert fired.wait(2.0)

    def test_retrigger_resets_timer(self) -> None:
        calls: list[int] = []
        with Debouncer.of(timedelta(milliseconds=60), lambda: calls.append(1)) as debouncer:
            debouncer.trigger()
            time.sleep(0.03)
            debouncer.trigger()  # 重置
            time.sleep(0.03)
            assert calls == [], "静默期未满不应执行"
            time.sleep(0.08)
            assert calls == [1], "只执行一次"

    def test_flush_executes_immediately_and_cancels_pending(self) -> None:
        calls: list[int] = []
        with Debouncer.of(timedelta(milliseconds=500), lambda: calls.append(1)) as debouncer:
            debouncer.trigger()
            debouncer.flush()
            assert calls == [1]
            assert debouncer.is_pending() is False
            time.sleep(0.05)
            assert calls == [1], "flush 后原计时不得再触发"

    def test_cancel_drops_pending(self) -> None:
        calls: list[int] = []
        with Debouncer.of(timedelta(milliseconds=30), lambda: calls.append(1)) as debouncer:
            debouncer.trigger()
            debouncer.cancel()
            assert debouncer.is_pending() is False
            time.sleep(0.08)
            assert calls == []

    def test_is_pending_lifecycle(self) -> None:
        with Debouncer.of(timedelta(milliseconds=50), lambda: None) as debouncer:
            assert debouncer.is_pending() is False
            debouncer.trigger()
            assert debouncer.is_pending() is True
            debouncer.cancel()
            assert debouncer.is_pending() is False

    def test_close_prevents_further_triggers(self) -> None:
        calls: list[int] = []
        debouncer = Debouncer.of(timedelta(milliseconds=20), lambda: calls.append(1))
        debouncer.close()
        debouncer.trigger()
        time.sleep(0.06)
        assert calls == []

    def test_action_exception_is_swallowed(self) -> None:
        def boom():
            raise RuntimeError("action down")

        with Debouncer.of(timedelta(milliseconds=20), boom) as debouncer:
            debouncer.trigger()
            time.sleep(0.08)  # 不应把异常抛给测试线程

    def test_flush_swallows_action_exception(self) -> None:
        def boom():
            raise RuntimeError("down")

        with Debouncer.of(timedelta(seconds=1), boom) as debouncer:
            debouncer.flush()  # 不抛

    @pytest.mark.parametrize("delay", [timedelta(0), timedelta(seconds=-1)])
    def test_invalid_delay_rejected(self, delay) -> None:
        with pytest.raises(ValueError):
            Debouncer.of(delay, lambda: None)

    def test_non_callable_action_rejected(self) -> None:
        with pytest.raises(ValueError):
            Debouncer.of(timedelta(seconds=1), None)


class TestNamedRegistry:
    def test_get_or_create_creates_once(self) -> None:
        created: list[str] = []

        def factory(name):
            created.append(name)
            return object()

        registry = NamedRegistry(factory)
        first = registry.get_or_create("api")
        second = registry.get_or_create("api")
        assert first is second
        assert created == ["api"]

    def test_per_call_factory_overrides(self) -> None:
        registry = NamedRegistry(lambda name: "default")
        assert registry.get_or_create("x", lambda name: "custom") == "custom"

    def test_find_and_remove(self) -> None:
        registry = NamedRegistry(lambda name: name.upper())
        registry.get_or_create("api")
        assert registry.find("api") == "API"
        assert registry.find("absent") is None
        assert registry.remove("api") == "API"
        assert registry.find("api") is None
        assert registry.remove("api") is None

    def test_register_replaces(self) -> None:
        registry = NamedRegistry()
        registry.register("x", 1)
        registry.register("x", 2)
        assert registry.find("x") == 2

    def test_keys_size_clear(self) -> None:
        registry = NamedRegistry(lambda name: name)
        registry.get_or_create("a")
        registry.get_or_create("b")
        assert set(registry.keys()) == {"a", "b"}
        assert registry.size() == 2
        registry.clear()
        assert registry.size() == 0
        assert registry.keys() == ()

    def test_concurrent_get_or_create_creates_exactly_once(self) -> None:
        created: list[str] = []
        lock = threading.Lock()

        def factory(name):
            with lock:
                created.append(name)
            time.sleep(0.01)
            return object()

        registry = NamedRegistry(factory)
        results: list[object] = []
        result_lock = threading.Lock()

        def worker():
            item = registry.get_or_create("shared")
            with result_lock:
                results.append(item)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(10)
        assert len(created) == 1, "工厂在锁内运行，不得重复创建"
        assert all(item is results[0] for item in results)

    def test_blank_name_rejected(self) -> None:
        registry = NamedRegistry(lambda name: name)
        with pytest.raises(ValueError):
            registry.get_or_create("")

    def test_no_factory_rejected(self) -> None:
        with pytest.raises(ValueError, match="factory"):
            NamedRegistry().get_or_create("x")

"""纯并发算法：同步重试、去抖、命名注册表。零第三方依赖。

对位 Java `atlas-richie-concurrency` 的可移植子集。不移植 JVM 特有的
DynamicExecutor resize / VirtualThreadFactory / StructuredTaskScope。
"""

from __future__ import annotations

import random
import threading
import time
from datetime import timedelta
from typing import Callable, Generic, TypeVar

T = TypeVar("T")

_DEFAULT_MAX_ATTEMPTS = 3
_DEFAULT_MAX_BACKOFF = timedelta(seconds=30)
_MAX_SAFE_SHIFT = 30


class RetryExhaustedError(RuntimeError):
    """All attempts failed (or the retry was cancelled)."""

    def __init__(self, message: str, last_error: BaseException | None = None) -> None:
        super().__init__(message)
        self.last_error = last_error


class Retryer:
    """Builder-style synchronous retry (对位 Java `Retryer.RetryBuilder`)."""

    def __init__(self, initial_backoff: timedelta) -> None:
        if initial_backoff is None or initial_backoff < timedelta(0):
            raise ValueError("initial_backoff must not be negative")
        self._initial_backoff = initial_backoff
        self._max_attempts = _DEFAULT_MAX_ATTEMPTS
        self._max_backoff = _DEFAULT_MAX_BACKOFF
        self._jitter = False
        self._retry_on: tuple[type[BaseException], ...] = (Exception,)
        self._rng = random.Random()

    @classmethod
    def of(cls, initial_backoff: timedelta) -> Retryer:
        return cls(initial_backoff)

    def max_attempts(self, attempts: int) -> Retryer:
        if attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        self._max_attempts = attempts
        return self

    def max_backoff(self, backoff: timedelta) -> Retryer:
        if backoff < timedelta(0):
            raise ValueError("max_backoff must not be negative")
        self._max_backoff = backoff
        return self

    def jitter(self, enabled: bool = True) -> Retryer:
        self._jitter = enabled
        return self

    def retry_on(self, *types: type[BaseException]) -> Retryer:
        if not types:
            raise ValueError("retry_on requires at least one exception type")
        self._retry_on = types
        return self

    def execute(
        self,
        task: Callable[[], T],
        *,
        cancelled: Callable[[], bool] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> T:
        if not callable(task):
            raise ValueError("task must be callable")
        last_error: BaseException | None = None
        for attempt in range(1, self._max_attempts + 1):
            if cancelled is not None and cancelled():
                raise RetryExhaustedError(
                    f"Retry cancelled before attempt {attempt}", last_error
                )
            try:
                return task()
            except Exception as error:
                if not isinstance(error, self._retry_on):
                    raise
                last_error = error
                if attempt < self._max_attempts:
                    sleep(self._compute_backoff(attempt).total_seconds())
        detail = str(last_error) if last_error is not None else "unknown"
        raise RetryExhaustedError(
            f"Retry exhausted after {self._max_attempts} attempts, last error: {detail}",
            last_error,
        )

    def execute_with_fallback(
        self,
        task: Callable[[], T],
        fallback: T,
        *,
        cancelled: Callable[[], bool] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> T:
        try:
            return self.execute(task, cancelled=cancelled, sleep=sleep)
        except Exception:
            return fallback

    def _compute_backoff(self, attempt: int) -> timedelta:
        initial_ms = self._initial_backoff.total_seconds() * 1000
        max_ms = self._max_backoff.total_seconds() * 1000
        shift = min(attempt - 1, _MAX_SAFE_SHIFT)
        try:
            backoff_ms = min(initial_ms * (1 << shift), max_ms)
        except OverflowError:
            backoff_ms = max_ms
        if self._jitter:
            low_ms = backoff_ms / 2
            if low_ms >= backoff_ms:
                return timedelta(milliseconds=backoff_ms)
            backoff_ms = self._rng.uniform(low_ms, backoff_ms)
        return timedelta(milliseconds=backoff_ms)


class Debouncer:
    """Trailing-edge debounce (对位 Java `Debouncer`).

    Each `trigger` restarts the timer; the action runs once after `delay` of
    quiet. Action exceptions are swallowed — debounce is a best-effort side
    channel and must not throw into the triggering caller.
    """

    def __init__(self, delay: timedelta, action: Callable[[], None]) -> None:
        if delay is None or delay <= timedelta(0):
            raise ValueError("delay must be positive")
        if not callable(action):
            raise ValueError("action must be callable")
        self._delay = delay.total_seconds()
        self._action = action
        self._lock = threading.Lock()
        self._timer: threading.Timer | None = None
        self._closed = False

    @classmethod
    def of(cls, delay: timedelta, action: Callable[[], None]) -> Debouncer:
        return cls(delay, action)

    def trigger(self) -> None:
        with self._lock:
            if self._closed:
                return
            if self._timer is not None:
                self._timer.cancel()
            self._timer = threading.Timer(self._delay, self._run_safely)
            self._timer.daemon = True
            self._timer.start()

    def flush(self) -> None:
        with self._lock:
            timer = self._timer
            self._timer = None
        if timer is not None:
            timer.cancel()
        self._run_safely()

    def cancel(self) -> None:
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None

    def is_pending(self) -> bool:
        with self._lock:
            return self._timer is not None

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None

    def _run_safely(self) -> None:
        with self._lock:
            self._timer = None
        try:
            self._action()
        except Exception:  # noqa: BLE001 — 对位 Java：去抖动作异常不外抛
            pass

    def __enter__(self) -> Debouncer:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


class NamedRegistry(Generic[T]):
    """Named instances with get-or-create (对位 Java `*Registry`).

    Makes per-resource circuit breakers / rate limiters reusable instead of
    constructing a new one per call. Thread-safe; the factory runs under the
    registry lock so two callers cannot create duplicate instances.
    """

    def __init__(self, factory: Callable[[str], T] | None = None) -> None:
        self._factory = factory
        self._items: dict[str, T] = {}
        self._lock = threading.Lock()

    def get_or_create(self, name: str, factory: Callable[[str], T] | None = None) -> T:
        maker = factory or self._factory
        if maker is None:
            raise ValueError("a factory is required (constructor or per-call)")
        if not name:
            raise ValueError("name must not be blank")
        with self._lock:
            if name not in self._items:
                self._items[name] = maker(name)
            return self._items[name]

    def find(self, name: str) -> T | None:
        with self._lock:
            return self._items.get(name)

    def register(self, name: str, item: T) -> None:
        if not name:
            raise ValueError("name must not be blank")
        with self._lock:
            self._items[name] = item

    def remove(self, name: str) -> T | None:
        with self._lock:
            return self._items.pop(name, None)

    def keys(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._items)

    def size(self) -> int:
        with self._lock:
            return len(self._items)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()


__all__ = ["Retryer", "RetryExhaustedError", "Debouncer", "NamedRegistry"]
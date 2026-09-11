"""Circuit breaker with sliding-window failure tracking."""

from __future__ import annotations

from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Deque

from .clock import Clock, SystemClock
from .errors import CircuitOpen


class CircuitState(StrEnum):
    """Circuit breaker lifecycle states."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass(frozen=True, slots=True)
class CircuitBreakerConfig:
    """Configuration for `CircuitBreaker`.

    `failure_rate_threshold` is a number in `[0.0, 1.0]` evaluated against
    the most recent `sliding_window_size` outcomes. It is only applied once
    `minimum_calls` outcomes have been recorded; below that threshold the
    breaker relies solely on `failure_threshold` (consecutive failures).
    """

    failure_threshold: int = 5
    failure_rate_threshold: float = 0.5
    sliding_window_size: int = 20
    minimum_calls: int = 10
    open_duration: float = 30.0
    half_open_max_calls: int = 1

    def __post_init__(self) -> None:
        if self.failure_threshold < 1:
            raise ValueError("CircuitBreakerConfig.failure_threshold must be >= 1")
        if not 0.0 <= self.failure_rate_threshold <= 1.0:
            raise ValueError("failure_rate_threshold must be in [0.0, 1.0]")
        if self.sliding_window_size < 1:
            raise ValueError("sliding_window_size must be >= 1")
        if self.minimum_calls < 1:
            raise ValueError("minimum_calls must be >= 1")
        if self.open_duration <= 0:
            raise ValueError("open_duration must be positive")
        if self.half_open_max_calls < 1:
            raise ValueError("half_open_max_calls must be >= 1")


@dataclass
class _SlidingWindow:
    """Bounded history of recent outcomes. `True` is success, `False` is failure."""

    capacity: int
    outcomes: Deque[bool] = field(default_factory=deque)

    def __post_init__(self) -> None:
        # Replace the unbounded placeholder with a bounded deque.
        self.outcomes = deque(maxlen=self.capacity)

    def record(self, success: bool) -> None:
        self.outcomes.append(success)

    def failures(self) -> int:
        return sum(1 for outcome in self.outcomes if not outcome)

    def calls(self) -> int:
        return len(self.outcomes)

    def failure_rate(self) -> float:
        if not self.outcomes:
            return 0.0
        return self.failures() / len(self.outcomes)


class CircuitBreaker:
    """Closed/half-open/open circuit breaker driven by a sliding window."""

    def __init__(self, config: CircuitBreakerConfig, clock: Clock = SystemClock()) -> None:
        self._config = config
        self._clock = clock
        self._state: CircuitState = CircuitState.CLOSED
        self._consecutive_failures = 0
        self._window = _SlidingWindow(capacity=config.sliding_window_size)
        self._opened_at: float | None = None
        self._half_open_in_flight = 0
        self._half_open_successes = 0

    @property
    def state(self) -> CircuitState:
        """The state after reconciling any elapsed `open_duration`."""
        self._maybe_close()
        return self._state

    @property
    def config(self) -> CircuitBreakerConfig:
        return self._config

    def reset(self) -> None:
        """Force the breaker back to `CLOSED`, dropping all recorded outcomes."""
        self._state = CircuitState.CLOSED
        self._consecutive_failures = 0
        self._window = _SlidingWindow(capacity=self._config.sliding_window_size)
        self._opened_at = None
        self._half_open_in_flight = 0
        self._half_open_successes = 0

    def _maybe_close(self) -> None:
        if self._state is not CircuitState.OPEN:
            return
        assert self._opened_at is not None
        if self._clock.now() - self._opened_at >= self._config.open_duration:
            self._state = CircuitState.HALF_OPEN
            self._half_open_in_flight = 0
            self._half_open_successes = 0

    def _should_open(self) -> bool:
        cfg = self._config
        if self._consecutive_failures >= cfg.failure_threshold:
            return True
        if self._window.calls() < cfg.minimum_calls:
            return False
        return self._window.failure_rate() >= cfg.failure_rate_threshold

    def allow(self) -> bool:
        """Reserve a slot for one call. Returns `False` if the call must be rejected."""
        self._maybe_close()
        if self._state is CircuitState.CLOSED:
            return True
        if self._state is CircuitState.OPEN:
            return False
        # HALF_OPEN
        if self._half_open_in_flight >= self._config.half_open_max_calls:
            return False
        self._half_open_in_flight += 1
        return True

    def record_success(self) -> None:
        self._maybe_close()
        self._consecutive_failures = 0
        if self._state is CircuitState.HALF_OPEN:
            self._half_open_successes += 1
            if self._half_open_successes >= self._config.half_open_max_calls:
                self.reset()
            return
        self._window.record(True)

    def record_failure(self) -> None:
        self._maybe_close()
        self._consecutive_failures += 1
        if self._state is CircuitState.HALF_OPEN:
            self._open_again()
            return
        self._window.record(False)
        if self._should_open():
            self._open_again()

    def _open_again(self) -> None:
        self._state = CircuitState.OPEN
        self._opened_at = self._clock.now()

    def _retry_after(self) -> float:
        if self._state is not CircuitState.OPEN or self._opened_at is None:
            return 0.0
        elapsed = self._clock.now() - self._opened_at
        return max(0.0, self._config.open_duration - elapsed)

    async def call(self, op: Callable[[], Awaitable[Any]]) -> Any:
        if not callable(op):
            raise TypeError("CircuitBreaker.call requires an awaitable callable")
        if not self.allow():
            raise CircuitOpen(
                f"circuit breaker is {self._state.value}",
                retry_after=self._retry_after(),
            )
        try:
            result = await op()
        except BaseException:
            self.record_failure()
            raise
        else:
            self.record_success()
            return result

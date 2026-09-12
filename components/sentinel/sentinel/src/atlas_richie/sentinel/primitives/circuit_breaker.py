"""基于滑动窗口的熔断器。
----
`CircuitBreaker` 通过跟踪最近 `sliding_window_size` 次调用的成败
以及连续失败次数，决定是否从 `CLOSED` 转到 `OPEN` 状态。

状态机：

- `CLOSED`：正常放行。`record_failure` 累加连续失败计数，并把结果
  写入滑动窗口；当满足"连续失败 ≥ `failure_threshold`"或
  "窗口失败率 ≥ `failure_rate_threshold`（且样本数 ≥ `minimum_calls`）"
  时跳到 `OPEN`。
- `OPEN`：拒绝所有调用；`open_duration` 秒后自动迁移到 `HALF_OPEN`。
- `HALF_OPEN`：放行最多 `half_open_max_calls` 个试探调用；任一失败
  立刻回到 `OPEN`，连续 `half_open_max_calls` 个成功则完全恢复为
  `CLOSED`。

`Clock` 注入后即可在 `ManualClock` 下做确定性测试。

English
--------
Circuit breaker with sliding-window failure tracking.

`CircuitBreaker` tracks outcomes in a sliding window of size
`sliding_window_size` and counts consecutive failures. From `CLOSED`
it transitions to `OPEN` when either `failure_threshold` consecutive
failures accumulate, or the window's failure rate meets
`failure_rate_threshold` (only after `minimum_calls` samples).

State machine:

- `CLOSED` — pass through. `record_failure` increments the consecutive
  counter and writes the outcome to the window; trips to `OPEN` when
  the consecutive threshold or the rate threshold is met.
- `OPEN` — every call is rejected. After `open_duration` seconds the
  state automatically transitions to `HALF_OPEN`.
- `HALF_OPEN` — at most `half_open_max_calls` probe calls are
  admitted. Any failure re-opens the breaker; that many consecutive
  successes fully restore `CLOSED`.

`Clock` is injected so the breaker is unit-testable with
`ManualClock`."""

from __future__ import annotations

from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Deque

from .clock import Clock, SystemClock
from ..errors import CircuitOpen


class CircuitState(StrEnum):
    """中文
    ----
    熔断器生命周期状态：`CLOSED` / `OPEN` / `HALF_OPEN`。

    English
    --------
    Circuit breaker lifecycle states.
    """

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass(frozen=True, slots=True)
class CircuitBreakerConfig:
    """中文
    ----
    `CircuitBreaker` 的配置。

    - `failure_threshold`：连续失败多少次后直接跳闸。
    - `failure_rate_threshold`：`[0.0, 1.0]` 区间内的失败率阈值，基于
      最近 `sliding_window_size` 次结果计算；只有累计样本数
      不少于 `minimum_calls` 时才生效。
    - `sliding_window_size`：滑动窗口容量。
    - `minimum_calls`：启用失败率判定的最小样本数；不足时仅靠
      `failure_threshold` 判定。
    - `open_duration`：进入 `OPEN` 状态后，自动迁移到 `HALF_OPEN`
      之前需要等待的秒数。
    - `half_open_max_calls`：`HALF_OPEN` 阶段允许通过的试探调用数。

    English
    --------
    Configuration for `CircuitBreaker`.

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
    """中文
    ----
    最近调用的有界结果记录。`True` 表示成功，`False` 表示失败。

    English
    --------
    Bounded history of recent outcomes. `True` is success, `False` is failure.
    """

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
    """中文
    ----
    以滑动窗口驱动的 closed/half-open/open 熔断器。

    English
    --------
    Closed/half-open/open circuit breaker driven by a sliding window.
    """

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
        """中文
        ----
        读取时先对过期的 `open_duration` 做调和，返回当前状态。

        English
        --------
        The state after reconciling any elapsed `open_duration`.
        """
        self._maybe_close()
        return self._state

    @property
    def config(self) -> CircuitBreakerConfig:
        return self._config

    def reset(self) -> None:
        """中文
        ----
        强制把熔断器回到 `CLOSED`，丢弃所有已记录的结果。

        English
        --------
        Force the breaker back to `CLOSED`, dropping all recorded outcomes.
        """
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
        """中文
        ----
        为一次调用预留名额。返回 `False` 表示该调用必须被拒绝。

        English
        --------
        Reserve a slot for one call. Returns `False` if the call must be rejected.
        """
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
        """中文
        ----
        在熔断器治理下执行一个可等待的 operation。

        Args:
            op: 零参、可等待的 callable；返回结果会被原样返回。

        Returns:
            `op()` 的返回值（成功路径）。

        Raises:
            TypeError: `op` 不是 callable。
            CircuitOpen: 熔断器当前为 `OPEN` 或 `HALF_OPEN` 已满。
            BaseException: `op()` 抛出的任何异常会被原样上抛。

        English
        --------
        Execute one awaitable operation under the breaker's governance.

        Args:
            op: Zero-arg awaitable callable. Its return value is
                forwarded to the caller on success.

        Returns:
            Whatever `op()` returns on the success path.

        Raises:
            TypeError: if `op` is not callable.
            CircuitOpen: if the breaker is `OPEN` or `HALF_OPEN` is full.
            BaseException: any exception raised by `op()` is re-raised.
        """
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

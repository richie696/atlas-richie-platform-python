"""带幂等键 gating 的 retry 策略与执行器。
----
`RetryExecutor` 在 `RetryPolicy` 的约束下重试一个可等待的 operation，
并通过 `IdempotencyKey` 决定某个调用是否安全可重试。设计要点：

- **指数退避 + jitter**：`delay_for(attempt)` 计算第 `attempt` 次
  重试的退避基数，再叠加 `[0, jitter]` 比例的扰动。
- **总耗时预算**：`max_elapsed` 限制整个重试窗口的 wall-clock
  累计耗时（含 sleep），超出后立即停止。
- **首字节保险**：`first_byte_only=True` 时，已经上报过 first byte
  的 attempt 即使失败也不再重试，避免给服务端造成重复副作用
  （例如 SSE 流已开始推送进度事件）。
- **可注入的依赖**：`Clock` / `Sleep` / `RandomSource` 都可注入，
  单测可完全脱离 wall clock 验证退避与超时。

English
--------
Retry policy and executor with idempotency-key gating.

`RetryExecutor` runs an awaitable operation under a `RetryPolicy` and
consults an `IdempotencyKey` to decide whether a given call is safe
to retry. The design covers:

- Exponential backoff with jitter (`delay_for`).
- An overall wall-clock budget (`max_elapsed`) that bounds the total
  retry window including sleep.
- A "first-byte" guard: when `first_byte_only=True`, attempts that
  have already signalled a first byte are not retried even on
  failure, to avoid re-running a server-side task whose effects are
  already in flight (e.g. an SSE stream that started emitting
  progress events).
- Injected `Clock` / `Sleep` / `RandomSource` so unit tests can
  reason about backoff and timeouts without touching wall time."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from .clock import Clock, Sleep, SystemClock, system_sleep
from .random_source import RandomSource, SystemRandom
from ..errors import RetryExhausted, RetryNotPermitted
from .idempotency import IdempotencyKey, StatelessIdempotencyKey


@dataclass
class FirstByteSignal:
    """中文
    ----
    被包装 operation 在收到第一个字节时翻起的可变标志。

    `RetryExecutor` 在每次 attempt 之间检查该标志：当
    `RetryPolicy.first_byte_only=True` 时，已经收到 first byte 的
    attempt 即使抛异常也不再重试。

    English
    --------
    A mutable flag a wrapped operation flips when its first byte arrives.

    `RetryExecutor` checks this flag between attempts: when
    `RetryPolicy.first_byte_only` is `True`, an attempt that has already
    received a byte is not retried even if it raised.
    """

    arrived: bool = False

    def mark(self) -> None:
        self.arrived = True


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """中文
    ----
    `RetryExecutor` 的配置。所有字段在构造时校验，错误配置会在
    第一次失败之前就被拒。

    - `max_attempts`：最多尝试次数（含首次）。
    - `initial_delay`：第一次重试前的初始延迟。
    - `max_delay`：单次退避的上限。
    - `max_elapsed`：整个重试窗口允许的 wall-clock 总耗时
      （含 sleep）；`0.0` 表示不限制。
    - `multiplier`：指数退避的倍率，必须 `>= 1.0`。
    - `jitter`：`[0.0, 1.0]` 范围内的相对扰动幅度。
    - `retriable_exceptions`：哪些异常类型允许重试。
    - `first_byte_only`：见模块 docstring 的"首字节保险"。

    English
    --------
    Configuration for `RetryExecutor`.

    All fields are validated up-front so a misconfigured policy fails at
    construction time, not at first failure.

    `first_byte_only` controls retry behavior for streaming-style
    operations. When `True`, `RetryExecutor` only retries a failure that
    occurred before the wrapped callable reported a "first byte" via a
    `FirstByteSignal`; further exceptions are surfaced to the caller
    rather than retried. This avoids re-running a server-side task whose
    effects are already in flight (e.g. an SSE stream that started
    emitting progress events).
    """

    max_attempts: int = 3
    initial_delay: float = 0.1
    max_delay: float = 10.0
    max_elapsed: float = 30.0
    multiplier: float = 2.0
    jitter: float = 0.0
    retriable_exceptions: tuple[type[BaseException], ...] = (Exception,)
    first_byte_only: bool = False

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("RetryPolicy.max_attempts must be >= 1")
        if self.initial_delay < 0:
            raise ValueError("RetryPolicy.initial_delay must be non-negative")
        if self.max_delay < self.initial_delay:
            raise ValueError("RetryPolicy.max_delay must be >= initial_delay")
        if self.max_elapsed < 0:
            raise ValueError("RetryPolicy.max_elapsed must be non-negative")
        if self.multiplier < 1.0:
            raise ValueError("RetryPolicy.multiplier must be >= 1.0")
        if not 0.0 <= self.jitter <= 1.0:
            raise ValueError("RetryPolicy.jitter must be in [0.0, 1.0]")
        if not self.retriable_exceptions:
            raise ValueError("RetryPolicy.retriable_exceptions must not be empty")

    def delay_for(self, attempt: int, random_source: RandomSource) -> float:
        """中文
        ----
        计算指定 attempt 的退避基数（未叠加 jitter）。

        Args:
            attempt: 1-based；第 1 次 attempt 返回 `0.0`（不延迟）。
            random_source: 当 `jitter > 0.0` 时用于在区间
                `[base - spread, base + spread]` 内采样。

        Returns:
            退避秒数。

        Raises:
            ValueError: `attempt < 1`。

        English
        --------
        Compute the pre-jitter backoff for the given attempt (1-indexed).
        """
        if attempt < 1:
            raise ValueError("attempt must be >= 1")
        if attempt == 1:
            base = 0.0
        else:
            base = self.initial_delay * (self.multiplier ** (attempt - 2))
        base = min(base, self.max_delay)
        if self.jitter == 0.0:
            return base
        spread = base * self.jitter
        return random_source.uniform(base - spread, base + spread)

    def is_retriable(self, exception: BaseException) -> bool:
        """中文
        ----
        判断 `exception` 是否在 `retriable_exceptions` 名单内。

        English
        --------
        Whether `exception` is in the configured retriable tuple.
        """
        return isinstance(exception, self.retriable_exceptions)


@dataclass(frozen=True, slots=True)
class RetryEvent:
    """中文
    ----
    一次 attempt 的结果，回调 `on_retry` 时使用。

    Attributes:
        attempt: 刚刚失败的那次 attempt（1-indexed）。
        delay: 距下次 attempt 的退避基数（未叠加 jitter），单位秒；
            当不再调度重试时为 `0.0`。
        exception: 失败 attempt 抛出的异常。
        elapsed: 从 `RetryExecutor.execute` 起始到当前 attempt
            失败的 wall-clock 累计秒数。

    English
    --------
    One attempt outcome reported to the optional `on_retry` hook.

    Attributes:
        attempt: The 1-indexed attempt number that just failed.
        delay: The pre-jitter wait, in seconds, before the next attempt.
            `0.0` when no further attempt is scheduled.
        exception: The exception raised by the failed attempt.
        elapsed: Wall-clock seconds from `RetryExecutor.execute` start to
            the moment this attempt failed.
    """

    attempt: int
    delay: float
    exception: BaseException
    elapsed: float


@dataclass(frozen=True, slots=True)
class RetryExecutor:
    """中文
    ----
    在 `RetryPolicy` 与注入的时间 / 睡眠 / 随机 / 幂等策略下，
    执行一个可等待 operation。

    English
    --------
    Runs an async operation under a `RetryPolicy` with injected time and sleep.
    """

    policy: RetryPolicy
    clock: Clock = field(default_factory=SystemClock)
    sleep: Sleep = field(default_factory=system_sleep)
    random_source: RandomSource = field(default_factory=SystemRandom)
    idempotency_key: IdempotencyKey = field(default_factory=StatelessIdempotencyKey)

    async def execute(
        self,
        op: Callable[[], Awaitable[Any]],
        *,
        on_retry: Callable[[RetryEvent], None] | None = None,
        first_byte: FirstByteSignal | None = None,
    ) -> Any:
        """中文
        ----
        在重试策略与幂等 gating 下执行 `op`。

        行为约定：

        - 当 `IdempotencyKey.derive(op)` 返回 `None` 时，只尝试一次；
          失败时抛 `RetryNotPermitted`。
        - 当 `first_byte_only=True` 且 `first_byte` 不为 `None` 时，
          每次 attempt 开始前会清空 `arrived` 标志；已经上报过 first
          byte 的 attempt 不再重试。
        - 触发退避时会先调 `on_retry(RetryEvent(...))`，再
          `await self.sleep(delay)`。

        Args:
            op: 零参可等待的 callable。
            on_retry: 每次重试前回调（可选）。
            first_byte: 与 `RetryPolicy.first_byte_only` 配对的信号
                对象（可选）。

        Returns:
            `op()` 的首次成功返回值。

        Raises:
            TypeError: `op` 不可调用。
            ValueError: `first_byte_only=True` 但未提供 `first_byte`。
            RetryNotPermitted: 幂等策略拒绝重试且首次失败。
            RetryExhausted: 重试次数 / 耗时预算耗尽仍未成功。
            BaseException: 不可重试的异常会被原样上抛。

        English
        --------
        Execute `op` under the retry policy with idempotency gating.
        """
        if not callable(op):
            raise TypeError("RetryExecutor.execute requires an awaitable callable")
        if self.policy.first_byte_only and first_byte is None:
            raise ValueError(
                "RetryPolicy.first_byte_only=True requires a non-None first_byte signal"
            )
        idempotency_tag = self.idempotency_key.derive(op)
        if idempotency_tag is None:
            try:
                return await op()
            except BaseException as first:
                raise RetryNotPermitted(
                    "operation is not idempotent and cannot be retried"
                ) from first

        start = self.clock.now()
        last_exception: BaseException | None = None
        attempts_made = 0
        for attempt in range(1, self.policy.max_attempts + 1):
            attempts_made = attempt
            if first_byte is not None:
                first_byte.arrived = False
            try:
                return await op()
            except BaseException as exc:  # noqa: BLE001 - retriable filter applied below
                last_exception = exc
                elapsed = self.clock.now() - start
                if not self.policy.is_retriable(exc):
                    raise
                if self.policy.first_byte_only and first_byte is not None and first_byte.arrived:
                    raise
                if attempt >= self.policy.max_attempts:
                    break
                delay = self.policy.delay_for(attempt + 1, self.random_source)
                if self.policy.max_elapsed > 0 and elapsed + delay > self.policy.max_elapsed:
                    break
                if on_retry is not None:
                    on_retry(
                        RetryEvent(
                            attempt=attempt,
                            delay=delay,
                            exception=exc,
                            elapsed=elapsed,
                        )
                    )
                if delay > 0:
                    await self.sleep(delay)
        assert last_exception is not None  # loop body only runs after a caught exception
        raise RetryExhausted(
            f"retry exhausted after {attempts_made} attempts",
            attempts=attempts_made,
            last_exception=last_exception,
        ) from last_exception

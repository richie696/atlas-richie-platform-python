"""令牌桶限流器。
----
`TokenBucket` 是一种按速率（token / 秒）补充、按请求消耗的限流器。
桶容量是 `capacity`，每个请求默认消耗 `tokens_per_acquire` 个令牌。
提供三种获取令牌的入口：

- `try_acquire()`：非阻塞；令牌不足时返回 `False`。
- `acquire(..., max_wait=0.0)`：非等待；令牌不足时立即抛
  `RateLimitExceeded`。
- `acquire(..., max_wait > 0.0)`：等待刷新；超过 `max_wait` 抛
  `RateLimitExceeded`，`retry_after` 字段告知还需等多久。

时间源 `Clock` / `Sleep` 注入后，可完全脱离 wall clock 做单测。

English
--------
Token-bucket rate limiter.

`TokenBucket` refills at `refill_rate` tokens per second up to
`capacity`, and consumes `tokens_per_acquire` tokens per request
(default 1). Three acquisition paths are provided:

- `try_acquire()` — non-blocking; returns `False` when tokens are
  insufficient.
- `acquire(..., max_wait=0.0)` — fail fast; raises
  `RateLimitExceeded` immediately when empty.
- `acquire(..., max_wait > 0.0)` — wait for refill; raises
  `RateLimitExceeded` after the budget is exhausted. The
  `retry_after` field reports the remaining wait.

`Clock` and `Sleep` are injected so the limiter can be unit-tested
without touching the wall clock."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from .clock import Clock, Sleep, SystemClock, system_sleep
from .errors import RateLimitExceeded


@dataclass(frozen=True, slots=True)
class TokenBucketConfig:
    """中文
    ----
    `TokenBucket` 的配置。

    - `capacity`：桶可容纳的最大令牌数。
    - `refill_rate`：令牌补充速率（个 / 秒）。
    - `tokens_per_acquire`：单次请求默认消耗的令牌数（默认 1）。

    English
    --------
    Configuration for `TokenBucket`.

    `capacity` is the maximum number of tokens the bucket can hold. Tokens
    refill at `refill_rate` tokens per second, and a request consumes
    `tokens_per_acquire` tokens (default 1).
    """

    capacity: int
    refill_rate: float
    tokens_per_acquire: int = 1

    def __post_init__(self) -> None:
        if self.capacity < 1:
            raise ValueError("TokenBucketConfig.capacity must be >= 1")
        if self.refill_rate <= 0:
            raise ValueError("TokenBucketConfig.refill_rate must be positive")
        if self.tokens_per_acquire < 1:
            raise ValueError("tokens_per_acquire must be >= 1")
        if self.tokens_per_acquire > self.capacity:
            raise ValueError("tokens_per_acquire must be <= capacity")


class TokenBucket:
    """中文
    ----
    异步令牌桶限流器。

    - `try_acquire` 非阻塞，令牌不足时返回 `False`。
    - `acquire` 在令牌不足时通过注入的 `sleep` 周期性重试；超过
      `max_wait` 时抛 `RateLimitExceeded`。

    English
    --------
    Async token-bucket rate limiter.

    `try_acquire` is non-blocking and returns `False` when the request
    would have to wait. `acquire` awaits a fresh token, calling the
    injected `sleep` between checks; it raises `RateLimitExceeded` when
    `max_wait` is reached.
    """

    def __init__(
        self,
        config: TokenBucketConfig,
        clock: Clock = SystemClock(),
        sleep: Sleep = system_sleep(),
    ) -> None:
        self._config = config
        self._clock = clock
        self._sleep = sleep
        self._tokens = float(config.capacity)
        self._last_refill = clock.now()

    @property
    def available(self) -> float:
        """中文
        ----
        按最新一次的令牌补充计算后，当前桶内可用令牌数。

        English
        --------
        Current token count after the most recent refill calculation.
        """
        self._refill()
        return self._tokens

    @property
    def config(self) -> TokenBucketConfig:
        return self._config

    def _refill(self) -> None:
        now = self._clock.now()
        elapsed = now - self._last_refill
        if elapsed <= 0:
            return
        self._tokens = min(
            float(self._config.capacity),
            self._tokens + elapsed * self._config.refill_rate,
        )
        self._last_refill = now

    def try_acquire(self, tokens: int | None = None) -> bool:
        """中文
        ----
        立即尝试消耗令牌；不足时返回 `False`，不抛异常。

        Args:
            tokens: 要消耗的令牌数；为 `None` 时使用配置中的
                `tokens_per_acquire`。

        Returns:
            成功扣减返回 `True`；令牌不足返回 `False`。

        Raises:
            ValueError: `tokens < 1`。

        English
        --------
        Consume tokens immediately if available, else return `False`.

        Args:
            tokens: Number of tokens to consume. When `None`, uses
                the configured `tokens_per_acquire`.

        Returns:
            `True` if the tokens were deducted; `False` if not
            enough tokens were available.

        Raises:
            ValueError: if `tokens < 1`.
        """
        if tokens is None:
            tokens = self._config.tokens_per_acquire
        if tokens < 1:
            raise ValueError("tokens must be >= 1")
        self._refill()
        if self._tokens >= tokens:
            self._tokens -= tokens
            return True
        return False

    def time_to_tokens(self, tokens: int | None = None) -> float:
        """中文
        ----
        返回距离 `tokens` 个令牌可用还需等待的秒数；若已可用则返回
        `0.0`。

        Args:
            tokens: 目标令牌数；为 `None` 时使用 `tokens_per_acquire`。

        Returns:
            距离令牌可用的剩余秒数；已可用时为 `0.0`。

        English
        --------
        Seconds until `tokens` become available. Zero if already available.
        """
        if tokens is None:
            tokens = self._config.tokens_per_acquire
        if tokens < 1:
            raise ValueError("tokens must be >= 1")
        self._refill()
        if self._tokens >= tokens:
            return 0.0
        deficit = tokens - self._tokens
        return deficit / self._config.refill_rate

    async def acquire(
        self,
        tokens: int | None = None,
        *,
        max_wait: float = 0.0,
    ) -> None:
        """中文
        ----
        消耗令牌；不足时通过注入的 `sleep` 周期性等待刷新。

        - `max_wait == 0.0` 且令牌不足：立即抛 `RateLimitExceeded`。
        - `max_wait > 0.0`：等待至令牌可被扣减；超过 `max_wait` 时
          抛 `RateLimitExceeded`，`retry_after` 指示还需等待的秒数。

        Args:
            tokens: 目标令牌数；为 `None` 时使用 `tokens_per_acquire`。
            max_wait: 允许的最长等待时间（秒）。

        Raises:
            RateLimitExceeded: 令牌不足且等待时间耗尽。
            ValueError: `tokens < 1` 或 `max_wait < 0`。

        English
        --------
        Consume tokens, awaiting via the injected sleep.

        Raises `RateLimitExceeded` immediately when `max_wait == 0` and the
        bucket is empty, or after the wait budget is exhausted.
        """
        if tokens is None:
            tokens = self._config.tokens_per_acquire
        if tokens < 1:
            raise ValueError("tokens must be >= 1")
        if max_wait < 0:
            raise ValueError("max_wait must be non-negative")
        if self.try_acquire(tokens):
            return
        if max_wait == 0.0:
            raise RateLimitExceeded(
                "token bucket is empty and no wait is allowed",
                retry_after=self.time_to_tokens(tokens),
            )
        deadline = self._clock.now() + max_wait
        while True:
            wait_seconds = self.time_to_tokens(tokens)
            if wait_seconds <= 0:
                if self.try_acquire(tokens):
                    return
            remaining = deadline - self._clock.now()
            if remaining <= 0:
                raise RateLimitExceeded(
                    "token bucket did not refill within max_wait",
                    retry_after=self.time_to_tokens(tokens),
                )
            await self._sleep(min(wait_seconds, remaining))

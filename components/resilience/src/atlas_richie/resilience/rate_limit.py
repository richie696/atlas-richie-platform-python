"""Token-bucket rate limiter."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from .clock import Clock, Sleep, SystemClock, system_sleep
from .errors import RateLimitExceeded


@dataclass(frozen=True, slots=True)
class TokenBucketConfig:
    """Configuration for `TokenBucket`.

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
    """Async token-bucket rate limiter.

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
        """Current token count after the most recent refill calculation."""
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
        """Consume tokens immediately if available, else return `False`."""
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
        """Seconds until `tokens` become available. Zero if already available."""
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
        """Consume tokens, awaiting via the injected sleep.

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

"""Retry policy and executor with idempotency-key gating."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from .clock import Clock, RandomSource, Sleep, SystemClock, SystemRandom, system_sleep
from .errors import RetryExhausted, RetryNotPermitted
from .idempotency import IdempotencyKey, StatelessIdempotencyKey


@dataclass
class FirstByteSignal:
    """A mutable flag a wrapped operation flips when its first byte arrives.

    `RetryExecutor` checks this flag between attempts: when
    `RetryPolicy.first_byte_only` is `True`, an attempt that has already
    received a byte is not retried even if it raised.
    """

    arrived: bool = False

    def mark(self) -> None:
        self.arrived = True


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Configuration for `RetryExecutor`.

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
        """Compute the pre-jitter backoff for the given attempt (1-indexed)."""
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
        return isinstance(exception, self.retriable_exceptions)


@dataclass(frozen=True, slots=True)
class RetryEvent:
    """One attempt outcome reported to the optional `on_retry` hook.

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
    """Runs an async operation under a `RetryPolicy` with injected time and sleep."""

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

"""Sentinel 基础原语(primitives)公共 API。
----
集中 re-export 5 类原语 + 注入式时间/随机源。M0 不改任何公开类名,
保留 `RetryPolicy` / `RetryExecutor` / `IdempotencyKey` / 3 个实现 /
`CircuitBreaker` / `TokenBucket` / `Bulkhead` / `Clock` / 3 个 Clock
实现 / `RandomSource` / 3 个 RandomSource 实现 / `system_sleep` /
`Sleep` 等。

公开符号清单(与 `atlas_richie.resilience.__all__` 1:1):

- Retry: `RetryPolicy` / `RetryExecutor` / `FirstByteSignal` / `RetryEvent`
- Circuit breaker: `CircuitBreaker` / `CircuitBreakerConfig` / `CircuitState`
- Rate limit: `TokenBucket` / `TokenBucketConfig`
- Bulkhead: `Bulkhead` / `BulkheadConfig`
- Idempotency: `IdempotencyKey` / `StatelessIdempotencyKey` /
  `NeverIdempotencyKey` / `CallableIdempotencyKey`
- Time: `Clock` / `SystemClock` / `ManualClock` / `Sleep` / `system_sleep`
- Random: `RandomSource` / `SystemRandom` / `DeterministicRandom`

错误类见 `atlas_richie.sentinel.errors`(M0 阶段 5 个原语异常 +
`ResilienceError` + 根 `SentinelError`)。

English
--------
Public API of Sentinel low-level primitives.

Centralised re-export of five primitive families plus injectable
time / randomness sources. M0 keeps the original public class names
(`RetryPolicy` / `RetryExecutor` / `IdempotencyKey` / `CircuitBreaker`
etc.) — this is a no-behaviour-change migration."""

from __future__ import annotations

from .bulkhead import Bulkhead, BulkheadConfig
from .circuit_breaker import CircuitBreaker, CircuitBreakerConfig, CircuitState
from .clock import Clock, ManualClock, Sleep, SystemClock, system_sleep
from .idempotency import (
    CallableIdempotencyKey,
    IdempotencyKey,
    NeverIdempotencyKey,
    StatelessIdempotencyKey,
)
from .random_source import DeterministicRandom, RandomSource, SystemRandom
from .retry import FirstByteSignal, RetryEvent, RetryExecutor, RetryPolicy
from .token_bucket import TokenBucket, TokenBucketConfig

__all__ = [
    # Retry
    "FirstByteSignal",
    "RetryEvent",
    "RetryExecutor",
    "RetryPolicy",
    # Circuit breaker
    "CircuitBreaker",
    "CircuitBreakerConfig",
    "CircuitState",
    # Rate limit
    "TokenBucket",
    "TokenBucketConfig",
    # Bulkhead
    "Bulkhead",
    "BulkheadConfig",
    # Idempotency
    "CallableIdempotencyKey",
    "IdempotencyKey",
    "NeverIdempotencyKey",
    "StatelessIdempotencyKey",
    # Time
    "Clock",
    "ManualClock",
    "Sleep",
    "SystemClock",
    "system_sleep",
    # Random
    "DeterministicRandom",
    "RandomSource",
    "SystemRandom",
]

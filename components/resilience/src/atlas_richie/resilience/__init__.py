"""框架无关的 resilience 原语集合（与具体业务 / 中间件解耦）。
----
本包对外暴露 retry、circuit-breaker、rate-limit、bulkhead、idempotency-key
五类原语，时间 / sleep / 随机数均通过 `Clock` / `Sleep` / `RandomSource`
注入，每个原语都能在不触碰 wall clock 的前提下做单测。

公共 API：

- Retry：`RetryPolicy` / `RetryExecutor` / `FirstByteSignal` / `RetryEvent`
- Circuit breaker：`CircuitBreaker` / `CircuitBreakerConfig` / `CircuitState`
- Rate limit：`TokenBucket` / `TokenBucketConfig`
- Bulkhead：`Bulkhead` / `BulkheadConfig`
- Idempotency：`IdempotencyKey` / `StatelessIdempotencyKey` /
  `NeverIdempotencyKey` / `CallableIdempotencyKey`
- Time / sleep / randomness：`Clock` / `SystemClock` / `ManualClock` /
  `Sleep` / `system_sleep` / `RandomSource` / `SystemRandom` /
  `DeterministicRandom`
- Errors：`ResilienceError` / `RetryExhausted` / `RetryNotPermitted` /
  `CircuitOpen` / `RateLimitExceeded` / `BulkheadFull`

English
--------
Framework-neutral resilience primitives for Atlas Richie components.

This package exposes retry, circuit-breaker, rate-limit, bulkhead, and
idempotency-key primitives. Time, sleep, and randomness are injected so
every primitive is testable without touching the wall clock."""

from .bulkhead import Bulkhead, BulkheadConfig
from .circuit_breaker import CircuitBreaker, CircuitBreakerConfig, CircuitState
from .clock import (
    Clock,
    DeterministicRandom,
    ManualClock,
    RandomSource,
    Sleep,
    SystemClock,
    SystemRandom,
    system_sleep,
)
from .errors import (
    BulkheadFull,
    CircuitOpen,
    RateLimitExceeded,
    ResilienceError,
    RetryExhausted,
    RetryNotPermitted,
)
from .idempotency import (
    CallableIdempotencyKey,
    IdempotencyKey,
    NeverIdempotencyKey,
    StatelessIdempotencyKey,
)
from .rate_limit import TokenBucket, TokenBucketConfig
from .retry import FirstByteSignal, RetryEvent, RetryExecutor, RetryPolicy

__all__ = [
    "Bulkhead",
    "BulkheadConfig",
    "BulkheadFull",
    "CallableIdempotencyKey",
    "CircuitBreaker",
    "CircuitBreakerConfig",
    "CircuitOpen",
    "CircuitState",
    "Clock",
    "DeterministicRandom",
    "FirstByteSignal",
    "IdempotencyKey",
    "ManualClock",
    "NeverIdempotencyKey",
    "RandomSource",
    "RateLimitExceeded",
    "ResilienceError",
    "RetryEvent",
    "RetryExecutor",
    "RetryExhausted",
    "RetryNotPermitted",
    "RetryPolicy",
    "Sleep",
    "StatelessIdempotencyKey",
    "SystemClock",
    "SystemRandom",
    "TokenBucket",
    "TokenBucketConfig",
    "system_sleep",
]

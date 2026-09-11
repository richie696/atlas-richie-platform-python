"""Framework-neutral resilience primitives for Atlas Richie components.

This package exposes retry, circuit-breaker, rate-limit, bulkhead, and
idempotency-key primitives. Time, sleep, and randomness are injected so
every primitive is testable without touching the wall clock.
"""

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

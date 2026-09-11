"""Resilience failure types, classified by portable behavior."""

from __future__ import annotations

from atlas_richie.contracts import PlatformError


class ResilienceError(PlatformError):
    """Base class for controlled resilience failures."""


class RetryExhausted(ResilienceError):
    """Retry attempts were exhausted without success, or the elapsed budget elapsed."""

    def __init__(self, message: str, *, attempts: int, last_exception: BaseException) -> None:
        super().__init__(message)
        self.attempts = attempts
        self.last_exception = last_exception


class RetryNotPermitted(ResilienceError):
    """The configured idempotency policy refused to retry the operation."""


class CircuitOpen(ResilienceError):
    """A call was rejected because the circuit breaker is currently open."""

    def __init__(self, message: str, *, retry_after: float) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class RateLimitExceeded(ResilienceError):
    """A rate limiter denied the request because the bucket was empty and no wait was allowed."""

    def __init__(self, message: str, *, retry_after: float) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class BulkheadFull(ResilienceError):
    """A bulkhead rejected the request because the concurrency cap is at capacity and no wait was allowed."""

    def __init__(self, message: str, *, retry_after: float) -> None:
        super().__init__(message)
        self.retry_after = retry_after

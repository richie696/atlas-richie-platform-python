# atlas-richie-resilience

Framework-neutral resilience primitives for Atlas Richie components.

This package provides the building blocks that allow other components to
absorb transient failures and protect shared resources without pulling in
third-party resilience libraries:

- `RetryPolicy` + `RetryExecutor` — exponential backoff, jitter, elapsed budget,
  retriable-exception filter, optional idempotency-key guard.
- `IdempotencyKey` Protocol — strategy for deriving an idempotency tag from an
  operation so `RetryExecutor` only retries safe work.
- `CircuitBreaker` — closed/half_open/open state machine with sliding window,
  failure-count and failure-rate thresholds, and a configurable open duration.
- `TokenBucket` RateLimiter — capacity and refill rate, with immediate
  `try_acquire` and time-bounded `acquire`.
- `Bulkhead` — semaphore-based concurrency cap with an optional wait timeout.

`Clock` and `Sleep` are injected, so unit tests use a `ManualClock` and a
fake sleeper without touching `time` or `asyncio.sleep`.

The package depends only on `atlas-richie-contracts` for shared error and
lifecycle types. It has no third-party runtime dependencies.

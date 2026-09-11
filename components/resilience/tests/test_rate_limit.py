"""Unit tests for the token-bucket rate limiter."""

from __future__ import annotations

import asyncio
import unittest

from atlas_richie.resilience import (
    ManualClock,
    RateLimitExceeded,
    TokenBucket,
    TokenBucketConfig,
)


class _AdvanceOnSleep:
    """A sleeper that advances a `ManualClock` by the requested duration before returning."""

    def __init__(self, clock: ManualClock) -> None:
        self._clock = clock
        self.delays: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.delays.append(seconds)
        # Hand control back so the bucket loop can re-check after the clock
        # has moved. We must not call `clock.advance` before yielding, or the
        # bucket would see the new time without having slept at all.
        await asyncio.sleep(0)
        self._clock.advance(seconds)


class TokenBucketConfigValidationTest(unittest.TestCase):
    def test_rejects_invalid_parameters(self) -> None:
        with self.assertRaises(ValueError):
            TokenBucketConfig(capacity=0, refill_rate=1.0)
        with self.assertRaises(ValueError):
            TokenBucketConfig(capacity=5, refill_rate=0)
        with self.assertRaises(ValueError):
            TokenBucketConfig(capacity=5, refill_rate=1.0, tokens_per_acquire=0)
        with self.assertRaises(ValueError):
            TokenBucketConfig(capacity=3, refill_rate=1.0, tokens_per_acquire=4)
        with self.assertRaises(ValueError):
            TokenBucketConfig(capacity=5, refill_rate=-1.0)


class TokenBucketTryAcquireTest(unittest.TestCase):
    def test_initial_capacity_is_full(self) -> None:
        clock = ManualClock()
        bucket = TokenBucket(
            TokenBucketConfig(capacity=5, refill_rate=1.0),
            clock=clock,
        )
        self.assertEqual(5.0, bucket.available)

    def test_consumes_tokens(self) -> None:
        clock = ManualClock()
        bucket = TokenBucket(
            TokenBucketConfig(capacity=5, refill_rate=1.0),
            clock=clock,
        )
        self.assertTrue(bucket.try_acquire())
        self.assertEqual(4.0, bucket.available)
        self.assertTrue(bucket.try_acquire(2))
        self.assertEqual(2.0, bucket.available)

    def test_returns_false_when_empty(self) -> None:
        clock = ManualClock()
        bucket = TokenBucket(
            TokenBucketConfig(capacity=1, refill_rate=1.0),
            clock=clock,
        )
        self.assertTrue(bucket.try_acquire())
        self.assertFalse(bucket.try_acquire())

    def test_refills_with_clock_advance(self) -> None:
        clock = ManualClock()
        bucket = TokenBucket(
            TokenBucketConfig(capacity=2, refill_rate=1.0),
            clock=clock,
        )
        self.assertTrue(bucket.try_acquire(2))
        self.assertFalse(bucket.try_acquire())
        clock.advance(1.0)
        self.assertTrue(bucket.try_acquire())
        self.assertEqual(0.0, bucket.available)

    def test_does_not_exceed_capacity(self) -> None:
        clock = ManualClock()
        bucket = TokenBucket(
            TokenBucketConfig(capacity=2, refill_rate=1.0),
            clock=clock,
        )
        clock.advance(100.0)
        self.assertEqual(2.0, bucket.available)

    def test_time_to_tokens(self) -> None:
        clock = ManualClock()
        bucket = TokenBucket(
            TokenBucketConfig(capacity=2, refill_rate=1.0),
            clock=clock,
        )
        bucket.try_acquire(2)
        self.assertAlmostEqual(1.0, bucket.time_to_tokens())
        clock.advance(0.5)
        self.assertAlmostEqual(0.5, bucket.time_to_tokens())


class TokenBucketAcquireTest(unittest.IsolatedAsyncioTestCase):
    async def test_acquire_immediate_when_tokens_available(self) -> None:
        clock = ManualClock()
        bucket = TokenBucket(
            TokenBucketConfig(capacity=3, refill_rate=1.0),
            clock=clock,
        )
        await bucket.acquire()
        self.assertEqual(2.0, bucket.available)

    async def test_acquire_fails_fast_when_no_wait(self) -> None:
        clock = ManualClock()
        bucket = TokenBucket(
            TokenBucketConfig(capacity=1, refill_rate=1.0),
            clock=clock,
        )
        await bucket.acquire()
        with self.assertRaises(RateLimitExceeded) as ctx:
            await bucket.acquire()
        self.assertGreater(ctx.exception.retry_after, 0.0)

    async def test_acquire_waits_and_succeeds(self) -> None:
        clock = ManualClock()
        sleeper = _AdvanceOnSleep(clock)
        bucket = TokenBucket(
            TokenBucketConfig(capacity=1, refill_rate=2.0),
            clock=clock,
            sleep=sleeper,
        )
        await bucket.acquire()
        await bucket.acquire(max_wait=2.0)
        # First acquire consumed 1 token; second waited 0.5 s for the bucket
        # to refill at 2 tokens / s.
        self.assertEqual([0.5], sleeper.delays)
        self.assertEqual(0.0, bucket.available)

    async def test_acquire_raises_when_max_wait_elapses(self) -> None:
        clock = ManualClock()
        sleeper = _AdvanceOnSleep(clock)
        bucket = TokenBucket(
            TokenBucketConfig(capacity=1, refill_rate=1.0),
            clock=clock,
            sleep=sleeper,
        )
        await bucket.acquire()
        with self.assertRaises(RateLimitExceeded):
            await bucket.acquire(max_wait=0.1)

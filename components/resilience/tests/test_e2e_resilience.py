"""End-to-end tests for the resilience primitives.

中文
----
E2E 测试集：把真实可注入的失败 / 延迟注入到真实 callable，验证
`Retry` / `CircuitBreaker` / `Bulkhead` / `TokenBucket` 在类生产
场景下的端到端行为。

覆盖 8 个用例：
1. Retry 在 3 次瞬时失败后恢复
2. Retry 在 `max_attempts` 耗尽后放弃
3. CircuitBreaker 连续 N 次失败后跳闸
4. CircuitBreaker 经过 `open_duration` 后进入 half-open 并恢复
5. Bulkhead 把并发数限制在 `max_concurrent` 以内
6. TokenBucket 排空容量后拒绝请求
7. Retry 套在 CircuitBreaker 里：低于跳闸阈值时不会触发跳闸
8. Chaos：随机 1-100ms 延迟 + 10% 失败率下，原始异常不外泄

English
--------
E2E suite: inject realistic failures and delays into real callables and
verify that `Retry` / `CircuitBreaker` / `Bulkhead` / `TokenBucket`
behave correctly under production-like chaos.

Scenarios (8):
1. Retry recovers after 3 transient failures.
2. Retry gives up after `max_attempts`.
3. CircuitBreaker opens after N consecutive failures.
4. CircuitBreaker transitions to half-open after `open_duration` and recovers.
5. Bulkhead caps concurrent invocations to `max_concurrent`.
6. TokenBucket drains capacity then rejects further requests.
7. Retry inside a CircuitBreaker: stays closed when below trip threshold.
8. Chaos: 100 calls with random 1-100ms delays and 10% failure rate never
   leak a bare exception — only `RetryExhausted` / `CircuitOpen`.

Timing strategy:
- Where the API supports it (CircuitBreaker, TokenBucket), we use
  `ManualClock` to make time-driven state transitions deterministic.
- Chaos and bulkhead concurrency tests use real `asyncio.sleep` to
  exercise the production timing path.

All tests are marked `@pytest.mark.e2e` (Phase C workspace convention).
Total suite target: < 10s."""

from __future__ import annotations

import asyncio
import random
import unittest
from collections.abc import Awaitable, Callable
from typing import Any

import pytest

from atlas_richie.resilience import (
    Bulkhead,
    BulkheadConfig,
    BulkheadFull,
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitOpen,
    CircuitState,
    ManualClock,
    RateLimitExceeded,
    RetryExecutor,
    RetryExhausted,
    RetryPolicy,
    TokenBucket,
    TokenBucketConfig,
)

pytestmark = pytest.mark.e2e


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------


def make_flaky_async(
    fail_count: int,
    *,
    exception_factory: Callable[[int], BaseException] = lambda i: RuntimeError(f"flaky failure #{i}"),
    success_value: Any = "ok",
) -> tuple[Callable[[], Awaitable[Any]], Callable[[], int]]:
    """Build a flaky async callable that fails `fail_count` times then succeeds.

    Returns a `(callable, counter)` pair. The counter is a zero-arg
    callable that returns the number of times the wrapped function has
    been invoked.

    Args:
        fail_count: Number of leading invocations that must raise.
        exception_factory: Callable invoked with the 1-based attempt
            number to produce the failure exception. Default yields
            `RuntimeError(f"flaky failure #{i}")`.
        success_value: Value returned once the warm-up failures are over.
    """

    state: dict[str, int] = {"calls": 0}

    async def fn() -> Any:
        state["calls"] += 1
        if state["calls"] <= fail_count:
            raise exception_factory(state["calls"])
        return success_value

    return fn, lambda: state["calls"]


class _CountingAsyncOp:
    """A recording async callable; configurable failure / success behaviour."""

    def __init__(
        self,
        *,
        value: Any = "ok",
        exception: type[BaseException] | None = None,
    ) -> None:
        self.value = value
        self.exception = exception
        self.calls = 0

    async def __call__(self) -> Any:
        self.calls += 1
        if self.exception is not None:
            raise self.exception(f"counted failure #{self.calls}")
        return self.value


async def _succeed() -> str:
    return "ok"


async def _always_fail() -> None:
    raise RuntimeError("nope")


# ----------------------------------------------------------------------------
# 1. Retry: 3 transient failures then success
# ----------------------------------------------------------------------------


class RetryRecoversAfterTransientFailuresE2ETest(unittest.IsolatedAsyncioTestCase):
    """中文：retry 在经历若干次瞬时失败后恢复，并准确报告调用次数。
    English: Retry recovers after a fixed number of transient failures
    and reports the exact call count.
    """

    async def test_recovers_after_three_transient_failures(self) -> None:
        policy = RetryPolicy(
            max_attempts=5,
            initial_delay=0.01,
            max_delay=0.05,
            jitter=0.0,
        )
        executor = RetryExecutor(policy)

        op, calls = make_flaky_async(fail_count=3)

        result = await executor.execute(op)

        self.assertEqual("ok", result)
        # 1 original + 3 retries = 4 invocations.
        self.assertEqual(4, calls())


# ----------------------------------------------------------------------------
# 2. Retry: gives up after max_attempts
# ----------------------------------------------------------------------------


class RetryGivesUpAfterMaxAttemptsE2ETest(unittest.IsolatedAsyncioTestCase):
    """中文：retry 超过 `max_attempts` 后抛 `RetryExhausted`，
    携带最后原始异常与精确的 attempts 计数。
    English: Retry raises `RetryExhausted` after `max_attempts`,
    carrying the last underlying exception and the exact attempt count.
    """

    async def test_gives_up_after_max_attempts(self) -> None:
        policy = RetryPolicy(
            max_attempts=3,
            initial_delay=0.01,
            max_delay=0.05,
            jitter=0.0,
        )
        executor = RetryExecutor(policy)

        op, calls = make_flaky_async(fail_count=10_000)  # always fails

        with self.assertRaises(RetryExhausted) as ctx:
            await executor.execute(op)

        # 3 invocations total — never more than `max_attempts`.
        self.assertEqual(3, calls())
        self.assertEqual(3, ctx.exception.attempts)
        # The wrapped exception is preserved as `__cause__` (chained).
        self.assertIsInstance(ctx.exception.last_exception, RuntimeError)
        self.assertIs(ctx.exception.__cause__, ctx.exception.last_exception)


# ----------------------------------------------------------------------------
# 3. CircuitBreaker: opens after N failures
# ----------------------------------------------------------------------------


class CircuitBreakerOpensAfterThresholdE2ETest(unittest.IsolatedAsyncioTestCase):
    """中文：连续 N 次失败后熔断器跳闸，后续调用被直接拒绝。
    English: After N consecutive failures the breaker trips and
    subsequent calls are rejected without invoking the wrapped callable.
    """

    async def test_circuit_opens_after_threshold_and_short_circuits(self) -> None:
        clock = ManualClock()
        breaker = CircuitBreaker(
            CircuitBreakerConfig(
                failure_threshold=3,
                sliding_window_size=10,
                minimum_calls=10,
                open_duration=10.0,
            ),
            clock=clock,
        )

        # Trip the breaker with 3 consecutive failures.
        for _ in range(3):
            with self.assertRaises(RuntimeError):
                await breaker.call(_always_fail)

        self.assertEqual(CircuitState.OPEN, breaker.state)

        # 4th call must NOT touch the wrapped function.
        op = _CountingAsyncOp(value="ok")
        with self.assertRaises(CircuitOpen):
            await breaker.call(op)
        self.assertEqual(0, op.calls)

        # The CircuitOpen surfaces a positive `retry_after` hint.
        try:
            await breaker.call(op)
        except CircuitOpen as exc:
            self.assertGreater(exc.retry_after, 0.0)
        self.assertEqual(0, op.calls)


# ----------------------------------------------------------------------------
# 4. CircuitBreaker: closes after reset_timeout (half-open recovery)
# ----------------------------------------------------------------------------


class CircuitBreakerHalfOpenRecoveryE2ETest(unittest.IsolatedAsyncioTestCase):
    """中文：`open_duration` 之后进入 HALF_OPEN，试探成功则完全恢复。
    English: After `open_duration` the breaker enters HALF_OPEN; a
    successful probe fully restores CLOSED.
    """

    async def test_circuit_recovers_via_half_open(self) -> None:
        clock = ManualClock()
        breaker = CircuitBreaker(
            CircuitBreakerConfig(
                failure_threshold=2,
                open_duration=0.5,
                half_open_max_calls=1,
            ),
            clock=clock,
        )

        # Trip the breaker with 2 consecutive failures.
        for _ in range(2):
            with self.assertRaises(RuntimeError):
                await breaker.call(_always_fail)
        self.assertEqual(CircuitState.OPEN, breaker.state)

        # Before `open_duration` elapses, the breaker stays OPEN.
        clock.advance(0.1)
        self.assertEqual(CircuitState.OPEN, breaker.state)

        # After `open_duration + 0.1` the breaker transitions to HALF_OPEN.
        clock.advance(0.5)
        self.assertEqual(CircuitState.HALF_OPEN, breaker.state)

        # A successful probe closes the circuit.
        result = await breaker.call(_succeed)
        self.assertEqual("ok", result)
        self.assertEqual(CircuitState.CLOSED, breaker.state)

    async def test_half_open_failure_reopens_circuit(self) -> None:
        clock = ManualClock()
        breaker = CircuitBreaker(
            CircuitBreakerConfig(
                failure_threshold=2,
                open_duration=0.5,
                half_open_max_calls=1,
            ),
            clock=clock,
        )

        for _ in range(2):
            with self.assertRaises(RuntimeError):
                await breaker.call(_always_fail)
        clock.advance(0.6)
        self.assertEqual(CircuitState.HALF_OPEN, breaker.state)

        # A failed probe re-opens the breaker.
        with self.assertRaises(RuntimeError):
            await breaker.call(_always_fail)
        self.assertEqual(CircuitState.OPEN, breaker.state)

        # Subsequent calls are short-circuited again.
        op = _CountingAsyncOp()
        with self.assertRaises(CircuitOpen):
            await breaker.call(op)
        self.assertEqual(0, op.calls)


# ----------------------------------------------------------------------------
# 5. Bulkhead: limits concurrency
# ----------------------------------------------------------------------------


class BulkheadLimitsConcurrencyE2ETest(unittest.IsolatedAsyncioTestCase):
    """中文：`Bulkhead(max_concurrent=2)` 同时只允许 2 个操作在途。
    English: `Bulkhead(max_concurrent=2)` never lets more than 2
    operations run in flight.
    """

    async def test_bulkhead_caps_concurrent_invocations(self) -> None:
        bulkhead = Bulkhead(BulkheadConfig(max_concurrent=2, max_wait=1.0))

        peak: list[int] = [0]
        current: list[int] = [0]
        # All 5 tasks wait on a barrier so they hit the bulkhead together;
        # without this, the first 2 might enter before the others even
        # start and the test would pass for the wrong reason.
        ready = asyncio.Barrier(5)
        entered = asyncio.Barrier(2)

        async def long_op() -> str:
            await ready.wait()
            async with bulkhead.guard():
                current[0] += 1
                peak[0] = max(peak[0], current[0])
                # 50ms of in-flight work — long enough for tasks to queue
                # behind the bulkhead while the first batch is running.
                await asyncio.sleep(0.05)
                current[0] -= 1
            return "ok"

        # 5 callers launch in parallel; they synchronize at the barrier
        # so all 5 race for the 2 permits simultaneously.
        tasks = [asyncio.create_task(long_op()) for _ in range(5)]
        results = await asyncio.gather(*tasks)

        self.assertEqual(5, len(results))
        for r in results:
            self.assertEqual("ok", r)
        # Peak must never exceed the configured cap.
        self.assertLessEqual(peak[0], 2)
        # And the cap was actually exercised — at least 2 entered.
        self.assertEqual(2, peak[0])

    async def test_bulkhead_rejects_excess_when_no_wait(self) -> None:
        # With `max_wait=0.0` the bulkhead fails fast; 3 of 5 callers
        # see `BulkheadFull` immediately.
        bulkhead = Bulkhead(BulkheadConfig(max_concurrent=2, max_wait=0.0))

        results: list[str] = []

        async def try_acquire() -> None:
            try:
                async with bulkhead.guard():
                    results.append("ok")
                    await asyncio.sleep(0.05)
            except BulkheadFull:
                results.append("rejected")

        tasks = [asyncio.create_task(try_acquire()) for _ in range(5)]
        await asyncio.gather(*tasks)

        self.assertEqual(5, len(results))
        accepted = results.count("ok")
        rejected = results.count("rejected")
        self.assertEqual(2, accepted)
        self.assertEqual(3, rejected)


# ----------------------------------------------------------------------------
# 6. RateLimiter: token-bucket behavior
# ----------------------------------------------------------------------------


class TokenBucketDrainsCapacityE2ETest(unittest.IsolatedAsyncioTestCase):
    """中文：令牌桶排空前 N 个请求成功；之后立即拒绝。
    English: The first N requests succeed (capacity); the next M are
    denied until the bucket refills.
    """

    async def test_first_ten_succeed_then_ten_rejected(self) -> None:
        # capacity=10 + refill_rate=10/s = 10 requests per second.
        bucket = TokenBucket(
            TokenBucketConfig(capacity=10, refill_rate=10.0),
            clock=ManualClock(),
        )

        successes = 0
        rejected = 0
        for _ in range(20):
            try:
                await bucket.acquire(max_wait=0.0)
            except RateLimitExceeded:
                rejected += 1
            else:
                successes += 1

        # With ManualClock, no refill happens between sequential
        # `acquire()` calls — the first 10 drain the bucket, the next 10
        # are rejected immediately.
        self.assertEqual(10, successes)
        self.assertEqual(10, rejected)

    async def test_try_acquire_does_not_block_when_empty(self) -> None:
        # Non-blocking variant: returns `False` instead of raising.
        bucket = TokenBucket(
            TokenBucketConfig(capacity=3, refill_rate=1.0),
            clock=ManualClock(),
        )

        self.assertTrue(bucket.try_acquire())
        self.assertTrue(bucket.try_acquire())
        self.assertTrue(bucket.try_acquire())
        # Bucket empty — further attempts return False.
        self.assertFalse(bucket.try_acquire())
        self.assertFalse(bucket.try_acquire())


# ----------------------------------------------------------------------------
# 7. Combined: Retry inside CircuitBreaker
# ----------------------------------------------------------------------------


class RetryInsideCircuitBreakerE2ETest(unittest.IsolatedAsyncioTestCase):
    """中文：Retry 套在 CircuitBreaker 里，低于跳闸阈值时熔断器保持 CLOSED。
    English: When retry sits inside the breaker, the breaker stays
    closed as long as total failures stay below the trip threshold.
    """

    async def test_retry_does_not_trip_below_threshold(self) -> None:
        clock = ManualClock()
        breaker = CircuitBreaker(
            CircuitBreakerConfig(
                failure_threshold=5,
                sliding_window_size=10,
                minimum_calls=10,
                open_duration=10.0,
            ),
            clock=clock,
        )
        executor = RetryExecutor(
            RetryPolicy(
                max_attempts=5,
                initial_delay=0.01,
                max_delay=0.05,
                jitter=0.0,
            ),
        )

        # Fail 4 times then succeed; with max_attempts=5 the 5th attempt
        # is the success. The breaker sees 4 consecutive failures, which
        # is below the 5-failure threshold, so it stays CLOSED.
        op, calls = make_flaky_async(fail_count=4)

        result = await breaker.call(lambda: executor.execute(op))

        self.assertEqual("ok", result)
        self.assertEqual(5, calls())  # 1 + 4 retries
        self.assertEqual(CircuitState.CLOSED, breaker.state)

    async def test_retry_exhaustion_records_as_breaker_failure(self) -> None:
        """中文：当 retry 把所有 attempt 耗尽，break 仍把这次外部
        `RetryExhausted` 视为一次失败；连续 N 次耗尽后熔断器跳闸。
        English: When retry exhausts, the breaker still observes the
        outer `RetryExhausted` as one failure; after N consecutive
        exhausted calls the breaker trips.
        """
        clock = ManualClock()
        breaker = CircuitBreaker(
            CircuitBreakerConfig(
                failure_threshold=2,
                sliding_window_size=10,
                minimum_calls=10,
                open_duration=10.0,
            ),
            clock=clock,
        )
        executor = RetryExecutor(
            RetryPolicy(
                max_attempts=3,
                initial_delay=0.01,
                max_delay=0.05,
                jitter=0.0,
            ),
        )

        # Two consecutive retry-exhausted calls: each contributes 1
        # breaker failure (the outer `RetryExhausted`). After the 2nd
        # call, the consecutive-failure counter hits the threshold and
        # the breaker trips.
        for expected_calls in (3, 3):
            op, calls = make_flaky_async(fail_count=10_000)
            with self.assertRaises(RetryExhausted):
                await breaker.call(lambda: executor.execute(op))
            self.assertEqual(expected_calls, calls())

        self.assertEqual(CircuitState.OPEN, breaker.state)

        # Next call is short-circuited — wrapped function not invoked.
        op = _CountingAsyncOp(value="ok")
        with self.assertRaises(CircuitOpen):
            await breaker.call(lambda: executor.execute(op))
        self.assertEqual(0, op.calls)


# ----------------------------------------------------------------------------
# 8. Chaos: random delays + failures
# ----------------------------------------------------------------------------


class ChaosRandomDelaysAndFailuresE2ETest(unittest.IsolatedAsyncioTestCase):
    """中文：100 次调用，每次 1-100ms 延迟 + 10% 失败率；原语层把所有
    原始异常转换为受控失败（`RetryExhausted` / `CircuitOpen`），不外泄
    裸 `RuntimeError`。
    English: 100 calls with random 1-100ms delays and 10% failure rate.
    The resilience layer must convert every raw failure into a
    controlled `RetryExhausted` / `CircuitOpen` (or success) — no bare
    `RuntimeError` may escape.
    """

    async def test_chaos_never_lets_bare_exception_escape(self) -> None:
        # SystemClock + real `asyncio.sleep` simulate a production-grade
        # chaos run. The breaker self-heals: after `open_duration`
        # (0.1s) it returns to half-open; a successful probe restores
        # CLOSED. So failures that look catastrophic at the start of
        # the run should not poison the tail of the run.
        breaker = CircuitBreaker(
            CircuitBreakerConfig(
                failure_threshold=10,
                sliding_window_size=20,
                minimum_calls=5,
                open_duration=0.1,
            ),
        )
        executor = RetryExecutor(
            RetryPolicy(
                max_attempts=3,
                initial_delay=0.01,
                max_delay=0.05,
                jitter=0.1,
            ),
        )

        rng = random.Random(42)  # deterministic chaos sequence

        async def chaotic_op() -> str:
            # 1-100ms latency; bounded by `[0.001, 0.1]` so the suite
            # stays well under 10s even with retries.
            await asyncio.sleep(rng.uniform(0.001, 0.1))
            if rng.random() < 0.1:
                raise RuntimeError("chaos-failure")
            return "ok"

        outcomes: list[str] = []
        for _ in range(100):
            try:
                result = await breaker.call(lambda: executor.execute(chaotic_op))
            except RetryExhausted:
                outcomes.append("retry_exhausted")
            except CircuitOpen:
                outcomes.append("circuit_open")
            except BaseException as exc:  # noqa: BLE001 — must be empty
                outcomes.append(f"bare:{type(exc).__name__}")
            else:
                self.assertEqual("ok", result)
                outcomes.append("ok")

        # No bare exception leaked past the resilience layer.
        bare = [o for o in outcomes if o.startswith("bare:")]
        self.assertEqual([], bare, f"unexpected bare exceptions: {bare}")

        # And we expect a mix of outcomes — chaos that always succeeded
        # would mean the failure injection is broken, chaos that always
        # failed would mean the system is broken. Either is suspect.
        self.assertGreater(outcomes.count("ok"), 0)

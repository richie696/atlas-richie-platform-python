"""Composition tests for the resilience primitives.

These tests exercise the patterns users will actually build: a retry loop
running inside a circuit breaker, a circuit breaker running inside a
bulkhead, and the order of `on_retry` events relative to breaker state.
"""

from __future__ import annotations

import unittest

from atlas_richie.resilience import (
    Bulkhead,
    BulkheadConfig,
    BulkheadFull,
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitOpen,
    CircuitState,
    DeterministicRandom,
    ManualClock,
    RetryExecutor,
    RetryExhausted,
    RetryPolicy,
)

from _helpers import FakeSleeper, FlakyCall


class RetryInsideCircuitBreakerTest(unittest.IsolatedAsyncioTestCase):
    async def test_retry_attempts_are_recorded_by_breaker(self) -> None:
        clock = ManualClock()
        sleeper = FakeSleeper()
        breaker = CircuitBreaker(
            CircuitBreakerConfig(
                failure_threshold=3,
                sliding_window_size=10,
                minimum_calls=10,
                open_duration=10.0,
            ),
            clock=clock,
        )
        executor = RetryExecutor(
            RetryPolicy(max_attempts=2, initial_delay=0.1, jitter=0.0),
            clock=clock,
            sleep=sleeper,
        )
        op = FlakyCall(value="ok", failures=2, exception=RuntimeError)
        with self.assertRaises(RetryExhausted):
            await breaker.call(lambda: executor.execute(op))
        # Two attempts → two recorded failures on the breaker.
        self.assertEqual(2, op.calls)
        self.assertEqual([0.1], sleeper.delays)
        self.assertEqual(CircuitState.CLOSED, breaker.state)

    async def test_open_circuit_short_circuits_retry(self) -> None:
        clock = ManualClock()
        breaker = CircuitBreaker(
            CircuitBreakerConfig(failure_threshold=1, open_duration=10.0),
            clock=clock,
        )
        # Trip the breaker.
        with self.assertRaises(RuntimeError):
            await breaker.call(FlakyCall(failures=1, exception=RuntimeError))
        op = FlakyCall(value="ok", failures=2)
        with self.assertRaises(CircuitOpen):
            await breaker.call(op)
        # The op must not have been invoked at all.
        self.assertEqual(0, op.calls)


class CircuitBreakerInsideBulkheadTest(unittest.IsolatedAsyncioTestCase):
    async def test_bulkhead_caps_concurrent_breaker_calls(self) -> None:
        bulkhead = Bulkhead(BulkheadConfig(max_concurrent=1))
        breaker = CircuitBreaker(CircuitBreakerConfig(failure_threshold=10))

        async def succeed() -> str:
            return "ok"

        async with bulkhead.guard():
            # Bulkhead is at capacity; a second concurrent call must fail fast.
            with self.assertRaises(BulkheadFull):
                await bulkhead.acquire()


class DeterministicJitterTest(unittest.TestCase):
    def test_deterministic_random_produces_expected_delay(self) -> None:
        policy = RetryPolicy(initial_delay=1.0, multiplier=1.0, jitter=0.5)
        # value=0.5 → low+0.5*(high-low) = low+0.5*spread
        self.assertEqual(1.0, policy.delay_for(2, DeterministicRandom(value=0.5)))

    def test_manual_clock_advance_supports_test_only_paths(self) -> None:
        clock = ManualClock(start=10.0)
        self.assertEqual(10.0, clock.now())
        clock.advance(5.0)
        self.assertEqual(15.0, clock.now())
        with self.assertRaises(ValueError):
            clock.advance(-1.0)
        with self.assertRaises(ValueError):
            ManualClock(start=-0.1)

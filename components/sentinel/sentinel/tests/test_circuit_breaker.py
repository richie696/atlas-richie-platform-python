"""Unit tests for the circuit breaker."""

from __future__ import annotations

import unittest

from atlas_richie.sentinel.errors import CircuitOpen
from atlas_richie.sentinel.primitives import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitState,
    ManualClock,
)

from _helpers import CountingCall, FlakyCall


class CircuitBreakerConfigValidationTest(unittest.TestCase):
    def test_rejects_invalid_parameters(self) -> None:
        with self.assertRaises(ValueError):
            CircuitBreakerConfig(failure_threshold=0)
        with self.assertRaises(ValueError):
            CircuitBreakerConfig(failure_rate_threshold=1.5)
        with self.assertRaises(ValueError):
            CircuitBreakerConfig(sliding_window_size=0)
        with self.assertRaises(ValueError):
            CircuitBreakerConfig(minimum_calls=0)
        with self.assertRaises(ValueError):
            CircuitBreakerConfig(open_duration=0)
        with self.assertRaises(ValueError):
            CircuitBreakerConfig(half_open_max_calls=0)


class CircuitBreakerStateTest(unittest.IsolatedAsyncioTestCase):
    async def test_opens_on_consecutive_failures(self) -> None:
        clock = ManualClock()
        breaker = CircuitBreaker(
            CircuitBreakerConfig(
                failure_threshold=3,
                sliding_window_size=10,
                minimum_calls=10,
                open_duration=5.0,
            ),
            clock=clock,
        )
        for _ in range(3):
            with self.assertRaises(RuntimeError):
                await breaker.call(FlakyCall(failures=1, exception=RuntimeError))
        self.assertEqual(CircuitState.OPEN, breaker.state)
        with self.assertRaises(CircuitOpen):
            await breaker.call(CountingCall())

    async def test_opens_on_failure_rate(self) -> None:
        clock = ManualClock()
        breaker = CircuitBreaker(
            CircuitBreakerConfig(
                failure_threshold=100,
                failure_rate_threshold=0.5,
                sliding_window_size=4,
                minimum_calls=4,
                open_duration=5.0,
            ),
            clock=clock,
        )
        for _ in range(2):
            with self.assertRaises(RuntimeError):
                await breaker.call(FlakyCall(failures=1, exception=RuntimeError))
        await breaker.call(CountingCall(value="ok"))
        with self.assertRaises(RuntimeError):
            await breaker.call(FlakyCall(failures=1, exception=RuntimeError))
        self.assertEqual(CircuitState.OPEN, breaker.state)

    async def test_does_not_open_below_minimum_calls(self) -> None:
        clock = ManualClock()
        breaker = CircuitBreaker(
            CircuitBreakerConfig(
                failure_threshold=100,
                failure_rate_threshold=0.5,
                sliding_window_size=10,
                minimum_calls=5,
            ),
            clock=clock,
        )
        for _ in range(3):
            with self.assertRaises(RuntimeError):
                await breaker.call(FlakyCall(failures=1, exception=RuntimeError))
        self.assertEqual(CircuitState.CLOSED, breaker.state)

    async def test_transitions_to_half_open_after_open_duration(self) -> None:
        clock = ManualClock()
        breaker = CircuitBreaker(
            CircuitBreakerConfig(
                failure_threshold=2,
                open_duration=5.0,
                half_open_max_calls=1,
            ),
            clock=clock,
        )
        for _ in range(2):
            with self.assertRaises(RuntimeError):
                await breaker.call(FlakyCall(failures=1, exception=RuntimeError))
        self.assertEqual(CircuitState.OPEN, breaker.state)
        clock.advance(5.0)
        self.assertEqual(CircuitState.HALF_OPEN, breaker.state)

    async def test_half_open_success_closes_circuit(self) -> None:
        clock = ManualClock()
        breaker = CircuitBreaker(
            CircuitBreakerConfig(
                failure_threshold=2,
                open_duration=5.0,
                half_open_max_calls=2,
            ),
            clock=clock,
        )
        for _ in range(2):
            with self.assertRaises(RuntimeError):
                await breaker.call(FlakyCall(failures=1, exception=RuntimeError))
        clock.advance(5.0)
        self.assertEqual("ok", await breaker.call(CountingCall(value="ok")))
        self.assertEqual("ok", await breaker.call(CountingCall(value="ok")))
        self.assertEqual(CircuitState.CLOSED, breaker.state)

    async def test_half_open_failure_reopens(self) -> None:
        clock = ManualClock()
        breaker = CircuitBreaker(
            CircuitBreakerConfig(
                failure_threshold=2,
                open_duration=5.0,
                half_open_max_calls=1,
            ),
            clock=clock,
        )
        for _ in range(2):
            with self.assertRaises(RuntimeError):
                await breaker.call(FlakyCall(failures=1, exception=RuntimeError))
        clock.advance(5.0)
        with self.assertRaises(RuntimeError):
            await breaker.call(FlakyCall(failures=1, exception=RuntimeError))
        self.assertEqual(CircuitState.OPEN, breaker.state)

    async def test_rejects_extra_calls_in_half_open(self) -> None:
        clock = ManualClock()
        breaker = CircuitBreaker(
            CircuitBreakerConfig(
                failure_threshold=2,
                open_duration=5.0,
                half_open_max_calls=1,
            ),
            clock=clock,
        )
        for _ in range(2):
            with self.assertRaises(RuntimeError):
                await breaker.call(FlakyCall(failures=1, exception=RuntimeError))
        clock.advance(5.0)
        # First half-open call goes through; the second is rejected.
        with self.assertRaises(RuntimeError):
            await breaker.call(FlakyCall(failures=1, exception=RuntimeError))

    async def test_reset_drops_history(self) -> None:
        clock = ManualClock()
        breaker = CircuitBreaker(
            CircuitBreakerConfig(failure_threshold=2, open_duration=5.0),
            clock=clock,
        )
        for _ in range(2):
            with self.assertRaises(RuntimeError):
                await breaker.call(FlakyCall(failures=1, exception=RuntimeError))
        self.assertEqual(CircuitState.OPEN, breaker.state)
        breaker.reset()
        self.assertEqual(CircuitState.CLOSED, breaker.state)
        self.assertEqual("ok", await breaker.call(CountingCall(value="ok")))

    async def test_circuit_open_carries_retry_after(self) -> None:
        clock = ManualClock()
        breaker = CircuitBreaker(
            CircuitBreakerConfig(failure_threshold=1, open_duration=10.0),
            clock=clock,
        )
        with self.assertRaises(RuntimeError):
            await breaker.call(FlakyCall(failures=1, exception=RuntimeError))
        with self.assertRaises(CircuitOpen) as ctx:
            await breaker.call(CountingCall())
        self.assertGreater(ctx.exception.retry_after, 0.0)
        self.assertLessEqual(ctx.exception.retry_after, 10.0)

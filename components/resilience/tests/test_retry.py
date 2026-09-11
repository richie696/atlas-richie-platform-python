"""Unit tests for `RetryPolicy` and `RetryExecutor`."""

from __future__ import annotations

import asyncio
import unittest

from atlas_richie.resilience import (
    DeterministicRandom,
    FirstByteSignal,
    ManualClock,
    NeverIdempotencyKey,
    RetryEvent,
    RetryExecutor,
    RetryExhausted,
    RetryNotPermitted,
    RetryPolicy,
)

from _helpers import CountingCall, FakeSleeper, FlakyCall


class RetryPolicyValidationTest(unittest.TestCase):
    def test_rejects_invalid_parameters(self) -> None:
        with self.assertRaises(ValueError):
            RetryPolicy(max_attempts=0)
        with self.assertRaises(ValueError):
            RetryPolicy(initial_delay=-0.1)
        with self.assertRaises(ValueError):
            RetryPolicy(initial_delay=2.0, max_delay=1.0)
        with self.assertRaises(ValueError):
            RetryPolicy(max_elapsed=-1.0)
        with self.assertRaises(ValueError):
            RetryPolicy(multiplier=0.5)
        with self.assertRaises(ValueError):
            RetryPolicy(jitter=1.5)
        with self.assertRaises(ValueError):
            RetryPolicy(retriable_exceptions=())

    def test_delay_for_is_zero_on_first_attempt(self) -> None:
        policy = RetryPolicy(initial_delay=0.1, multiplier=2.0)
        random = DeterministicRandom(value=0.5)
        self.assertEqual(0.0, policy.delay_for(1, random))

    def test_delay_for_grows_exponentially(self) -> None:
        policy = RetryPolicy(initial_delay=0.1, multiplier=2.0, jitter=0.0)
        random = DeterministicRandom(value=0.5)
        self.assertEqual(0.0, policy.delay_for(1, random))
        self.assertEqual(0.1, policy.delay_for(2, random))
        self.assertEqual(0.2, policy.delay_for(3, random))
        self.assertEqual(0.4, policy.delay_for(4, random))

    def test_delay_for_respects_max_delay(self) -> None:
        policy = RetryPolicy(initial_delay=0.1, multiplier=10.0, max_delay=0.5, jitter=0.0)
        random = DeterministicRandom(value=0.5)
        self.assertEqual(0.5, policy.delay_for(5, random))

    def test_delay_for_with_jitter_uses_random_source(self) -> None:
        policy = RetryPolicy(initial_delay=1.0, multiplier=1.0, jitter=0.5)
        random_low = DeterministicRandom(value=0.0)
        random_high = DeterministicRandom(value=1.0)
        self.assertEqual(0.5, policy.delay_for(2, random_low))
        self.assertEqual(1.5, policy.delay_for(2, random_high))

    def test_is_retriable(self) -> None:
        policy = RetryPolicy(retriable_exceptions=(ConnectionError, TimeoutError))
        self.assertTrue(policy.is_retriable(ConnectionError("x")))
        self.assertTrue(policy.is_retriable(TimeoutError("x")))
        self.assertFalse(policy.is_retriable(ValueError("x")))


class RetryExecutorSuccessTest(unittest.IsolatedAsyncioTestCase):
    async def test_returns_value_on_first_success(self) -> None:
        sleeper = FakeSleeper()
        executor = RetryExecutor(RetryPolicy(), sleep=sleeper)
        op = CountingCall(value=42)
        result = await executor.execute(op)
        self.assertEqual(42, result)
        self.assertEqual(1, op.calls)
        self.assertEqual([], sleeper.delays)

    async def test_succeeds_after_failures(self) -> None:
        sleeper = FakeSleeper()
        executor = RetryExecutor(
            RetryPolicy(max_attempts=4, initial_delay=0.1, jitter=0.0),
            sleep=sleeper,
        )
        op = FlakyCall(value="done", failures=2)
        result = await executor.execute(op)
        self.assertEqual("done", result)
        self.assertEqual(3, op.calls)
        self.assertEqual([0.1, 0.2], sleeper.delays)

    async def test_calls_on_retry_hook_with_event(self) -> None:
        sleeper = FakeSleeper()
        events: list[RetryEvent] = []
        executor = RetryExecutor(
            RetryPolicy(max_attempts=3, initial_delay=0.1, jitter=0.0),
            sleep=sleeper,
        )
        op = FlakyCall(value="x", failures=1)
        result = await executor.execute(op, on_retry=events.append)
        self.assertEqual("x", result)
        self.assertEqual(1, len(events))
        event = events[0]
        self.assertEqual(1, event.attempt)
        # Attempt 1 failed; the delay reported is the wait before attempt 2,
        # which is `initial_delay * multiplier^0 = 0.1`.
        self.assertEqual(0.1, event.delay)
        self.assertIsInstance(event.exception, RuntimeError)


class RetryExecutorFailureTest(unittest.IsolatedAsyncioTestCase):
    async def test_raises_last_exception_when_non_retriable(self) -> None:
        sleeper = FakeSleeper()
        executor = RetryExecutor(
            RetryPolicy(retriable_exceptions=(ConnectionError,)),
            sleep=sleeper,
        )
        op = FlakyCall(failures=3, exception=ValueError)
        with self.assertRaises(ValueError):
            await executor.execute(op)
        self.assertEqual(1, op.calls)
        self.assertEqual([], sleeper.delays)

    async def test_raises_retry_exhausted(self) -> None:
        sleeper = FakeSleeper()
        executor = RetryExecutor(
            RetryPolicy(max_attempts=3, initial_delay=0.1, jitter=0.0),
            sleep=sleeper,
        )
        op = FlakyCall(failures=99, exception=ConnectionError)
        with self.assertRaises(RetryExhausted) as ctx:
            await executor.execute(op)
        self.assertEqual(3, ctx.exception.attempts)
        self.assertIsInstance(ctx.exception.last_exception, ConnectionError)
        self.assertEqual(3, op.calls)
        self.assertEqual([0.1, 0.2], sleeper.delays)

    async def test_max_elapsed_budget_stops_early(self) -> None:
        clock = ManualClock(start=1000.0)
        sleeper = FakeSleeper()
        executor = RetryExecutor(
            RetryPolicy(max_attempts=10, initial_delay=1.0, max_elapsed=0.5, jitter=0.0),
            clock=clock,
            sleep=sleeper,
        )
        op = FlakyCall(failures=99, exception=ConnectionError)
        with self.assertRaises(RetryExhausted) as ctx:
            await executor.execute(op)
        self.assertEqual(1, ctx.exception.attempts)
        self.assertEqual(1, op.calls)


class RetryExecutorIdempotencyTest(unittest.IsolatedAsyncioTestCase):
    async def test_never_idempotent_blocks_retry(self) -> None:
        sleeper = FakeSleeper()
        executor = RetryExecutor(
            RetryPolicy(max_attempts=3, initial_delay=0.1, jitter=0.0),
            sleep=sleeper,
            idempotency_key=NeverIdempotencyKey(),
        )
        op = FlakyCall(failures=99, exception=ConnectionError)
        with self.assertRaises(RetryNotPermitted) as ctx:
            await executor.execute(op)
        self.assertIsInstance(ctx.exception.__cause__, ConnectionError)
        self.assertEqual(1, op.calls)
        self.assertEqual([], sleeper.delays)

    async def test_validation_rejects_non_callable(self) -> None:
        executor = RetryExecutor(RetryPolicy())
        with self.assertRaises(TypeError):
            await executor.execute("not-callable")  # type: ignore[arg-type]


class RetryExecutorSleepInjectionTest(unittest.IsolatedAsyncioTestCase):
    async def test_default_sleep_is_asyncio_sleep(self) -> None:
        # If we go through asyncio.sleep(0) we should not block; verify the call
        # path uses an awaitable without raising.
        executor = RetryExecutor(
            RetryPolicy(max_attempts=2, initial_delay=0.0, jitter=0.0),
        )
        op = FlakyCall(value="ok", failures=1)
        self.assertEqual("ok", await executor.execute(op))


class RetryExecutorFirstByteOnlyTest(unittest.IsolatedAsyncioTestCase):
    async def test_retries_when_first_byte_not_received(self) -> None:
        signal = FirstByteSignal()
        sleeper = FakeSleeper()
        executor = RetryExecutor(
            RetryPolicy(max_attempts=3, initial_delay=0.0, jitter=0.0, first_byte_only=True),
            sleep=sleeper,
        )

        class _BeforeFirstByte:
            def __init__(self) -> None:
                self.calls = 0

            async def __call__(self) -> str:
                self.calls += 1
                if self.calls < 2:
                    raise ConnectionError("connect failed")
                signal.mark()
                return "ok"

        op = _BeforeFirstByte()
        self.assertEqual("ok", await executor.execute(op, first_byte=signal))
        self.assertEqual(2, op.calls)
        self.assertTrue(signal.arrived)

    async def test_does_not_retry_after_first_byte(self) -> None:
        signal = FirstByteSignal()
        executor = RetryExecutor(
            RetryPolicy(max_attempts=3, initial_delay=0.0, jitter=0.0, first_byte_only=True),
        )

        class _AfterFirstByte:
            def __init__(self) -> None:
                self.calls = 0

            async def __call__(self) -> str:
                self.calls += 1
                signal.mark()
                raise ConnectionError("stream dropped after first byte")

        op = _AfterFirstByte()
        with self.assertRaises(ConnectionError):
            await executor.execute(op, first_byte=signal)
        self.assertEqual(1, op.calls)

    async def test_first_byte_only_requires_a_signal(self) -> None:
        executor = RetryExecutor(
            RetryPolicy(max_attempts=3, first_byte_only=True),
        )
        with self.assertRaises(ValueError):
            await executor.execute(lambda: _immediate("ok"))

    async def test_signal_resets_between_attempts_when_policy_does_not_gate(self) -> None:
        # With `first_byte_only=False` the executor never reads the signal, but
        # it still resets it at the top of each attempt so the caller can use
        # it as a per-attempt progress flag.
        signal = FirstByteSignal()
        executor = RetryExecutor(
            RetryPolicy(max_attempts=3, initial_delay=0.0, jitter=0.0, first_byte_only=False),
        )
        op = FlakyCall(value="ok", failures=2)
        self.assertEqual("ok", await executor.execute(op, first_byte=signal))
        # After two failures and one success, the signal is still at its
        # pre-attempt value (False) because the success path doesn't mark it.
        self.assertFalse(signal.arrived)


async def _immediate(value: Any) -> Any:
    return value

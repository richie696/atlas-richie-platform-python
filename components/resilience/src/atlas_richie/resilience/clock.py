"""Injectable time sources used by every resilience primitive."""

from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Awaitable, Callable
from typing import Protocol


class Clock(Protocol):
    """A monotonic time source. Implementations must never go backwards."""

    def now(self) -> float:
        """Return a monotonically non-decreasing timestamp in seconds."""


class SystemClock:
    """The default `Clock`; backed by `time.monotonic`."""

    def now(self) -> float:
        return time.monotonic()


class ManualClock:
    """A `Clock` whose value is advanced by the test harness.

    The clock value only moves when `advance` is called, so unit tests can
    reason about durations without touching wall time.
    """

    def __init__(self, start: float = 0.0) -> None:
        if start < 0:
            raise ValueError("ManualClock start must be non-negative")
        self._now = start

    def now(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        if seconds < 0:
            raise ValueError("ManualClock.advance must be non-negative")
        self._now += seconds


Sleep = Callable[[float], Awaitable[None]]
"""An awaitable sleep. `system_sleep` is the default factory; tests may replace it."""


def system_sleep() -> Sleep:
    """Return the default `Sleep` callable, bound to `asyncio.sleep`.

    A factory (rather than a function) lets dataclass fields declare
    `field(default_factory=system_sleep)` cleanly: the field receives a
    fresh `Sleep` reference per instance and primitives call it with the
    requested delay.
    """

    async def _sleep(seconds: float) -> None:
        if seconds < 0:
            raise ValueError("sleep duration must be non-negative")
        if seconds > 0:
            await asyncio.sleep(seconds)

    return _sleep


class RandomSource(Protocol):
    """A reproducible random source used by retry jitter and similar features."""

    def uniform(self, low: float, high: float) -> float:
        """Return a uniformly distributed value in `[low, high)`."""


class SystemRandom:
    """The default `RandomSource`; backed by `random.uniform`."""

    def uniform(self, low: float, high: float) -> float:
        return random.uniform(low, high)


class DeterministicRandom:
    """A `RandomSource` that returns a fixed midpoint, for deterministic tests."""

    def __init__(self, value: float = 0.5) -> None:
        if not 0.0 <= value <= 1.0:
            raise ValueError("DeterministicRandom value must be in [0.0, 1.0]")
        self._value = value

    def uniform(self, low: float, high: float) -> float:
        return low + (high - low) * self._value

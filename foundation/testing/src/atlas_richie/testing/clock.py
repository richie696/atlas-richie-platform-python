"""Deterministic clock for time-dependent tests.

Pure standard library. Replaces the ad-hoc `clock = [0.0]` / `lambda: clock[0]`
pattern duplicated across the cache-core, mfa-validation and redis-streammq suites.
Units are the caller's choice: advance by milliseconds for a millisecond clock,
by seconds for a monotonic one.
"""

from __future__ import annotations


class ManualClock:
    """A callable clock whose value only changes when the test advances it."""

    __slots__ = ("_value",)

    def __init__(self, start: float = 0.0) -> None:
        self._value = float(start)

    @property
    def value(self) -> float:
        return self._value

    def __call__(self) -> float:
        return self._value

    def advance(self, delta: float) -> float:
        self._value += delta
        return self._value

    def set(self, value: float) -> float:
        self._value = float(value)
        return self._value


__all__ = ["ManualClock"]

"""Inline test helpers for the resilience suite.

These helpers are imported by each test module as a top-level module
(rather than a relative import) because `components/resilience/tests/`
has no `__init__.py`, matching the rest of the workspace.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any


class FakeSleeper:
    """Records requested sleeps without actually awaiting them."""

    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.delays.append(seconds)

    def total(self) -> float:
        return sum(self.delays)


class FlakyCall:
    """An async callable that fails `failures` times before returning a value."""

    def __init__(self, value: Any = "ok", *, failures: int = 0, exception: type[BaseException] = RuntimeError) -> None:
        self.value = value
        self.failures = failures
        self.exception = exception
        self.calls = 0

    async def __call__(self) -> Any:
        self.calls += 1
        if self.calls <= self.failures:
            raise self.exception(f"flaky failure #{self.calls}")
        return self.value


class CountingCall:
    """An async callable that records every invocation."""

    def __init__(self, value: Any = "ok", *, side_effect: Callable[[int], Awaitable[Any]] | None = None) -> None:
        self.value = value
        self.side_effect = side_effect
        self.calls = 0

    async def __call__(self) -> Any:
        self.calls += 1
        if self.side_effect is not None:
            return await self.side_effect(self.calls)
        return self.value

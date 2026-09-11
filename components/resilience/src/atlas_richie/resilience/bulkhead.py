"""Concurrency-capping bulkhead backed by an asyncio semaphore."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from .clock import Clock, Sleep, SystemClock, system_sleep
from .errors import BulkheadFull


@dataclass(frozen=True, slots=True)
class BulkheadConfig:
    """Configuration for `Bulkhead`.

    `max_concurrent` is the hard cap on in-flight calls. `max_wait` is the
    longest a caller may block waiting for a permit; `0.0` (the default)
    means "fail fast".
    """

    max_concurrent: int
    max_wait: float = 0.0

    def __post_init__(self) -> None:
        if self.max_concurrent < 1:
            raise ValueError("BulkheadConfig.max_concurrent must be >= 1")
        if self.max_wait < 0:
            raise ValueError("BulkheadConfig.max_wait must be non-negative")


class Bulkhead:
    """Async semaphore-based concurrency cap."""

    def __init__(
        self,
        config: BulkheadConfig,
        clock: Clock = SystemClock(),
        sleep: Sleep = system_sleep(),
    ) -> None:
        self._config = config
        self._clock = clock
        self._sleep = sleep
        self._semaphore = asyncio.Semaphore(config.max_concurrent)
        self._in_flight = 0

    @property
    def config(self) -> BulkheadConfig:
        return self._config

    @property
    def in_flight(self) -> int:
        return self._in_flight

    async def acquire(self) -> None:
        """Block until a permit is available, or fail fast per `max_wait`."""
        if self._config.max_wait == 0.0:
            if self._semaphore.locked():
                raise BulkheadFull(
                    "bulkhead is at capacity and no wait is allowed",
                    retry_after=0.0,
                )
            await self._semaphore.acquire()
            self._in_flight += 1
            return
        try:
            await asyncio.wait_for(self._semaphore.acquire(), timeout=self._config.max_wait)
        except TimeoutError as exc:
            raise BulkheadFull(
                "bulkhead did not release a permit within max_wait",
                retry_after=0.0,
            ) from exc
        self._in_flight += 1

    def release(self) -> None:
        """Release a previously acquired permit.

        Calling `release` more times than `acquire` is a programming error;
        `asyncio.Semaphore` will raise `ValueError` in that case.
        """
        self._semaphore.release()
        self._in_flight = max(0, self._in_flight - 1)

    @asynccontextmanager
    async def guard(self) -> AsyncIterator[None]:
        """Context manager that acquires a permit on enter and releases on exit."""
        await self.acquire()
        try:
            yield
        finally:
            self.release()

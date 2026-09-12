"""基于 asyncio 信号量的并发舱（bulkhead）。
----
`Bulkhead` 把对下游依赖的并发调用数限制在 `max_concurrent` 以内；
当并发数已满时按 `max_wait` 决定是立即失败（`BulkheadFull`）还是
等待一个 permit。

`guard()` 异步上下文管理器是首选用法：进入时 acquire，退出时 release
（即使被调用方抛出异常）。`acquire()` / `release()` 适合需要手工
控制生命周期的场景。

时间源 `Clock` 与 `Sleep` 可注入，方便在不触碰 wall clock 的前提下
做单测。

English
--------
Concurrency-capping bulkhead backed by an asyncio semaphore.

`Bulkhead` caps in-flight calls to a downstream dependency at
`max_concurrent`. When the cap is reached, callers either fail fast
(`BulkheadFull`) or wait up to `max_wait` for a permit.

The `guard()` async context manager is the preferred entry point —
acquires on enter, releases on exit (even when the wrapped body
raises). `acquire()` / `release()` are exposed for callers that need
manual lifetime control.

Time is injected via `Clock` and `Sleep` so unit tests can reason
about contention without touching wall time."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from .clock import Clock, Sleep, SystemClock, system_sleep
from ..errors import BulkheadFull


@dataclass(frozen=True, slots=True)
class BulkheadConfig:
    """中文
    ----
    `Bulkhead` 的配置。

    - `max_concurrent`：在途（in-flight）调用的硬上限。
    - `max_wait`：调用方阻塞等待 permit 的最长时间；`0.0`（默认）
      表示"立即失败"。

    English
    --------
    Configuration for `Bulkhead`.

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
    """中文
    ----
    基于 asyncio 信号量的并发上限器。

    配合 `guard()` 异步上下文管理器使用，可在被保护代码块异常退出时
    自动归还 permit。

    English
    --------
    Async semaphore-based concurrency cap.
    """

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
        """中文
        ----
        阻塞直到 permit 可用，或按 `max_wait` 立即失败。

        - `max_wait == 0.0`：在容量已满时直接抛 `BulkheadFull`。
        - `max_wait > 0.0`：在等待超时后抛 `BulkheadFull`。

        Raises:
            BulkheadFull: 容量已满且等待时间耗尽。

        English
        --------
        Block until a permit is available, or fail fast per `max_wait`.

        Raises:
            BulkheadFull: capacity reached and the wait budget elapsed.
        """
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
        """中文
        ----
        释放先前 `acquire()` 获得的 permit。

        注意：`release` 调用次数超过 `acquire` 是编程错误，
        `asyncio.Semaphore` 在该情况下会抛 `ValueError`。

        English
        --------
        Release a previously acquired permit.

        Calling `release` more times than `acquire` is a programming error;
        `asyncio.Semaphore` will raise `ValueError` in that case.
        """
        self._semaphore.release()
        self._in_flight = max(0, self._in_flight - 1)

    @asynccontextmanager
    async def guard(self) -> AsyncIterator[None]:
        """中文
        ----
        异步上下文管理器：进入时 acquire，退出时 release。

        即便被保护代码块抛异常，`finally` 也会归还 permit。

        English
        --------
        Context manager that acquires a permit on enter and releases on exit.
        """
        await self.acquire()
        try:
            yield
        finally:
            self.release()

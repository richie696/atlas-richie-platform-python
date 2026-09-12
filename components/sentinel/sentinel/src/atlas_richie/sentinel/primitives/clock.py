"""注入式时间源,贯穿所有 Sentinel 原语。
----
所有 Sentinel 原语都接收可注入的 `Clock` / `Sleep`,
这样单元测试可以在不触碰 wall clock 的情况下推理时长、退避和
过期逻辑。生产代码使用 `SystemClock` / `system_sleep`,
测试代码使用 `ManualClock` 替换。

设计要点:

- **Clock**:单调不减的时间源;`ManualClock` 只在 `advance()` 时前进。
- **Sleep**:`Callable[[float], Awaitable[None]]`,工厂函数 `system_sleep`
  返回绑定到 `asyncio.sleep` 的实例,便于 `field(default_factory=...)`
  干净地嵌入 dataclass。

`RandomSource` 已拆到 `atlas_richie.sentinel.primitives.random_source`。
历史:RandomSource/SystemRandom/DeterministicRandom 在
`atlas_richie.resilience.clock` 是单文件;M0.5 按目标结构拆出。

English
--------
Injectable time source used by every Sentinel primitive.

`Clock` / `Sleep` are injected so unit tests can reason about durations,
backoff, and expiration without touching the wall clock. Production code
uses `SystemClock` / `system_sleep`; tests substitute `ManualClock` to
keep scenarios deterministic.

`RandomSource` was split out into
`atlas_richie.sentinel.primitives.random_source` as part of the M0.5
migration to the Sentinel target structure."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Protocol


class Clock(Protocol):
    """中文
    ----
    单调时间源。实现必须保证返回值永不倒退。

    English
    --------
    A monotonic time source. Implementations must never go backwards.
    """

    def now(self) -> float:
        """中文
        ----
        返回单调不减的时间戳(秒)。

        English
        --------
        Return a monotonically non-decreasing timestamp in seconds.
        """


class SystemClock:
    """中文
    ----
    默认 `Clock` 实现,底层使用 `time.monotonic`。

    English
    --------
    The default `Clock`; backed by `time.monotonic`.
    """

    def now(self) -> float:
        return time.monotonic()


class ManualClock:
    """中文
    ----
    由测试驱动前进的 `Clock`。只有 `advance()` 被调用时,时间值才会
    变化,因此单元测试可以推理时长而不触碰 wall clock。

    English
    --------
    A `Clock` whose value is advanced by the test harness.

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
"""中文
----
可等待的 `sleep`。`system_sleep` 是默认工厂,测试可注入替身。

English
--------
An awaitable sleep. `system_sleep` is the default factory; tests may
replace it."""


def system_sleep() -> Sleep:
    """中文
    ----
    返回绑定到 `asyncio.sleep` 的默认 `Sleep` callable。

    选择工厂函数(而不是直接暴露函数)的原因:dataclass 字段可使用
    `field(default_factory=system_sleep)`,每个实例获得独立的 `Sleep`
    引用,原语按需传入延迟。

    English
    --------
    Return the default `Sleep` callable, bound to `asyncio.sleep`.

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

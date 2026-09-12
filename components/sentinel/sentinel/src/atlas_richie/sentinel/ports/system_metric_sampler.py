"""Sentinel SystemMetricSampler(M2.4 Port)。

中文
----
``SystemMetricSampler`` 是 SystemSlot 用来采集系统指标的 Port;主包
**不**安装 psutil,默认提供 ``DefaultSystemMetricSampler``,只用
stdlib (asyncio + time + os) 采集。

设计要点:

- **Protocol + 注入**:主包用 Protocol,具体实现可由 Adapter wheel
  (sentinel-adapter-asgi 等) 注入,生产可用 psutil
- **失败 fail-safe** (``degraded=True``):sampler 抛错时 SystemSlot
  记录 ``Engine.last_error`` + 跳过本规则的阈值检查,**不**触发
  SystemBlocked(避免 sampler bug 把整服务 503)
- **5 个指标**:CPU / load / event_loop_lag_ms / in_flight_qps /
  completed_qps(ADAPTIVE_CAPACITY 用)

English
--------
Sentinel SystemMetricSampler (M2.4 Port).

``SystemMetricSampler`` is the Port SystemSlot uses to collect system
metrics; the main wheel does **not** install psutil; default impl
``DefaultSystemMetricSampler`` uses stdlib only (asyncio + time + os).

Design points:

- **Protocol + inject** — main wheel uses Protocol; concrete
  implementations (e.g. psutil-backed) can be injected by Adapter
  wheels.
- **Failure fail-safe** (``degraded=True``): when sampler raises,
  SystemSlot records ``Engine.last_error`` + skips this rule's
  threshold checks; **does not** trigger SystemBlocked (avoid
  sampler bugs causing service-wide 503).
- **5 metrics**: CPU / load / event_loop_lag_ms / in_flight_qps /
  completed_qps (ADAPTIVE_CAPACITY uses)."""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from ..primitives.clock import Clock, SystemClock


@dataclass(frozen=True, slots=True)
class SystemSnapshot:
    """中文
    ----
    一次采样的不可变视图。

    任何指标 sampler 失败 → 该字段为 ``None``(degraded = True);
    其它字段照常。

    English
    --------
    Immutable view of one sampling.

    Any metric sampler failure → that field is ``None`` (degraded =
    True); other fields are populated as usual.
    """

    cpu_usage: float | None
    load: float | None
    event_loop_lag_ms: float | None
    in_flight_qps: float | None
    completed_qps: float | None
    at_ns: int
    degraded: bool = False


@runtime_checkable
class SystemMetricSampler(Protocol):
    """中文
    ----
    系统指标采样器 Port。

    实现要求:

    - ``sample()`` 同步或协程,返回不可变 ``SystemSnapshot``
    - 任何指标采集失败时**不**抛,**标记**对应字段 ``None`` +
      ``degraded=True``(由实现决定哪些指标失败)
    - 同步 / 异步都行;M2.4 Slot 调 ``await sampler.sample()`` 或
      ``sampler.sample()``(M2.4 选 await)

    English
    --------
    System metric sampler Port.

    Implementation requirements:

    - ``sample()`` sync or coroutine; returns immutable
      ``SystemSnapshot``.
    - **Does not raise** on any metric failure; marks failed fields
      ``None`` + ``degraded=True``.
    - Sync or async; M2.4 Slot calls ``await sampler.sample()`` (or
      direct sync call when not a coroutine).
    """

    def sample(self) -> "SystemSnapshot | Awaitable[SystemSnapshot]":
        ...


@dataclass(slots=True)
class DefaultSystemMetricSampler:
    """中文
    ----
    默认 stdlib sampler(无 psutil)。

    - ``clock`` — 可注入 Clock(测试用 ManualClock)
    - ``_in_flight`` / ``_completed`` — 由 Engine 维护(进入 +1,
      完成 -1;成功 +1 completed_qps)

    English
    --------
    Default stdlib sampler (no psutil).

    - ``clock`` — injectable Clock (ManualClock for tests).
    - ``_in_flight`` / ``_completed`` — Engine-maintained counters.
    """

    clock: Clock = field(default_factory=SystemClock)
    _in_flight: int = 0
    _completed_in_window: int = 0
    _window_start_ns: int = 0

    def record_enter(self) -> None:
        """中文
        ----
        Engine 在 entry 入口调用。

        English
        --------
        Called by Engine on entry start.
        """
        self._in_flight += 1

    def record_complete(self, *, success: bool) -> None:
        """中文
        ----
        Engine 在 entry 完成时调用。

        English
        --------
        Called by Engine on entry completion.
        """
        self._in_flight = max(0, self._in_flight - 1)
        if success:
            self._completed_in_window += 1

    def sample(self) -> SystemSnapshot:
        """中文
        ----
        同步采样(主路径,无需 await)。

        English
        --------
        Synchronous sample (no await needed for main path).
        """
        now_ns = time.time_ns()
        # 1s 滚动窗口:completed_qps = window_count
        if self._window_start_ns == 0:
            self._window_start_ns = now_ns
        window_elapsed_ns = now_ns - self._window_start_ns
        completed_qps: float | None = None
        if window_elapsed_ns > 0:
            completed_qps = self._completed_in_window * 1_000_000_000 / window_elapsed_ns
            if window_elapsed_ns > 1_000_000_000:  # 1s 滚动
                self._window_start_ns = now_ns
                self._completed_in_window = 0
        # CPU / load: 跨平台,简化(用 os.getloadavg 如果有,否则 None)
        cpu_usage: float | None = None
        load: float | None = None
        try:
            load = os.getloadavg()[0]
        except (OSError, AttributeError):
            load = None
        # CPU usage: 没有 psutil / 简单方法是 None(主包不强制依赖)
        # M3.x Adapter 可注入 psutil 实现
        # event_loop_lag: 主包不实现(需要 asyncio event loop 时间戳)
        # 也是 None;M3.x Adapter 可注入
        return SystemSnapshot(
            cpu_usage=cpu_usage,
            load=load,
            event_loop_lag_ms=None,  # 留给 Adapter
            in_flight_qps=float(self._in_flight),
            completed_qps=completed_qps,
            at_ns=now_ns,
            degraded=(cpu_usage is None and load is None),
        )


__all__ = ["SystemMetricSampler", "SystemSnapshot", "DefaultSystemMetricSampler"]

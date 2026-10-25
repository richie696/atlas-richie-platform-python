"""Sentinel SystemMetricSampler(M2.4 Port)。

中文
----
``SystemMetricSampler`` 是 SystemSlot 用来采集系统指标的 Port;主包
**不**安装 psutil,默认提供 ``DefaultSystemMetricSampler``,只用
stdlib (asyncio + time + os + pathlib) 采集。Linux 上只有检测到有效
cgroup CPU quota 时才计算进程 CPU 占比;未配置 quota 的环境返回 ``None``。

设计要点:

- **Protocol + 注入**:主包用 Protocol,具体实现可由 Adapter wheel
  (sentinel-adapter-asgi 等) 注入,生产可用 psutil
- **失败 fail-safe** (``degraded=True``):sampler 抛错时 SystemSlot
  记录 ``Engine.last_error`` + 跳过本规则的阈值检查,**不**触发
  SystemBlocked(避免 sampler bug 把整服务 503)
- **系统保护指标**:CPU / load / event_loop_lag_ms / in_flight_qps /
  completed_qps(ADAPTIVE_CAPACITY 用)
- **遥测补充**:``memory_bytes`` 是 Linux 进程 RSS;``memory_ratio``
  是该 RSS 与可见 cgroup 有效限额之比;不新增 ``SystemRule`` 可匹配的
  保护指标;不支持或读取失败时为 ``None``

English
--------
Sentinel SystemMetricSampler (M2.4 Port).

``SystemMetricSampler`` is the Port SystemSlot uses to collect system
metrics; the main wheel does **not** install psutil; default impl
``DefaultSystemMetricSampler`` uses stdlib only (asyncio + time + os + pathlib).
On Linux, process CPU ratio is available only when a valid cgroup v1/v2 CPU
quota can be read; a narrower process CPU affinity further limits the
normalization. An unconfigured quota remains unavailable rather than falling
back to host CPU capacity.

Design points:

- **Protocol + inject** — main wheel uses Protocol; concrete
  implementations (e.g. psutil-backed) can be injected by Adapter
  wheels.
- **Failure fail-safe** (``degraded=True``): when sampler raises,
  SystemSlot records ``Engine.last_error`` + skips this rule's
  threshold checks; **does not** trigger SystemBlocked (avoid
  sampler bugs causing service-wide 503).
- **System-protection metrics**: CPU / load / event_loop_lag_ms /
  in_flight_qps / completed_qps (used by ADAPTIVE_CAPACITY).
- **Telemetry addition**: ``memory_bytes`` is Linux process RSS and
  ``memory_ratio`` is that RSS divided by the tightest visible finite cgroup
  memory limit. These do not add a ``SystemRule`` protection selector;
  unsupported or failed reads remain ``None``."""

from __future__ import annotations

import math
import os
import time
from collections.abc import Awaitable
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Protocol, runtime_checkable

from ..primitives.clock import Clock, SystemClock

_NANOSECONDS_PER_SECOND = 1_000_000_000
_PROC_SELF_STATM = Path("/proc/self/statm")
_PROC_SELF_CGROUP = Path("/proc/self/cgroup")
_PROC_SELF_MOUNTINFO = Path("/proc/self/mountinfo")
_CGROUP_V2_CPU_MAX = Path("/sys/fs/cgroup/cpu.max")
_CGROUP_V1_CPU_QUOTA = Path("/sys/fs/cgroup/cpu/cpu.cfs_quota_us")
_CGROUP_V1_CPU_PERIOD = Path("/sys/fs/cgroup/cpu/cpu.cfs_period_us")
_CGROUP_V1_MEMORY_LIMIT_UNLIMITED_THRESHOLD_BYTES = 1 << 60


def _is_finite_nonnegative_measurement(value: object) -> bool:
    """Return whether a sampler measurement is a finite non-negative number."""
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value) and value >= 0
    except OverflowError:
        return False


def _parse_cpu_quota(quota: str, period: str) -> float | None:
    """Return a positive CPU quota in cores; unlimited or invalid is unknown."""
    try:
        quota_value = int(quota)
        period_value = int(period)
    except ValueError:
        return None
    if quota_value <= 0 or period_value <= 0:
        return None
    return quota_value / period_value


def _read_effective_cpu_capacity() -> float | None:
    """Read the process CPU capacity without substituting host capacity."""
    try:
        v2_parts = _CGROUP_V2_CPU_MAX.read_text(encoding="ascii").split()
    except OSError:
        v2_parts = []
    if len(v2_parts) == 2 and v2_parts[0] != "max":
        quota_cores = _parse_cpu_quota(v2_parts[0], v2_parts[1])
    else:
        try:
            quota = _CGROUP_V1_CPU_QUOTA.read_text(encoding="ascii").strip()
            period = _CGROUP_V1_CPU_PERIOD.read_text(encoding="ascii").strip()
        except OSError:
            return None
        quota_cores = _parse_cpu_quota(quota, period)
    if quota_cores is None:
        return None

    try:
        affinity_cores = len(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        return quota_cores
    if affinity_cores <= 0:
        return None
    return min(quota_cores, float(affinity_cores))


def _read_process_rss_bytes() -> int | None:
    """Read Linux process resident memory; unsupported platforms stay unknown."""
    try:
        resident_pages = int(_PROC_SELF_STATM.read_text(encoding="ascii").split()[1])
        page_size = int(os.sysconf("SC_PAGE_SIZE"))
    except (IndexError, OSError, UnicodeError, ValueError):
        return None
    if resident_pages < 0 or page_size <= 0:
        return None
    return resident_pages * page_size


def _decode_mountinfo_path(value: str) -> str:
    """Decode the octal escapes used for paths in procfs mountinfo."""
    return (
        value.replace("\\040", " ")
        .replace("\\011", "\t")
        .replace("\\012", "\n")
        .replace("\\134", "\\")
    )


def _cgroup_directory(controller: str) -> tuple[Path, Path] | None:
    """Resolve the current cgroup directory and its visible mount root."""
    try:
        cgroup_lines = _PROC_SELF_CGROUP.read_text(encoding="ascii").splitlines()
        mount_lines = _PROC_SELF_MOUNTINFO.read_text(encoding="ascii").splitlines()
    except (OSError, UnicodeError):
        return None

    cgroup_path: PurePosixPath | None = None
    for line in cgroup_lines:
        parts = line.split(":", 2)
        if len(parts) != 3:
            continue
        controllers, path = parts[1], parts[2]
        if (controller == "cgroup2" and not controllers) or (
            controller != "cgroup2" and controller in controllers.split(",")
        ):
            if not path.startswith("/"):
                return None
            cgroup_path = PurePosixPath(path)
            break
    if cgroup_path is None:
        return None

    for line in mount_lines:
        before, separator, after = line.partition(" - ")
        if not separator:
            continue
        mount_fields = before.split()
        filesystem_fields = after.split()
        if len(mount_fields) < 5 or not filesystem_fields:
            continue
        filesystem = filesystem_fields[0]
        expected_filesystem = "cgroup2" if controller == "cgroup2" else "cgroup"
        if filesystem != expected_filesystem:
            continue
        if controller != "cgroup2":
            mount_options = (
                set(filesystem_fields[2].split(","))
                if len(filesystem_fields) > 2
                else set()
            )
            if controller not in mount_options:
                continue
        mount_root = PurePosixPath(_decode_mountinfo_path(mount_fields[3]))
        mount_point = Path(_decode_mountinfo_path(mount_fields[4]))
        try:
            relative_path = cgroup_path.relative_to(mount_root)
        except ValueError:
            continue
        return mount_point / Path(*relative_path.parts), mount_point
    return None


def _read_effective_memory_limit_bytes() -> int | None:
    """Read the tightest visible finite cgroup memory limit for this process."""
    cgroup = _cgroup_directory("cgroup2")
    limit_name = "memory.max"
    if cgroup is None:
        cgroup = _cgroup_directory("memory")
        limit_name = "memory.limit_in_bytes"
    if cgroup is None:
        return None

    current, mount_point = cgroup
    limits: list[int] = []
    directory = current
    while True:
        try:
            raw_limit = (directory / limit_name).read_text(encoding="ascii").strip()
        except (OSError, UnicodeError):
            return None
        if raw_limit != "max":
            try:
                limit = int(raw_limit)
            except ValueError:
                return None
            is_v1_unlimited = (
                limit_name == "memory.limit_in_bytes"
                and limit >= _CGROUP_V1_MEMORY_LIMIT_UNLIMITED_THRESHOLD_BYTES
            )
            if limit > 0 and not is_v1_unlimited:
                limits.append(limit)
        if directory == mount_point:
            break
        parent = directory.parent
        if parent == directory:
            return None
        directory = parent
    return min(limits) if limits else None


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
    memory_bytes: int | None = None
    memory_ratio: float | None = None

    def __post_init__(self) -> None:
        if type(self.at_ns) is not int or self.at_ns < 0:
            raise ValueError("at_ns must be a non-negative integer")
        if type(self.degraded) is not bool:
            raise TypeError("degraded must be a boolean")
        for name in (
            "cpu_usage",
            "load",
            "event_loop_lag_ms",
            "in_flight_qps",
            "completed_qps",
            "memory_ratio",
        ):
            value = getattr(self, name)
            if value is not None and not _is_finite_nonnegative_measurement(value):
                raise ValueError(f"{name} must be finite and non-negative when present")
        if self.cpu_usage is not None and self.cpu_usage > 1:
            raise ValueError("cpu_usage must not exceed 1")
        if self.memory_bytes is not None and (
            type(self.memory_bytes) is not int or self.memory_bytes < 0
        ):
            raise ValueError("memory_bytes must be a non-negative integer when present")


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

    def sample(self) -> SystemSnapshot | Awaitable[SystemSnapshot]: ...


@runtime_checkable
class SystemMetricLifecycle(Protocol):
    """Optional entry-accounting capability for process metric samplers.

    Samplers that expose ``in_flight_qps`` or ``completed_qps`` can implement
    this small lifecycle port. A sampler concerned only with host metrics
    still needs to implement only :class:`SystemMetricSampler`.
    """

    def record_enter(self) -> None: ...

    def record_complete(self, *, success: bool) -> None: ...


@dataclass(slots=True)
class DefaultSystemMetricSampler:
    """中文
    ----
    默认 stdlib sampler(无 psutil)。

    - ``clock`` — 可注入 Clock(测试用 ManualClock)
    - ``_in_flight`` / ``_completed`` — 由 Engine 维护(进入 +1,
      完成 -1;成功 +1 completed_qps)
    - ``cpu_usage`` — 进程 CPU 时间增量 / min(cgroup quota, CPU affinity);无
      quota、首次采样或不支持的平台返回 ``None``

    English
    --------
    Default stdlib sampler (no psutil).

    - ``clock`` — injectable Clock (ManualClock for tests).
    - ``_in_flight`` / ``_completed`` — Engine-maintained counters.
    - ``cpu_usage`` — process CPU-time delta divided by the lower of the
      cgroup CPU quota and process CPU affinity; unavailable on the first
      sample, without a quota, or on unsupported platforms.
    - ``memory_bytes`` — Linux process RSS from ``/proc/self/statm``;
      unavailable on unsupported platforms or when procfs cannot be read.
    - ``memory_ratio`` — process RSS divided by the tightest visible finite
      cgroup memory limit; unavailable when either side is unknown.
    """

    clock: Clock = field(default_factory=SystemClock)
    _in_flight: int = 0
    _completed_in_window: int = 0
    _window_start_s: float | None = None
    _last_cpu_observation: tuple[float, int] | None = field(
        default=None, init=False, repr=False
    )

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
        now_s = self.clock.now()
        now_ns = time.time_ns()
        process_cpu_ns = time.process_time_ns()
        # 以单调时钟统计完成率,墙钟只用于快照时间戳。
        if self._window_start_s is None:
            self._window_start_s = now_s
        window_elapsed_s = now_s - self._window_start_s
        completed_qps: float | None = None
        if window_elapsed_s > 0:
            completed_qps = self._completed_in_window / window_elapsed_s
            if window_elapsed_s > 1.0:  # 1s 采样窗口
                self._window_start_s = now_s
                self._completed_in_window = 0
        # Process CPU is meaningful as a ratio only when the effective
        # process capacity is known. Do not normalize a container process by
        # the host's CPU count: that would under-report throttled workloads.
        cpu_usage = self._sample_cpu_usage(now_s, process_cpu_ns)
        memory_bytes = _read_process_rss_bytes()
        memory_limit_bytes = _read_effective_memory_limit_bytes()
        memory_ratio = (
            memory_bytes / memory_limit_bytes
            if memory_bytes is not None and memory_limit_bytes is not None
            else None
        )
        load: float | None = None
        try:
            load = os.getloadavg()[0]
        except (OSError, AttributeError):
            load = None
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
            memory_bytes=memory_bytes,
            memory_ratio=memory_ratio,
        )

    def _sample_cpu_usage(self, now_s: float, process_cpu_ns: int) -> float | None:
        previous = self._last_cpu_observation
        self._last_cpu_observation = (now_s, process_cpu_ns)
        effective_cpu_cores = _read_effective_cpu_capacity()
        if effective_cpu_cores is None or previous is None:
            return None

        previous_time_s, previous_cpu_ns = previous
        elapsed_s = now_s - previous_time_s
        consumed_cpu_ns = process_cpu_ns - previous_cpu_ns
        if elapsed_s <= 0 or consumed_cpu_ns < 0:
            return None

        usage = (
            consumed_cpu_ns / _NANOSECONDS_PER_SECOND / elapsed_s / effective_cpu_cores
        )
        return min(usage, 1.0)


__all__ = [
    "DefaultSystemMetricSampler",
    "SystemMetricLifecycle",
    "SystemMetricSampler",
    "SystemSnapshot",
]

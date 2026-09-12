"""Sentinel 环形 SlidingWindow(M1.4)。

中文
----
``SlidingWindow`` 是 FlowRule / CircuitBreaker 等规则的统计基础:把
时间轴切成 ``bucket_count`` 个等长桶,每个桶保存该时段内的 passed /
blocked 计数,提供 O(1) 的窗口内累加和。

设计要点:

- **stdlib ring buffer**:用 ``collections.deque`` + 索引实现,无
  ``sortedcontainers`` 等 3rd-party 依赖
- **桶索引 = (now // bucket_ms) % bucket_count**:用 ``Clock``(可注入)
  而不是 ``time.monotonic()``,保证测试可复现
- **过期桶原地重置**:`advance(now_ms)` 把所有"now_ms 之前"的桶视为过期,
  并把过期数据清零(避免旧数据被错误地"穿越时间"算入新窗口)
- **线程安全**:**不**内置锁;Engine 在单 event loop 单线程下用足够
  (锁由 Engine 自身的 asyncio.Lock 提供,见 M1.2)

English
--------
Sentinel ring SlidingWindow (M1.4).

``SlidingWindow`` is the statistics base for FlowRule / CircuitBreaker
etc. — split the timeline into ``bucket_count`` equal-length buckets,
each holding the passed / blocked count for that slot, and provide
O(1) sum over the window.

Design points:

- **stdlib ring buffer** — ``collections.deque`` + index, no
  ``sortedcontainers`` or other 3rd-party deps.
- **Bucket index = (now // bucket_ms) % bucket_count** — uses
  ``Clock`` (injectable) instead of ``time.monotonic()`` for
  test-determinism.
- **Stale-bucket reset** — ``advance(now_ms)`` treats all buckets
  older than ``now_ms`` as expired and zeroes their counts (prevents
  stale data from "travelling in time" into a new window).
- **Thread safety** — no built-in lock; Engine single-loop single-
  thread usage is sufficient (lock is provided by Engine's
  ``asyncio.Lock``, see M1.2)."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from ..primitives.clock import Clock, SystemClock

# Default bucket size (ms) and count; can be overridden at construction
_DEFAULT_BUCKET_MS = 500
_DEFAULT_BUCKET_COUNT = 10  # → 5 second window


@dataclass(slots=True)
class _Bucket:
    """中文
    ----
    单个时间桶:passed / blocked 计数,以及该桶对应的 epoch_ms。

    用 ``slots=True`` dataclass 避免 dict 开销;每个 ``SlidingWindow``
    实例化时分配 ``bucket_count`` 个。

    English
    --------
    One time bucket: passed / blocked counters plus the bucket's
    epoch_ms. Uses ``slots=True`` to avoid dict overhead; each
    ``SlidingWindow`` allocates ``bucket_count`` of these."""

    epoch_ms: int
    passed: int = 0
    blocked: int = 0

    def reset(self, epoch_ms: int) -> None:
        """中文
        ----
        重置桶(过期桶重置,passed / blocked 归 0)。

        English
        --------
        Reset the bucket (zero counters; used when bucket ages out).
        """
        self.epoch_ms = epoch_ms
        self.passed = 0
        self.blocked = 0


class SlidingWindow:
    """中文
    ----
    环形 SlidingWindow。

    构造参数:

    - ``clock`` — 可注入 ``Clock``(默认 ``SystemClock``);测试用
      ``ManualClock`` 替换以实现 deterministic
    - ``bucket_ms`` — 每桶时长(毫秒;默认 500)
    - ``bucket_count`` — 桶数(默认 10,共 5 秒窗口)

    公开方法:

    - ``record_pass(now_ms)`` — 记录一次通过
    - ``record_block(now_ms)`` — 记录一次拒绝
    - ``sum(now_ms)`` — 返回当前窗口内 (passed, blocked) tuple
    - ``reset(now_ms)`` — 重置全部桶(主要给测试用)

    English
    --------
    Ring SlidingWindow.

    Constructor args:

    - ``clock`` — injectable ``Clock`` (default ``SystemClock``);
      tests use ``ManualClock`` for determinism.
    - ``bucket_ms`` — bucket length in ms (default 500).
    - ``bucket_count`` — number of buckets (default 10, 5 s window).

    Public methods:

    - ``record_pass(now_ms)`` — record a pass.
    - ``record_block(now_ms)`` — record a block.
    - ``sum(now_ms)`` — return (passed, blocked) tuple for the window.
    - ``reset(now_ms)`` — reset all buckets (mainly for tests).
    """

    __slots__ = (
        "clock",
        "bucket_ms",
        "bucket_count",
        "_buckets",
        "_last_seen_ms",
    )

    def __init__(
        self,
        *,
        clock: Clock | None = None,
        bucket_ms: int = _DEFAULT_BUCKET_MS,
        bucket_count: int = _DEFAULT_BUCKET_COUNT,
    ) -> None:
        if bucket_ms <= 0:
            raise ValueError(f"bucket_ms must be positive (got {bucket_ms})")
        if bucket_count <= 0:
            raise ValueError(f"bucket_count must be positive (got {bucket_count})")
        self.clock: Clock = clock or SystemClock()
        self.bucket_ms = bucket_ms
        self.bucket_count = bucket_count
        # deque of _Bucket; pre-fill with epoch=0 so first advance
        # doesn't need special-case logic
        self._buckets: deque[_Bucket] = deque(
            _Bucket(epoch_ms=0) for _ in range(bucket_count)
        )
        self._last_seen_ms: int = 0

    def _bucket_index(self, epoch_ms: int) -> int:
        return (epoch_ms // self.bucket_ms) % self.bucket_count

    def _bucket_for(self, now_ms: int) -> _Bucket:
        idx = self._bucket_index(now_ms)
        bucket = self._buckets[idx]
        # If the bucket's epoch is stale, reset it to current epoch
        if bucket.epoch_ms != (now_ms // self.bucket_ms):
            bucket.reset(now_ms // self.bucket_ms)
        return bucket

    def _evict_stale(self, now_ms: int) -> None:
        """中文
        ----
        标记当前 epoch 之前的所有桶为"过期"并清零(下次访问时会被
        ``_bucket_for`` 重置)。

        English
        --------
        Mark all buckets whose epoch is older than the current one as
        "stale" by zeroing them (next access resets via ``_bucket_for``).
        """
        # No-op: the lazy reset in _bucket_for handles eviction.
        # We only need to track _last_seen_ms for diagnostics.
        if now_ms > self._last_seen_ms:
            self._last_seen_ms = now_ms

    def _now_ms(self) -> int:
        """中文
        ----
        从注入的 ``Clock`` 取当前时间(秒 → 毫秒)。

        English
        --------
        Read current time from injected ``Clock`` (seconds → ms).
        """
        return int(self.clock.now() * 1000)

    def record_pass(self, now_ms: int | None = None) -> None:
        """中文
        ----
        记录一次通过;``now_ms`` 为 ``None`` 时从 ``clock`` 读取。

        English
        --------
        Record a pass; ``now_ms=None`` reads from ``clock``.
        """
        if now_ms is None:
            now_ms = self._now_ms()
        self._evict_stale(now_ms)
        self._bucket_for(now_ms).passed += 1

    def record_block(self, now_ms: int | None = None) -> None:
        """中文
        ----
        记录一次拒绝。

        English
        --------
        Record a block.
        """
        if now_ms is None:
            now_ms = self._now_ms()
        self._evict_stale(now_ms)
        self._bucket_for(now_ms).blocked += 1

    def sum(self, now_ms: int | None = None) -> tuple[int, int]:
        """中文
        ----
        返回当前窗口内 (passed, blocked) tuple。

        关键:**先** ``_evict_stale`` 再求和,确保过期的桶已经清零。

        English
        --------
        Return (passed, blocked) for the current window.

        Crucial: ``_evict_stale`` is called first so stale buckets are
        reset to zero before summation.
        """
        if now_ms is None:
            now_ms = self._now_ms()
        self._evict_stale(now_ms)
        # Force a touch on every bucket in the window so stale ones reset
        window_start_ms = now_ms - self.bucket_ms * self.bucket_count
        current_epoch = now_ms // self.bucket_ms
        total_passed = 0
        total_blocked = 0
        for offset in range(self.bucket_count):
            epoch = current_epoch - offset
            idx = epoch % self.bucket_count
            bucket = self._buckets[idx]
            if bucket.epoch_ms == epoch and bucket.epoch_ms * self.bucket_ms >= window_start_ms:
                total_passed += bucket.passed
                total_blocked += bucket.blocked
        return total_passed, total_blocked

    def reset(self, now_ms: int | None = None) -> None:
        """中文
        ----
        重置全部桶(主要给测试 / 故障恢复用)。

        English
        --------
        Reset all buckets (mainly for tests / failure recovery).
        """
        if now_ms is None:
            now_ms = self._now_ms()
        epoch = now_ms // self.bucket_ms
        for bucket in self._buckets:
            bucket.reset(epoch)
        self._last_seen_ms = now_ms


__all__ = ["SlidingWindow", "_DEFAULT_BUCKET_MS", "_DEFAULT_BUCKET_COUNT"]

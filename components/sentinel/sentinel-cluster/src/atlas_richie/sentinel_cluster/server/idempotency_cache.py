"""Atlas Richie Sentinel Cluster — Idempotency Cache (M6.3.3).

中文
----
``request_id`` 短期 cache, 5 min TTL (协议 §5.1), 防止 Client 重试时
双扣 (at-least-once 投递 + 强幂等)。

**key 设计**: ``(request_id, instance_id, startup_epoch)`` — 三元组
保证**跨 owner 不会误命中** (不同 instance_id 即使 request_id 撞了
也 miss)。

**TTL 选择** (协议 §5.2): 5 min < lease TTL 推荐 (避免旧 release 请求
错误命中 stale cache)。1.0 lease TTL 默认 30 s, 5 min 远大于 lease TTL,
但 release 命中 idempotency cache 时 lease 早已过期, 响应是**已知**的
DENIED/LEASE_NOT_FOUND, 不会造成业务影响。

**过期清理**: 后台 task 周期扫 (复用 ``LeaseStore.scrub_expired`` 模式,
在 ``TokenServer`` 启动期调度); 也支持在 ``get_or_set`` 路径上
lazy clean (单次调用 max 1 entry)。

**线程模型**: 跟 ``LeaseStore`` 一致 — 单 asyncio event loop +
``asyncio.Lock`` 保护 (Server 设计为单进程, M6.7 决策)。

English
--------
``request_id`` short-term cache, 5 min TTL (protocol §5.1), preventing
double-spend on Client retries (at-least-once delivery + strong idempotency).

Key design: ``(request_id, instance_id, startup_epoch)`` — the triple
guarantees **no cross-owner false hit** (different ``instance_id`` even
with colliding ``request_id`` results in miss).

TTL rationale (protocol §5.2): 5 min < lease TTL is recommended (to
avoid stale release requests wrongly hitting the cache). 1.0 lease TTL
defaults to 30 s; 5 min >> lease TTL, but a release hitting the idempotency
cache after the lease has expired yields the **known**
DENIED / LEASE_NOT_FOUND response, with no business impact.

Expiry cleanup: background task periodic scan (mirroring
``LeaseStore.scrub_expired``, scheduled in ``TokenServer`` start-up);
also supports lazy cleanup on ``get_or_set`` path (max 1 entry per call).

Threading model: same as ``LeaseStore`` — single asyncio event loop +
``asyncio.Lock`` protection (Server is designed as single-process,
M6.7 decision).
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Callable

from atlas_richie.contracts.cluster.v1 import IDEMPOTENCY_CACHE_TTL_NS


@dataclass(frozen=True, slots=True)
class CacheEntry:
    """Idempotency cache 单条记录 (frozen + slots)."""

    key: tuple[str, str, int]  # (request_id, instance_id, startup_epoch)
    value: dict[str, Any]  # 缓存的 envelope (dict, 跟 ClusterTokenEnvelope.payload 兼容)
    expires_at_ns: int


class IdempotencyCache:
    """``request_id`` 短期 idempotency cache (M6.3.3).

    1.0 接受限制:
    - 进程内, 不跨进程 (1.0 Server 单进程)
    - 5 min TTL 过期后, 同 request_id 视为新请求 (Client 端 retry 必须
      仍带同 request_id 才有 idempotency 意义)
    """

    def __init__(
        self,
        *,
        ttl_ns: int = IDEMPOTENCY_CACHE_TTL_NS,
        clock: Callable[[], int] | None = None,
    ) -> None:
        """初始化 idempotency cache.

        Args:
            ttl_ns: TTL 纳秒 (默认 5 min, 协议 §5.1)
            clock: 时钟函数 (返回 int 纳秒), 用于单测注入
        """
        if not isinstance(ttl_ns, int) or ttl_ns <= 0:
            raise ValueError(f"ttl_ns must be positive int, got {ttl_ns!r}")
        self._ttl_ns = ttl_ns
        self._clock = clock if clock is not None else time.time_ns
        self._lock = asyncio.Lock()
        # key -> CacheEntry
        self._entries: dict[tuple[str, str, int], CacheEntry] = {}

    @property
    def ttl_ns(self) -> int:
        return self._ttl_ns

    @property
    def size(self) -> int:
        """当前 cache 大小 (包含未过期 + 已过期未清理, 单测用)."""
        return len(self._entries)

    async def get(
        self,
        request_id: str,
        instance_id: str,
        startup_epoch: int,
        *,
        now_ns: int | None = None,
    ) -> dict[str, Any] | None:
        """查 cache; 命中且未过期返回响应 dict; 否则返回 None.

        Args:
            request_id: Client 生成的 UUID v4
            instance_id: Owner 进程的 instance_id
            startup_epoch: Owner 进程的 startup_epoch
            now_ns: 注入的"现在"纳秒, None = self._clock()

        Returns:
            命中 → 缓存的响应 dict (envelope-shaped); miss / 过期 → None
        """
        if now_ns is None:
            now_ns = self._clock()
        key = (request_id, instance_id, startup_epoch)
        async with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            if entry.expires_at_ns <= now_ns:
                # lazy clean
                self._entries.pop(key, None)
                return None
            return entry.value

    async def put(
        self,
        request_id: str,
        instance_id: str,
        startup_epoch: int,
        value: dict[str, Any],
        *,
        now_ns: int | None = None,
        ttl_ns: int | None = None,
    ) -> CacheEntry:
        """写 cache; 覆盖旧 entry; 返回写入的 entry.

        Args:
            request_id: Client 生成的 UUID v4
            instance_id: Owner 进程的 instance_id
            startup_epoch: Owner 进程的 startup_epoch
            value: 缓存的响应 dict (envelope-shaped)
            now_ns: 注入的"现在"纳秒
            ttl_ns: 覆盖默认 TTL (单测用)

        Returns:
            写入的 CacheEntry
        """
        if now_ns is None:
            now_ns = self._clock()
        effective_ttl = ttl_ns if ttl_ns is not None else self._ttl_ns
        key = (request_id, instance_id, startup_epoch)
        entry = CacheEntry(
            key=key,
            value=value,
            expires_at_ns=now_ns + effective_ttl,
        )
        async with self._lock:
            self._entries[key] = entry
        return entry

    async def get_or_set(
        self,
        request_id: str,
        instance_id: str,
        startup_epoch: int,
        factory: Callable[[], dict[str, Any]],
        *,
        now_ns: int | None = None,
    ) -> tuple[dict[str, Any], bool]:
        """查 cache, miss 时调 ``factory()`` 写 cache; 返回 ``(value, hit)``.

        Args:
            factory: 缓存 miss 时调用的工厂函数 (返回 envelope-shaped dict)

        Returns:
            ``(value, hit)`` — ``hit=True`` 表示来自 cache, ``False`` 表示新写入
        """
        if now_ns is None:
            now_ns = self._clock()
        key = (request_id, instance_id, startup_epoch)
        async with self._lock:
            entry = self._entries.get(key)
            if entry is not None and entry.expires_at_ns > now_ns:
                return entry.value, True
            if entry is not None and entry.expires_at_ns <= now_ns:
                # lazy clean
                self._entries.pop(key, None)
        # factory call 在 lock 外执行, 避免 factory 慢阻塞其他写
        value = factory()
        new_entry = CacheEntry(
            key=key,
            value=value,
            expires_at_ns=now_ns + self._ttl_ns,
        )
        async with self._lock:
            # 二次检查: 避免并发 factory 双写
            existing = self._entries.get(key)
            if existing is not None and existing.expires_at_ns > now_ns:
                return existing.value, True
            self._entries[key] = new_entry
        return new_entry.value, False

    async def scrub_expired(self, *, now_ns: int | None = None) -> int:
        """扫描清理已过期 entry; 返回清理数.

        由后台 task 周期调用。
        """
        if now_ns is None:
            now_ns = self._clock()
        cleaned = 0
        async with self._lock:
            expired_keys = [k for k, e in self._entries.items() if e.expires_at_ns <= now_ns]
            for k in expired_keys:
                self._entries.pop(k, None)
                cleaned += 1
        return cleaned

    def _lock_for_testing(self) -> asyncio.Lock:
        """暴露 lock 给单测 (断言并发 / 持有状态); 1.0 公开 API 不导出."""
        return self._lock


__all__ = ["CacheEntry", "IdempotencyCache"]

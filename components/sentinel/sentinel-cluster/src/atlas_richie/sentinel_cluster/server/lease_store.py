"""Atlas Richie Sentinel Cluster — Lease Store (M6.3.3).

中文
----
进程内 lease 状态存储 + 配额状态, 用 ``asyncio.Lock`` 保护 (Server 在
asyncio 进程里, 跟 Engine event loop 一致, M6.7 决策)。

**数据模型**:

- ``dict[resource, ResourceState]``: 资源配额状态 (max_permits / used / leases)
- ``dict[lease_id, Lease]``: Server 生成的 opaque lease 句柄
- ``dict[(lease_id, instance_id, startup_epoch), True]``: epoch 索引 (用于
  ``fencing`` 校验 + O(1) 二次探测)

**为什么是 3 个 dict 而不是 1 个**: lease 跟 epoch 索引**必须**分开, 否则
``(lease_id, instance_id, startup_epoch)`` 不匹配时只能 O(N) 扫表 (1.0
接受限制: 单 resource 上限由 max_permits 决定, 实际不会太大)。

**Lease 默认 TTL**: 30 s (协议 §5.2, ``DEFAULT_LEASE_TTL_NS``)。

**持久化**: 1.0 **不**做。Server 重启期间 active lease 失效 (设计 §8 风险),
1.0 接受, 文档化, M6.3.x future 持久化 (Redis HA 另起 ADR)。

**owner epoch fencing** (设计 §4.3): release / renew 校验
``(lease_id, instance_id, startup_epoch)`` 三元组; 不匹配 → 不在
``epoch_index`` 中查到 → Server 返回 ``STALE_EPOCH``, Client 忽略,
**不**抛。

English
--------
In-process lease state storage + quota state, guarded by ``asyncio.Lock``
(Server runs in an asyncio process, consistent with Engine event loop,
per M6.7 decision).

Data model:

- ``dict[resource, ResourceState]``: resource quota state (max / used / leases)
- ``dict[lease_id, Lease]``: Server-generated opaque lease handle
- ``dict[(lease_id, instance_id, startup_epoch), True]``: epoch index for
  fencing + O(1) secondary probe

Why 3 dicts rather than 1: lease and epoch index **must** be separate;
otherwise ``(lease_id, instance_id, startup_epoch)`` mismatch requires
O(N) scan (1.0 accepts this cap: per-resource max is bounded by
``max_permits``, so the table stays small in practice).

Default Lease TTL: 30 s (protocol §5.2, ``DEFAULT_LEASE_TTL_NS``).

Persistence: 1.0 **does not** persist. Active leases are invalidated on
Server restart (design §8 risk, accepted in 1.0, documented).
M6.3.x future persistence (Redis HA, separate ADR).

Owner epoch fencing (design §4.3): release / renew verify the
``(lease_id, instance_id, startup_epoch)`` triple; mismatch → not found
in ``epoch_index`` → Server returns ``STALE_EPOCH``, Client ignores, no raise.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Iterable

from atlas_richie.contracts.cluster.v1 import DEFAULT_LEASE_TTL_NS

from ..config import ResourceConfig
from ..errors import ClusterLeaseNotFound


@dataclass(frozen=True, slots=True)
class Lease:
    """Server 生成的 opaque lease 句柄 (frozen + slots).

    字段语义:
    - ``lease_id``: UUID v4, Server 端生成 (Client 不可伪造)
    - ``resource``: 资源名
    - ``permits``: 占用的 permit 数 (浮点, 支持分数 permit)
    - ``instance_id``: Owner 进程的 instance_id (UUID)
    - ``startup_epoch``: Owner 进程的 startup_epoch (用于 fencing)
    - ``issued_at_ns``: Server 分配时墙上时间 (纳秒)
    - ``expires_at_ns``: Server 决定的过期时间 (纳秒); 0 = 永不过期
    """

    lease_id: str
    resource: str
    permits: float
    instance_id: str
    startup_epoch: int
    issued_at_ns: int
    expires_at_ns: int

    def is_expired(self, now_ns: int) -> bool:
        """是否过期; ``expires_at_ns == 0`` 表示永不过期."""
        if self.expires_at_ns == 0:
            return False
        return now_ns >= self.expires_at_ns


@dataclass(slots=True)
class _ResourceState:
    """单个 resource 的配额状态 (private)."""

    name: str
    max_permits: float
    used_permits: float = 0.0
    # 资源下活跃 lease (用于 expiry 扫描; lease_store 也保存 lease 自身)
    active_lease_ids: set[str] = field(default_factory=set)

    @property
    def available_permits(self) -> float:
        return self.max_permits - self.used_permits


def epoch_key(lease_id: str, instance_id: str, startup_epoch: int) -> tuple[str, str, int]:
    """生成 epoch_index 键 (public helper, 用于 fencing 校验)."""
    return (lease_id, instance_id, startup_epoch)


class LeaseStore:
    """进程内 lease + 配额 store (M6.3.3).

    线程模型: Server 在单 asyncio event loop 内运行, 用 ``asyncio.Lock``
    串行化所有 mutating 操作。**禁止**在跨线程 / 跨进程共享此 store
    (Server 设计为单进程, M6.7 决策)。
    """

    def __init__(
        self,
        resources: Iterable[ResourceConfig],
        *,
        lease_ttl_ns: int = DEFAULT_LEASE_TTL_NS,
        clock: "callable[[], int] | None" = None,
    ) -> None:
        """初始化 lease store.

        Args:
            resources: 已配置的 ResourceConfig 列表
            lease_ttl_ns: 默认 lease TTL 纳秒
            clock: 时钟函数 (返回 int 纳秒), 用于单测注入
        """
        if not isinstance(lease_ttl_ns, int) or lease_ttl_ns <= 0:
            raise ValueError(f"lease_ttl_ns must be positive int, got {lease_ttl_ns!r}")
        self._lease_ttl_ns = lease_ttl_ns
        self._clock = clock if clock is not None else time.time_ns
        self._lock = asyncio.Lock()
        # resource -> _ResourceState
        self._resources: dict[str, _ResourceState] = {}
        # lease_id -> Lease
        self._leases: dict[str, Lease] = {}
        # (lease_id, instance_id, startup_epoch) -> True, fencing O(1) lookup
        self._epoch_index: dict[tuple[str, str, int], True] = {}
        for rc in resources:
            self._resources[rc.name] = _ResourceState(
                name=rc.name,
                max_permits=rc.max_permits,
                used_permits=rc.initial_permits or 0.0,
            )

    # ------------------------------------------------------------------
    # properties
    # ------------------------------------------------------------------

    @property
    def lease_ttl_ns(self) -> int:
        return self._lease_ttl_ns

    def known_resources(self) -> frozenset[str]:
        """所有已注册 resource name (frozen)."""
        return frozenset(self._resources.keys())

    def active_lease_count(self, resource: str) -> int:
        """指定 resource 的活跃 lease 数 (包含已过期未清理的)."""
        state = self._resources.get(resource)
        if state is None:
            return 0
        return len(state.active_lease_ids)

    def used_permits(self, resource: str) -> float:
        """指定 resource 已用 permit 数."""
        state = self._resources.get(resource)
        if state is None:
            return 0.0
        return state.used_permits

    def max_permits(self, resource: str) -> float:
        """指定 resource 配额上限."""
        state = self._resources.get(resource)
        if state is None:
            return 0.0
        return state.max_permits

    def available_permits(self, resource: str) -> float:
        """指定 resource 剩余 permit 数."""
        state = self._resources.get(resource)
        if state is None:
            return 0.0
        return state.available_permits

    # ------------------------------------------------------------------
    # mutating operations (must be called under self._lock)
    # ------------------------------------------------------------------

    async def acquire(
        self,
        resource: str,
        permits: float,
        instance_id: str,
        startup_epoch: int,
        *,
        now_ns: int | None = None,
    ) -> Lease | None:
        """分配 lease; 配额满返回 None.

        Args:
            resource: 资源名
            permits: 申请 permit 数 (≥ 0)
            instance_id: Owner 进程的 instance_id
            startup_epoch: Owner 进程的 startup_epoch
            now_ns: 注入的"现在"纳秒, None = 用 self._clock()

        Returns:
            成功 → 新 Lease; 配额满或 resource 未配 → None
        """
        if not isinstance(permits, (int, float)) or permits < 0:
            raise ValueError(f"permits must be non-negative, got {permits!r}")
        if now_ns is None:
            now_ns = self._clock()
        async with self._lock:
            state = self._resources.get(resource)
            if state is None:
                return None
            if state.available_permits < permits:
                return None
            lease_id = str(uuid.uuid4())
            lease = Lease(
                lease_id=lease_id,
                resource=resource,
                permits=float(permits),
                instance_id=instance_id,
                startup_epoch=startup_epoch,
                issued_at_ns=now_ns,
                expires_at_ns=now_ns + self._lease_ttl_ns,
            )
            self._leases[lease_id] = lease
            self._epoch_index[epoch_key(lease_id, instance_id, startup_epoch)] = True
            state.used_permits += float(permits)
            state.active_lease_ids.add(lease_id)
            return lease

    async def get(self, lease_id: str) -> Lease | None:
        """按 lease_id 查 lease (O(1), 不删)."""
        async with self._lock:
            return self._leases.get(lease_id)

    async def has_epoch(
        self, lease_id: str, instance_id: str, startup_epoch: int
    ) -> bool:
        """fencing 校验: ``(lease_id, instance_id, startup_epoch)`` 是否在索引中."""
        async with self._lock:
            return epoch_key(lease_id, instance_id, startup_epoch) in self._epoch_index

    async def release(
        self,
        lease_id: str,
        instance_id: str,
        startup_epoch: int,
    ) -> bool:
        """释放 lease; 配额恢复; 重复 release 幂等.

        Returns:
            True = 释放成功; False = 不存在 / fencing 失败 (静默忽略)

        **fencing 语义**: ``(lease_id, instance_id, startup_epoch)`` 不
        匹配 → 返回 False (调用方决定是否发 ``STALE_EPOCH`` 错误码)。
        """
        async with self._lock:
            lease = self._leases.get(lease_id)
            if lease is None:
                return False
            if not self._epoch_index.get(epoch_key(lease_id, instance_id, startup_epoch), False):
                return False
            # 删 lease + epoch index
            self._epoch_index.pop(epoch_key(lease_id, instance_id, startup_epoch), None)
            state = self._resources.get(lease.resource)
            if state is not None:
                state.used_permits = max(0.0, state.used_permits - lease.permits)
                state.active_lease_ids.discard(lease_id)
            del self._leases[lease_id]
            return True

    async def renew(
        self,
        lease_id: str,
        instance_id: str,
        startup_epoch: int,
        extends_for_ns: int,
        *,
        now_ns: int | None = None,
    ) -> Lease | None:
        """续约 lease; 成功 → 延长 ``expires_at_ns``; 已过期 / epoch 不匹配 → None.

        Args:
            lease_id: Server 生成的 lease_id
            instance_id: Owner 进程的 instance_id
            startup_epoch: Owner 进程的 startup_epoch
            extends_for_ns: 续约时长 (相对当前纳秒)
            now_ns: 注入的"现在"纳秒

        Returns:
            成功 → 更新后的 Lease; 失败 (fencing / 已过期 / 不存在) → None
        """
        if not isinstance(extends_for_ns, int) or extends_for_ns <= 0:
            raise ValueError(
                f"extends_for_ns must be positive int, got {extends_for_ns!r}"
            )
        if now_ns is None:
            now_ns = self._clock()
        async with self._lock:
            lease = self._leases.get(lease_id)
            if lease is None:
                return None
            if not self._epoch_index.get(epoch_key(lease_id, instance_id, startup_epoch), False):
                return None
            if lease.is_expired(now_ns):
                # 已过期: 自动清理 + 配额恢复 (fencing 已通过但 lease 已死)
                self._epoch_index.pop(epoch_key(lease_id, instance_id, startup_epoch), None)
                state = self._resources.get(lease.resource)
                if state is not None:
                    state.used_permits = max(0.0, state.used_permits - lease.permits)
                    state.active_lease_ids.discard(lease_id)
                del self._leases[lease_id]
                return None
            # 续约: 重新设置 expires_at_ns = max(原, now + extends_for_ns)
            new_expiry = now_ns + extends_for_ns
            if new_expiry > lease.expires_at_ns:
                new_lease = Lease(
                    lease_id=lease.lease_id,
                    resource=lease.resource,
                    permits=lease.permits,
                    instance_id=lease.instance_id,
                    startup_epoch=lease.startup_epoch,
                    issued_at_ns=lease.issued_at_ns,
                    expires_at_ns=new_expiry,
                )
                self._leases[lease_id] = new_lease
                return new_lease
            return lease

    async def scrub_expired(self, *, now_ns: int | None = None) -> int:
        """扫描并清理已过期 lease; 返回清理数 (per-resource 配额恢复).

        由后台 task 周期调用 (``ClusterTokenConfig.lease_scrub_interval_s``).
        """
        if now_ns is None:
            now_ns = self._clock()
        cleaned = 0
        async with self._lock:
            expired_ids = [
                lid for lid, l in self._leases.items() if l.is_expired(now_ns)
            ]
            for lid in expired_ids:
                lease = self._leases.pop(lid, None)
                if lease is None:
                    continue
                # 同步清 epoch index (任意 instance_id + epoch 都清)
                keys_to_remove = [
                    k for k in self._epoch_index if k[0] == lid
                ]
                for k in keys_to_remove:
                    self._epoch_index.pop(k, None)
                state = self._resources.get(lease.resource)
                if state is not None:
                    state.used_permits = max(0.0, state.used_permits - lease.permits)
                    state.active_lease_ids.discard(lid)
                cleaned += 1
        return cleaned

    # ------------------------------------------------------------------
    # internal helpers
    # ------------------------------------------------------------------

    def _lock_for_testing(self) -> asyncio.Lock:
        """暴露 lock 给单测 (断言并发 / 持有状态); 1.0 公开 API 不导出."""
        return self._lock


__all__ = ["Lease", "LeaseStore", "epoch_key"]

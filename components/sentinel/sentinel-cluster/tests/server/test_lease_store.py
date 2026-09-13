"""LeaseStore 单测 (M6.3.3).

10 个单测覆盖: add / get / remove / expiry scan / 双加 / 双删 /
epoch fencing / 配额恢复 / 未知 resource 拒绝.
"""

from __future__ import annotations

import pytest

from atlas_richie.sentinel_cluster.config import ResourceConfig
from atlas_richie.sentinel_cluster.server.lease_store import LeaseStore, epoch_key

pytestmark = pytest.mark.unit


def _make_store(
    *,
    resources: list[ResourceConfig] | None = None,
    clock=None,
    lease_ttl_ns: int = 30_000_000_000,
) -> LeaseStore:
    return LeaseStore(
        resources=resources or [ResourceConfig(name="/r1", max_permits=5.0)],
        lease_ttl_ns=lease_ttl_ns,
        clock=clock,
    )


class FakeClock:
    """可注入的 fake clock (单测 helper, list[int] 不可用 lambda)."""

    def __init__(self, start_ns: int = 1_000_000_000_000_000_000) -> None:
        self._now_ns = start_ns

    def __call__(self) -> int:
        return self._now_ns

    def advance(self, ns: int) -> None:
        self._now_ns += ns


# ---------------------------------------------------------------------------
# 1. acquire / get (3 个)
# ---------------------------------------------------------------------------


class TestLeaseStoreAdd:
    """add / get / 配额预占."""

    @pytest.mark.asyncio
    async def test_acquire_returns_lease_with_uuid(self) -> None:
        store = _make_store()
        lease = await store.acquire("/r1", 1.0, "instance-A", 0)
        assert lease is not None
        assert lease.lease_id is not None
        # UUID 8-4-4-4-12 = 36 chars
        assert len(lease.lease_id) == 36

    @pytest.mark.asyncio
    async def test_acquire_decreases_available_permits(self) -> None:
        store = _make_store()
        assert store.available_permits("/r1") == 5.0
        await store.acquire("/r1", 2.0, "instance-A", 0)
        assert store.available_permits("/r1") == 3.0
        assert store.used_permits("/r1") == 2.0

    @pytest.mark.asyncio
    async def test_acquire_records_owner(self) -> None:
        store = _make_store()
        lease = await store.acquire("/r1", 1.0, "instance-A", 5)
        assert lease.instance_id == "instance-A"
        assert lease.startup_epoch == 5


# ---------------------------------------------------------------------------
# 2. quota / unknown resource (3 个)
# ---------------------------------------------------------------------------


class TestLeaseStoreQuota:
    """配额满 / 未知 resource 拒绝."""

    @pytest.mark.asyncio
    async def test_acquire_returns_none_when_quota_full(self) -> None:
        store = _make_store()
        await store.acquire("/r1", 5.0, "instance-A", 0)
        result = await store.acquire("/r1", 1.0, "instance-B", 0)
        assert result is None

    @pytest.mark.asyncio
    async def test_acquire_returns_none_for_unknown_resource(self) -> None:
        store = _make_store()
        result = await store.acquire("/unknown", 1.0, "instance-A", 0)
        assert result is None

    @pytest.mark.asyncio
    async def test_acquire_with_zero_permits_allowed(self) -> None:
        # 0 permit 是合法的 (e.g. heartbeat); 不应扣配额
        store = _make_store()
        lease = await store.acquire("/r1", 0.0, "instance-A", 0)
        assert lease is not None
        assert store.used_permits("/r1") == 0.0


# ---------------------------------------------------------------------------
# 3. release / idempotent / unknown (3 个)
# ---------------------------------------------------------------------------


class TestLeaseStoreRelease:
    """release / 配额恢复 / 重复 release 幂等 / 未知 lease_id."""

    @pytest.mark.asyncio
    async def test_release_restores_permits(self) -> None:
        store = _make_store()
        lease = await store.acquire("/r1", 3.0, "instance-A", 0)
        assert store.used_permits("/r1") == 3.0
        ok = await store.release(lease.lease_id, "instance-A", 0)
        assert ok is True
        assert store.used_permits("/r1") == 0.0
        assert store.available_permits("/r1") == 5.0

    @pytest.mark.asyncio
    async def test_release_unknown_lease_returns_false(self) -> None:
        store = _make_store()
        ok = await store.release("non-existent", "instance-A", 0)
        assert ok is False

    @pytest.mark.asyncio
    async def test_double_release_is_idempotent(self) -> None:
        store = _make_store()
        lease = await store.acquire("/r1", 1.0, "instance-A", 0)
        assert await store.release(lease.lease_id, "instance-A", 0) is True
        # 重复 release 第二次返回 False, 不抛
        assert await store.release(lease.lease_id, "instance-A", 0) is False
        assert store.used_permits("/r1") == 0.0


# ---------------------------------------------------------------------------
# 4. owner epoch fencing (3 个)
# ---------------------------------------------------------------------------


class TestLeaseStoreFencing:
    """owner epoch fencing."""

    @pytest.mark.asyncio
    async def test_release_stale_epoch_returns_false(self) -> None:
        store = _make_store()
        lease = await store.acquire("/r1", 1.0, "instance-A", startup_epoch=0)
        # 模拟 owner restart (startup_epoch 变 1); 旧 epoch 释放被拒
        ok = await store.release(lease.lease_id, "instance-A", startup_epoch=1)
        assert ok is False
        # 配额未恢复
        assert store.used_permits("/r1") == 1.0
        # lease 仍在
        assert await store.get(lease.lease_id) is not None

    @pytest.mark.asyncio
    async def test_release_wrong_instance_returns_false(self) -> None:
        store = _make_store()
        lease = await store.acquire("/r1", 1.0, "instance-A", 0)
        # 别的 instance 释放: epoch 索引不命中
        ok = await store.release(lease.lease_id, "instance-B", 0)
        assert ok is False
        assert store.used_permits("/r1") == 1.0

    @pytest.mark.asyncio
    async def test_epoch_key_helper(self) -> None:
        # 公开 helper, 用于 fencing 校验
        k = epoch_key("lease-1", "instance-A", 0)
        assert k == ("lease-1", "instance-A", 0)


# ---------------------------------------------------------------------------
# 5. expiry / 配额恢复 (1 个)
# ---------------------------------------------------------------------------


class TestLeaseStoreExpiry:
    """lease 过期扫描 / 配额恢复."""

    @pytest.mark.asyncio
    async def test_scrub_expired_cleans_and_restores(self) -> None:
        clock = FakeClock()
        store = _make_store(clock=clock, lease_ttl_ns=10_000_000)  # 10 ms TTL
        lease = await store.acquire("/r1", 1.0, "instance-A", 0)
        assert store.used_permits("/r1") == 1.0
        # 不推进时间, lease 未过期
        cleaned = await store.scrub_expired()
        assert cleaned == 0
        assert store.used_permits("/r1") == 1.0
        # 推进时间超过 TTL
        clock.advance(20_000_000)  # +20 ms (超过 10 ms TTL)
        cleaned = await store.scrub_expired()
        assert cleaned == 1
        assert store.used_permits("/r1") == 0.0
        assert await store.get(lease.lease_id) is None

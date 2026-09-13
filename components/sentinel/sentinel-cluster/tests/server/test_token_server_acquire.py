"""TokenServer ACQUIRE 行为单测 (M6.3.3).

6 个单测覆盖:
- 配额满 deny (QUEUE_FULL) + retry_after_ns
- 部分授予 (permits_granted 准确)
- 配额恢复 (release 后能再次 acquire)
- 多 instance 共享配额
- 0 permit acquire (合法)
- idempotency cache 命中 (重复 request_id 返回同响应)
"""

from __future__ import annotations

import uuid

import pytest

from atlas_richie.contracts.cluster.v1 import (
    ClusterDenyReason,
    ClusterMessageKind,
)

from atlas_richie.sentinel.ports.token import ClusterFailurePolicy

from atlas_richie.sentinel_cluster.config import (
    ClusterTokenConfig,
    ClusterTokenMode,
    ResourceConfig,
)
from atlas_richie.sentinel_cluster.server.token_server import TokenServer

pytestmark = pytest.mark.unit


def _cfg(
    *, max_permits: float = 5.0, resources: tuple[ResourceConfig, ...] | None = None
) -> ClusterTokenConfig:
    if resources is None:
        resources = (ResourceConfig(name="/r1", max_permits=max_permits),)
    return ClusterTokenConfig(
        cluster_token_mode=ClusterTokenMode.STANDALONE,
        bind_address="127.0.0.1:0",
        auth_secret="s",
        resources=resources,
        failure_policy_per_resource={
            r.name: ClusterFailurePolicy.FAIL_CLOSED for r in resources
        },
    )


def _acquire_env(
    *,
    resource: str = "/r1",
    permits: float = 1.0,
    instance_id: str = "instance-A",
    startup_epoch: int = 0,
    request_id: str | None = None,
) -> "atlas_richie.contracts.cluster.v1.ClusterTokenEnvelope":
    import time as _t
    from datetime import datetime, timezone
    from atlas_richie.contracts.cluster.v1 import (
        ClusterMessageKind,
        ClusterTokenEnvelope,
        ISO_8601_UTC_MICRO,
        PROTOCOL_VERSION,
    )
    if request_id is None:
        request_id = str(uuid.uuid4())
    iso = datetime.fromtimestamp(_t.time_ns() / 1e9, tz=timezone.utc).strftime(ISO_8601_UTC_MICRO)
    return ClusterTokenEnvelope(
        protocol_version=PROTOCOL_VERSION,
        message_kind=ClusterMessageKind.ACQUIRE_REQUEST,
        request_id=request_id,
        instance_id=instance_id,
        startup_epoch=startup_epoch,
        resource=resource,
        permits=permits,
        deadline_ns=5_000_000,
        client_requested_at=iso,
        server_received_at=iso,
        payload={
            "rule_version_epoch": 1,
            "rule_version_revision": 0,
            "rule_version_checksum": "sha256:" + "a" * 64,
            "priority": 0,
        },
    )


def _release_env(lease_id, *, instance_id="instance-A", startup_epoch=0):
    import time as _t
    from datetime import datetime, timezone
    from atlas_richie.contracts.cluster.v1 import (
        ClusterMessageKind,
        ClusterTokenEnvelope,
        ISO_8601_UTC_MICRO,
        PROTOCOL_VERSION,
    )
    iso = datetime.fromtimestamp(_t.time_ns() / 1e9, tz=timezone.utc).strftime(ISO_8601_UTC_MICRO)
    return ClusterTokenEnvelope(
        protocol_version=PROTOCOL_VERSION,
        message_kind=ClusterMessageKind.RELEASE_REQUEST,
        request_id=str(uuid.uuid4()),
        instance_id=instance_id,
        startup_epoch=startup_epoch,
        resource="/r1",
        permits=1.0,
        deadline_ns=5_000_000,
        client_requested_at=iso,
        server_received_at=iso,
        payload={"lease_id": lease_id, "permits_released": 1.0},
    )


class TestTokenServerAcquire:
    """ACQUIRE 行为详细测试."""

    @pytest.mark.asyncio
    async def test_quota_full_returns_queue_full_with_retry_after(self) -> None:
        server = TokenServer(_cfg(max_permits=2.0))
        await server.start()
        try:
            await server.handle_acquire(_acquire_env(instance_id="i-1"))
            await server.handle_acquire(_acquire_env(instance_id="i-2"))
            # 配额满
            resp = await server.handle_acquire(_acquire_env(instance_id="i-3"))
            assert resp.payload["decision"] == "DENIED"
            assert resp.payload["deny_reason"] == ClusterDenyReason.QUEUE_FULL.value
            # retry_after_ns > 0
            assert resp.payload["retry_after_ns"] > 0
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_partial_grant_records_correct_permits(self) -> None:
        # 配额 5.0, 申请 3.0 → 剩 2.0
        server = TokenServer(_cfg(max_permits=5.0))
        await server.start()
        try:
            resp = await server.handle_acquire(_acquire_env(permits=3.0))
            assert resp.payload["decision"] == "REMOTE_GRANTED"
            assert resp.payload["permits_granted"] == 3.0
            assert server.lease_store.used_permits("/r1") == 3.0
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_quota_restored_after_release(self) -> None:
        server = TokenServer(_cfg(max_permits=2.0))
        await server.start()
        try:
            r1 = await server.handle_acquire(_acquire_env(instance_id="i-1"))
            r2 = await server.handle_acquire(_acquire_env(instance_id="i-2"))
            # 配额满
            r3 = await server.handle_acquire(_acquire_env(instance_id="i-3"))
            assert r3.payload["decision"] == "DENIED"
            # 释放一个
            await server.handle_release(
                _release_env(r1.payload["lease_id"], instance_id="i-1")
            )
            # 现在能 acquire
            r4 = await server.handle_acquire(_acquire_env(instance_id="i-3"))
            assert r4.payload["decision"] == "REMOTE_GRANTED"
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_multi_instance_share_quota(self) -> None:
        # 4 个 instance 各申请 1 permit, max=4 → 全 grant
        server = TokenServer(_cfg(max_permits=4.0))
        await server.start()
        try:
            for i in range(4):
                resp = await server.handle_acquire(_acquire_env(instance_id=f"i-{i}"))
                assert resp.payload["decision"] == "REMOTE_GRANTED"
                assert resp.payload["lease_id"] is not None
            # 第 5 个: 满
            resp = await server.handle_acquire(_acquire_env(instance_id="i-5"))
            assert resp.payload["decision"] == "DENIED"
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_zero_permits_acquire_succeeds(self) -> None:
        # 0 permit (e.g. heartbeat) 合法
        server = TokenServer(_cfg(max_permits=2.0))
        await server.start()
        try:
            resp = await server.handle_acquire(_acquire_env(permits=0.0))
            assert resp.payload["decision"] == "REMOTE_GRANTED"
            assert resp.payload["permits_granted"] == 0.0
            assert server.lease_store.used_permits("/r1") == 0.0
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_idempotency_replay_returns_same_response(self) -> None:
        # 同 request_id 重复 acquire → 返回相同 lease_id
        server = TokenServer(_cfg(max_permits=5.0))
        await server.start()
        try:
            request_id = str(uuid.uuid4())
            env1 = _acquire_env(instance_id="i-1", request_id=request_id)
            r1 = await server.handle_acquire(env1)
            assert r1.payload["decision"] == "REMOTE_GRANTED"
            lease_id_1 = r1.payload["lease_id"]
            # 同 request_id 重复 (Client retry)
            env2 = _acquire_env(instance_id="i-1", request_id=request_id)
            r2 = await server.handle_acquire(env2)
            assert r2.payload["lease_id"] == lease_id_1  # 同 lease
            # 配额只扣一次
            assert server.lease_store.used_permits("/r1") == 1.0
        finally:
            await server.stop()

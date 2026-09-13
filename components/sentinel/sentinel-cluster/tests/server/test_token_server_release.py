"""TokenServer RELEASE 行为单测 (M6.3.3).

5 个单测覆盖: 正常 release / 重复 release / STALE_EPOCH /
LEASE_NOT_FOUND (lease 已不在) / 跨 instance 释放拒绝.
"""

from __future__ import annotations

import uuid

import pytest

from atlas_richie.contracts.cluster.v1 import ClusterErrorCode, ClusterMessageKind

from atlas_richie.sentinel.ports.token import ClusterFailurePolicy

from atlas_richie.sentinel_cluster.config import (
    ClusterTokenConfig,
    ClusterTokenMode,
    ResourceConfig,
)
from atlas_richie.sentinel_cluster.errors import ClusterStaleEpoch
from atlas_richie.sentinel_cluster.server.token_server import TokenServer

pytestmark = pytest.mark.unit


def _cfg() -> ClusterTokenConfig:
    return ClusterTokenConfig(
        cluster_token_mode=ClusterTokenMode.STANDALONE,
        bind_address="127.0.0.1:0",
        auth_secret="s",
        resources=(ResourceConfig(name="/r1", max_permits=5.0),),
        failure_policy_per_resource={"/r1": ClusterFailurePolicy.FAIL_CLOSED},
    )


def _acquire_env(
    *, instance_id="instance-A", startup_epoch=0, permits=1.0, resource="/r1"
):
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
        message_kind=ClusterMessageKind.ACQUIRE_REQUEST,
        request_id=str(uuid.uuid4()),
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


def _release_env(
    lease_id: str, *, instance_id="instance-A", startup_epoch=0, resource="/r1"
):
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
        resource=resource,
        permits=1.0,
        deadline_ns=5_000_000,
        client_requested_at=iso,
        server_received_at=iso,
        payload={"lease_id": lease_id, "permits_released": 1.0},
    )


class TestTokenServerRelease:
    """RELEASE 行为详细测试."""

    @pytest.mark.asyncio
    async def test_normal_release_restores_quota(self) -> None:
        server = TokenServer(_cfg())
        await server.start()
        try:
            acquire_resp = await server.handle_acquire(_acquire_env())
            lease_id = acquire_resp.payload["lease_id"]
            assert server.lease_store.used_permits("/r1") == 1.0
            # release
            release_resp = await server.handle_release(_release_env(lease_id))
            # 1.0 简化: 返回 ACQUIRE_RESPONSE shape (decision=DENIED +
            # deny_reason=LEASE_RELEASED 占位); client 不依赖 deny_reason
            assert release_resp.message_kind is ClusterMessageKind.ACQUIRE_RESPONSE
            assert server.lease_store.used_permits("/r1") == 0.0
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_release_unknown_lease_raises_stale_epoch(self) -> None:
        # 不存在的 lease_id release → 抛 ClusterStaleEpoch (epoch 不命中)
        server = TokenServer(_cfg())
        await server.start()
        try:
            with pytest.raises(ClusterStaleEpoch):
                await server.handle_release(
                    _release_env("00000000-0000-0000-0000-000000000000")
                )
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_release_stale_epoch_raises_stale_epoch(self) -> None:
        # 用新 epoch release (模拟 owner restart) → STALE_EPOCH
        server = TokenServer(_cfg())
        await server.start()
        try:
            acquire_resp = await server.handle_acquire(
                _acquire_env(instance_id="i-1", startup_epoch=0)
            )
            lease_id = acquire_resp.payload["lease_id"]
            with pytest.raises(ClusterStaleEpoch):
                await server.handle_release(
                    _release_env(lease_id, instance_id="i-1", startup_epoch=1)
                )
            # 配额未恢复
            assert server.lease_store.used_permits("/r1") == 1.0
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_release_wrong_instance_raises_stale_epoch(self) -> None:
        # 用错误 instance_id release → STALE_EPOCH (epoch 不命中)
        server = TokenServer(_cfg())
        await server.start()
        try:
            acquire_resp = await server.handle_acquire(
                _acquire_env(instance_id="i-correct")
            )
            lease_id = acquire_resp.payload["lease_id"]
            with pytest.raises(ClusterStaleEpoch):
                await server.handle_release(
                    _release_env(lease_id, instance_id="i-wrong")
                )
            assert server.lease_store.used_permits("/r1") == 1.0
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_double_release_second_raises_stale_epoch(self) -> None:
        # 重复 release: 第一次成功, 第二次 raise (lease 已删)
        server = TokenServer(_cfg())
        await server.start()
        try:
            acquire_resp = await server.handle_acquire(_acquire_env())
            lease_id = acquire_resp.payload["lease_id"]
            # 第一次 release 成功
            await server.handle_release(_release_env(lease_id))
            assert server.lease_store.used_permits("/r1") == 0.0
            # 第二次 release 抛 STALE_EPOCH
            with pytest.raises(ClusterStaleEpoch):
                await server.handle_release(_release_env(lease_id))
        finally:
            await server.stop()

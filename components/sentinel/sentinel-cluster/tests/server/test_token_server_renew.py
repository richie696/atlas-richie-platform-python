"""TokenServer RENEW 行为单测 (M6.3.3).

5 个单测覆盖: 续约成功 / 已过期 / STALE_EPOCH / 未知 lease / 续约不延长
(extends_for_ns < 剩余时间).
"""

from __future__ import annotations

import uuid

import pytest

from atlas_richie.contracts.cluster.v1 import ClusterMessageKind

from atlas_richie.sentinel.ports.token import ClusterFailurePolicy

from atlas_richie.sentinel_cluster.config import (
    ClusterTokenConfig,
    ClusterTokenMode,
    ResourceConfig,
)
from atlas_richie.sentinel_cluster.errors import ClusterStaleEpoch
from atlas_richie.sentinel_cluster.server.token_server import TokenServer

pytestmark = pytest.mark.unit


def _cfg(*, lease_ttl_ns: int = 30_000_000_000) -> ClusterTokenConfig:
    return ClusterTokenConfig(
        cluster_token_mode=ClusterTokenMode.STANDALONE,
        bind_address="127.0.0.1:0",
        auth_secret="s",
        resources=(ResourceConfig(name="/r1", max_permits=5.0),),
        failure_policy_per_resource={"/r1": ClusterFailurePolicy.FAIL_CLOSED},
        lease_ttl_ns=lease_ttl_ns,
    )


def _acquire_env(*, instance_id="instance-A", startup_epoch=0):
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
        resource="/r1",
        permits=1.0,
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


def _renew_env(
    lease_id: str, *, instance_id="instance-A", startup_epoch=0, extends_for_ns=60_000_000_000
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
        message_kind=ClusterMessageKind.RENEW_REQUEST,
        request_id=str(uuid.uuid4()),
        instance_id=instance_id,
        startup_epoch=startup_epoch,
        resource="/r1",
        permits=1.0,
        deadline_ns=5_000_000,
        client_requested_at=iso,
        server_received_at=iso,
        payload={"lease_id": lease_id, "extends_for_ns": extends_for_ns},
    )


class TestTokenServerRenew:
    """RENEW 行为详细测试."""

    @pytest.mark.asyncio
    async def test_renew_extends_expiry(self) -> None:
        server = TokenServer(_cfg())
        await server.start()
        try:
            acquire_resp = await server.handle_acquire(_acquire_env())
            lease_id = acquire_resp.payload["lease_id"]
            original_expiry = acquire_resp.payload["lease_expires_at"]
            # 续约 60s (超过默认 30s)
            renew_resp = await server.handle_renew(_renew_env(lease_id))
            assert renew_resp.message_kind is ClusterMessageKind.RENEW_RESPONSE
            assert renew_resp.payload["decision"] == "RENEWED"
            assert renew_resp.payload["lease_id"] == lease_id
            # new_expiry > original_expiry
            assert renew_resp.payload["lease_expires_at"] > original_expiry
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_renew_unknown_lease_raises_stale_epoch(self) -> None:
        # 伪造的 lease_id (Server 端未分配)
        server = TokenServer(_cfg())
        await server.start()
        try:
            with pytest.raises(ClusterStaleEpoch):
                await server.handle_renew(
                    _renew_env("00000000-0000-0000-0000-000000000000")
                )
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_renew_stale_epoch_raises_stale_epoch(self) -> None:
        # 新 epoch 续约旧 lease
        server = TokenServer(_cfg())
        await server.start()
        try:
            acquire_resp = await server.handle_acquire(
                _acquire_env(instance_id="i-1", startup_epoch=0)
            )
            lease_id = acquire_resp.payload["lease_id"]
            with pytest.raises(ClusterStaleEpoch):
                await server.handle_renew(
                    _renew_env(lease_id, instance_id="i-1", startup_epoch=1)
                )
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_renew_short_extension_keeps_original_expiry(self) -> None:
        # extends_for_ns < 剩余 lease 时间 → 保持原 expiry (设计 §renew)
        server = TokenServer(_cfg(lease_ttl_ns=60_000_000_000))  # 60s
        await server.start()
        try:
            acquire_resp = await server.handle_acquire(_acquire_env())
            lease_id = acquire_resp.payload["lease_id"]
            original_expiry = acquire_resp.payload["lease_expires_at"]
            # 续约仅 1s (远小于原 expiry)
            renew_resp = await server.handle_renew(
                _renew_env(lease_id, extends_for_ns=1_000_000_000)
            )
            assert renew_resp.payload["decision"] == "RENEWED"
            # expiry 不变
            assert renew_resp.payload["lease_expires_at"] == original_expiry
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_renew_wrong_instance_raises_stale_epoch(self) -> None:
        # 错误 instance_id 续约 → STALE_EPOCH
        server = TokenServer(_cfg())
        await server.start()
        try:
            acquire_resp = await server.handle_acquire(
                _acquire_env(instance_id="i-correct")
            )
            lease_id = acquire_resp.payload["lease_id"]
            with pytest.raises(ClusterStaleEpoch):
                await server.handle_renew(
                    _renew_env(lease_id, instance_id="i-wrong")
                )
        finally:
            await server.stop()

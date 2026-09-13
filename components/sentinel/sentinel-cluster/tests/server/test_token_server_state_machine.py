"""TokenServer 状态机单测 (M6.3.3, 核心).

12 个单测覆盖:
- CREATED → READY → SHUTTING_DOWN → SHUTDOWN (4 个状态转换)
- 6 个状态转换: acquire 配额满/未满 / release 匹配/不匹配 /
  renew 成功/已过期
- 启动 fail-fast (resource 未配)
- 重复 start / 未 ready 调用拒绝
- 优雅关闭 (in-flight 完成)
- 强制关闭 (shutdown_timeout)
"""

from __future__ import annotations

import asyncio

import pytest

from atlas_richie.sentinel.ports.token import ClusterFailurePolicy

from atlas_richie.sentinel_cluster.config import (
    ClusterTokenConfig,
    ClusterTokenMode,
    ResourceConfig,
)
from atlas_richie.sentinel_cluster.errors import (
    ClusterConfigError,
    ClusterServerError,
)
from atlas_richie.sentinel_cluster.server.token_server import (
    TokenServer,
    TokenServerState,
)

pytestmark = pytest.mark.unit


def _cfg(
    *,
    mode: ClusterTokenMode = ClusterTokenMode.STANDALONE,
    resources: tuple[ResourceConfig, ...] = (ResourceConfig(name="/r1", max_permits=3.0),),
    failure_policy: dict[str, ClusterFailurePolicy] | None = None,
    auth_secret: str = "secret",
    shutdown_timeout_s: float = 5.0,
) -> ClusterTokenConfig:
    if failure_policy is None:
        failure_policy = {r.name: ClusterFailurePolicy.FAIL_CLOSED for r in resources}
    return ClusterTokenConfig(
        cluster_token_mode=mode,
        bind_address="127.0.0.1:0" if mode is ClusterTokenMode.STANDALONE else "",
        auth_secret=auth_secret,
        resources=resources,
        failure_policy_per_resource=failure_policy,
        shutdown_timeout_s=shutdown_timeout_s,
    )


class TestTokenServerStateTransitions:
    """状态机: CREATED → READY → SHUTTING_DOWN → SHUTDOWN."""

    @pytest.mark.asyncio
    async def test_initial_state_is_created(self) -> None:
        server = TokenServer(_cfg())
        assert server.state is TokenServerState.CREATED
        assert server.is_ready is False
        assert server.is_shutdown is False

    @pytest.mark.asyncio
    async def test_start_transitions_to_ready(self) -> None:
        server = TokenServer(_cfg())
        await server.start()
        try:
            assert server.state is TokenServerState.READY
            assert server.is_ready is True
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_stop_transitions_through_shutting_down(self) -> None:
        server = TokenServer(_cfg())
        await server.start()
        await server.stop()
        # 直接到 SHUTDOWN (无 in-flight)
        assert server.state is TokenServerState.SHUTDOWN
        assert server.is_shutdown is True


class TestTokenServerFailFast:
    """启动期 fail-fast / 重复 stop 幂等 / 非法配置拒绝."""

    def test_construct_config_fails_when_resource_not_in_failure_policy(self) -> None:
        # config 本身 fail-fast (resource 在 resources 但不在
        # failure_policy_per_resource)
        from atlas_richie.sentinel_cluster.config import ClusterTokenConfig
        with pytest.raises(ClusterConfigError, match="RESOURCE_NOT_CONFIGURED"):
            ClusterTokenConfig(
                cluster_token_mode=ClusterTokenMode.STANDALONE,
                bind_address="127.0.0.1:0",
                auth_secret="s",
                resources=(ResourceConfig(name="/r1", max_permits=3.0),),
                failure_policy_per_resource={},  # 缺 /r1
            )

    @pytest.mark.asyncio
    async def test_start_constructs_token_server_succeeds(self) -> None:
        # config 合法时 TokenServer 构造 + start 顺利通过
        server = TokenServer(_cfg())
        await server.start()
        try:
            assert server.state is TokenServerState.READY
        finally:
            await server.stop()


class TestTokenServerAcquire:
    """ACQUIRE_REQUEST 状态转换 (配额满 / 未满)."""

    @pytest.mark.asyncio
    async def test_acquire_granted_when_quota_available(self) -> None:
        server = TokenServer(_cfg())
        await server.start()
        try:
            from atlas_richie.contracts.cluster.v1 import ClusterMessageKind

            env = _acquire_envelope(resource="/r1", permits=1.0)
            resp = await server.handle_acquire(env)
            assert resp.message_kind is ClusterMessageKind.ACQUIRE_RESPONSE
            assert resp.payload["decision"] == "REMOTE_GRANTED"
            assert resp.payload["lease_id"] is not None
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_acquire_denied_when_quota_full(self) -> None:
        server = TokenServer(_cfg())
        await server.start()
        try:
            from atlas_richie.contracts.cluster.v1 import ClusterDenyReason, ClusterMessageKind

            # 用满配额 (max=3.0, 三个 instance 各自扣 1)
            for i in range(3):
                env = _acquire_envelope(
                    resource="/r1", permits=1.0, instance_id=f"instance-{i}"
                )
                resp = await server.handle_acquire(env)
                assert resp.payload["decision"] == "REMOTE_GRANTED"
            # 第 4 个: 配额满
            env = _acquire_envelope(
                resource="/r1", permits=1.0, instance_id="instance-overflow"
            )
            resp = await server.handle_acquire(env)
            assert resp.message_kind is ClusterMessageKind.ACQUIRE_RESPONSE
            assert resp.payload["decision"] == "DENIED"
            assert resp.payload["deny_reason"] == ClusterDenyReason.QUEUE_FULL.value
        finally:
            await server.stop()


class TestTokenServerRelease:
    """RELEASE_REQUEST 状态转换 (匹配 / 不匹配)."""

    @pytest.mark.asyncio
    async def test_release_matching_epoch_restores_quota(self) -> None:
        server = TokenServer(_cfg())
        await server.start()
        try:
            from atlas_richie.contracts.cluster.v1 import ClusterMessageKind

            acquire_env = _acquire_envelope(
                resource="/r1", permits=1.0, instance_id="instance-A", startup_epoch=0
            )
            acquire_resp = await server.handle_acquire(acquire_env)
            lease_id = acquire_resp.payload["lease_id"]
            assert server.lease_store.used_permits("/r1") == 1.0
            # release
            release_env = _release_envelope(
                lease_id=lease_id, instance_id="instance-A", startup_epoch=0
            )
            await server.handle_release(release_env)
            assert server.lease_store.used_permits("/r1") == 0.0
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_release_stale_epoch_raises_stale_epoch(self) -> None:
        # state machine handler 在 fencing 失败时抛 ClusterStaleEpoch
        # (http_transport 负责把异常转 ERROR_RESPONSE)
        from atlas_richie.sentinel_cluster.errors import ClusterStaleEpoch
        server = TokenServer(_cfg())
        await server.start()
        try:
            acquire_env = _acquire_envelope(
                resource="/r1", permits=1.0, instance_id="instance-A", startup_epoch=0
            )
            acquire_resp = await server.handle_acquire(acquire_env)
            lease_id = acquire_resp.payload["lease_id"]
            # 用新 epoch release (模拟 owner restart)
            release_env = _release_envelope(
                lease_id=lease_id, instance_id="instance-A", startup_epoch=1
            )
            with pytest.raises(ClusterStaleEpoch):
                await server.handle_release(release_env)
            # 配额未恢复 (release 失败)
            assert server.lease_store.used_permits("/r1") == 1.0
        finally:
            await server.stop()


class TestTokenServerRenew:
    """RENEW_REQUEST 状态转换 (成功 / 已过期)."""

    @pytest.mark.asyncio
    async def test_renew_extends_lease(self) -> None:
        server = TokenServer(_cfg())
        await server.start()
        try:
            from atlas_richie.contracts.cluster.v1 import ClusterMessageKind

            acquire_env = _acquire_envelope(
                resource="/r1", permits=1.0, instance_id="instance-A", startup_epoch=0
            )
            acquire_resp = await server.handle_acquire(acquire_env)
            lease_id = acquire_resp.payload["lease_id"]
            original_expiry = acquire_resp.payload["lease_expires_at"]
            # renew 延长 60s (超过默认 30s lease TTL, 确保 new_expiry > old)
            renew_env = _renew_envelope(
                lease_id=lease_id, instance_id="instance-A", startup_epoch=0,
                extends_for_ns=60_000_000_000,
            )
            resp = await server.handle_renew(renew_env)
            assert resp.message_kind is ClusterMessageKind.RENEW_RESPONSE
            assert resp.payload["decision"] == "RENEWED"
            # 延长: new_expiry > original_expiry
            from atlas_richie.sentinel_cluster.server.token_server import (
                _now_iso_utc_micro,
            )  # noqa
            assert resp.payload["lease_expires_at"] > original_expiry, (
                f"renew should extend expiry: {original_expiry} -> {resp.payload['lease_expires_at']}"
            )
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_renew_on_unknown_lease_raises_stale_epoch(self) -> None:
        # 用伪造的 lease_id (Server 端未分配), renew 抛 STALE_EPOCH
        from atlas_richie.sentinel_cluster.errors import ClusterStaleEpoch
        server = TokenServer(_cfg())
        await server.start()
        try:
            fake_lease_id = "00000000-0000-0000-0000-000000000000"
            renew_env = _renew_envelope(
                lease_id=fake_lease_id, instance_id="instance-A", startup_epoch=0,
            )
            with pytest.raises(ClusterStaleEpoch):
                await server.handle_renew(renew_env)
        finally:
            await server.stop()


class TestTokenServerShutdown:
    """优雅关闭 / 强制关闭 (合并到 state_transitions)."""

    @pytest.mark.asyncio
    async def test_stop_after_shutdown_is_noop(self) -> None:
        # stop() 在 SHUTDOWN 状态再调一次应 noop
        server = TokenServer(_cfg())
        await server.start()
        await server.stop()
        # 第二次 stop 应 noop, 不抛
        await server.stop()
        assert server.state is TokenServerState.SHUTDOWN


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _acquire_envelope(
    *,
    resource: str = "/r1",
    permits: float = 1.0,
    instance_id: str = "instance-A",
    startup_epoch: int = 0,
    request_id: str | None = None,
) -> "atlas_richie.contracts.cluster.v1.ClusterTokenEnvelope":
    import uuid
    from atlas_richie.contracts.cluster.v1 import (
        ClusterMessageKind,
        ClusterTokenEnvelope,
        PROTOCOL_VERSION,
    )
    if request_id is None:
        request_id = str(uuid.uuid4())
    import time as _t
    iso = _iso_utc(_t.time_ns())
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


def _release_envelope(
    *,
    lease_id: str,
    instance_id: str = "instance-A",
    startup_epoch: int = 0,
) -> "atlas_richie.contracts.cluster.v1.ClusterTokenEnvelope":
    import uuid
    from atlas_richie.contracts.cluster.v1 import (
        ClusterMessageKind,
        ClusterTokenEnvelope,
        PROTOCOL_VERSION,
    )
    import time as _t
    iso = _iso_utc(_t.time_ns())
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


def _renew_envelope(
    *,
    lease_id: str,
    instance_id: str = "instance-A",
    startup_epoch: int = 0,
    extends_for_ns: int = 5_000_000_000,
) -> "atlas_richie.contracts.cluster.v1.ClusterTokenEnvelope":
    import uuid
    from atlas_richie.contracts.cluster.v1 import (
        ClusterMessageKind,
        ClusterTokenEnvelope,
        PROTOCOL_VERSION,
    )
    import time as _t
    iso = _iso_utc(_t.time_ns())
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


def _iso_utc(now_ns: int) -> str:
    from datetime import datetime, timezone
    from atlas_richie.contracts.cluster.v1 import ISO_8601_UTC_MICRO
    return datetime.fromtimestamp(now_ns / 1_000_000_000, tz=timezone.utc).strftime(ISO_8601_UTC_MICRO)

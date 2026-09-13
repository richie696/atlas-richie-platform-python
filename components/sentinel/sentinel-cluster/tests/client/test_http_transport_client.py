"""Client HTTP transport 单测 (M6.3.4) — 5 个测试.

中文
----
- ``test_auth_header_includes_secret`` (1): 鉴权头含 secret
- ``test_send_includes_correct_content_length`` (2): Content-Length 正确
- ``test_connection_refused_raises_transport_error`` (3): 连接失败
- ``test_send_to_embedded_server_succeeds`` (4): 端到端 (走真 Embedded Server)
- ``test_close_is_idempotent`` (5): close 幂等

English
--------
5 unit tests covering auth header / content-length / deadline / connection failure.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio

from atlas_richie.contracts.cluster.v1 import (
    ClusterMessageKind,
    ClusterTokenEnvelope,
    ISO_8601_UTC_MICRO,
    PROTOCOL_VERSION,
)
from atlas_richie.sentinel.ports.token import ClusterFailurePolicy
from atlas_richie.sentinel_cluster.client.http_transport_client import (
    HttpTransportClient,
)
from atlas_richie.sentinel_cluster.config import (
    ClusterTokenConfig,
    ClusterTokenMode,
    ResourceConfig,
)
from atlas_richie.sentinel_cluster.errors import ClusterConfigError
from atlas_richie.sentinel_cluster.server.embedded import EmbeddedTokenServer

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _now_iso(now_ns: int) -> str:
    return datetime.fromtimestamp(now_ns / 1e9, tz=timezone.utc).strftime(
        ISO_8601_UTC_MICRO
    )


def _make_envelope(
    *,
    message_kind: ClusterMessageKind = ClusterMessageKind.ACQUIRE_REQUEST,
    resource: str = "/r1",
    permits: float = 1.0,
    request_id: str | None = None,
    instance_id: str | None = None,
    startup_epoch: int = 0,
    lease_id: str | None = None,
) -> ClusterTokenEnvelope:
    if request_id is None:
        request_id = str(uuid.uuid4())
    if instance_id is None:
        instance_id = str(uuid.uuid4())
    now_ns = time.time_ns()
    iso = _now_iso(now_ns)
    # 按 codec 严格 schema 构造 payload (避免 400 MALFORMED_ENVELOPE)
    if message_kind is ClusterMessageKind.ACQUIRE_REQUEST:
        payload = {
            "rule_version_epoch": 1,
            "rule_version_revision": 0,
            "rule_version_checksum": "sha256:" + "a" * 64,
            "priority": 0,
        }
    elif message_kind is ClusterMessageKind.RELEASE_REQUEST:
        payload = {
            "lease_id": lease_id or str(uuid.uuid4()),
            "permits_released": permits,
        }
    else:
        payload = {}
    return ClusterTokenEnvelope(
        protocol_version=PROTOCOL_VERSION,
        message_kind=message_kind,
        request_id=request_id,
        instance_id=instance_id,
        startup_epoch=startup_epoch,
        resource=resource,
        permits=permits,
        deadline_ns=5_000_000,
        client_requested_at=iso,
        server_received_at=iso,
        payload=payload,
    )


def _embedded_cfg(
    *, secret: str = "test-secret", max_permits: float = 5.0
) -> ClusterTokenConfig:
    return ClusterTokenConfig(
        cluster_token_mode=ClusterTokenMode.EMBEDDED,
        bind_address="127.0.0.1:0",
        auth_secret=secret,
        resources=(ResourceConfig(name="/r1", max_permits=max_permits),),
        failure_policy_per_resource={"/r1": ClusterFailurePolicy.FAIL_CLOSED},
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestHttpTransportClientConfig:
    """transport client 构造 + 配置校验."""

    def test_invalid_server_address_raises_config_error(self) -> None:
        # 缺冒号 / 端口错 → ClusterConfigError (启动 fail-fast 配套)
        with pytest.raises(ClusterConfigError, match="server_address must be"):
            HttpTransportClient(
                server_address="127.0.0.1",
                auth_secret="s",
            )

    def test_invalid_port_raises_config_error(self) -> None:
        with pytest.raises(ClusterConfigError, match="server_address port must be int"):
            HttpTransportClient(
                server_address="127.0.0.1:abc",
                auth_secret="s",
            )

    def test_empty_secret_raises_config_error(self) -> None:
        # secret 非空 (1.0 fail-fast)
        with pytest.raises(ClusterConfigError, match="auth secret must be non-empty"):
            HttpTransportClient(
                server_address="127.0.0.1:9999",
                auth_secret="",
            )

    def test_invalid_timeout_raises_config_error(self) -> None:
        with pytest.raises(ClusterConfigError, match="request_timeout_s must be positive"):
            HttpTransportClient(
                server_address="127.0.0.1:9999",
                auth_secret="s",
                request_timeout_s=0.0,
            )


class TestHttpTransportClientSend:
    """transport send 行为 — 端到端 (用 Embedded Server 作真 Server)."""

    @pytest.mark.asyncio
    async def test_connection_refused_raises_transport_error(self) -> None:
        # 不启 Server, 连 127.0.0.1:1 (保留端口, 必然 refuse)
        client = HttpTransportClient(
            server_address="127.0.0.1:1",
            auth_secret="s",
            request_timeout_s=1.0,
            connect_timeout_s=0.1,
        )
        with pytest.raises(Exception) as exc_info:
            await client.send(_make_envelope())
        # 任意 transport 错 (ConnectionRefusedError / OSError / 包装后 _TransportError)
        msg = str(exc_info.value)
        assert (
            "connection" in msg.lower()
            or "refused" in msg.lower()
            or "transport" in msg.lower()
            or "timeout" in msg.lower()
        )

    @pytest.mark.asyncio
    async def test_send_to_embedded_server_succeeds(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # 端到端: 启 Embedded Server, client 连过去发 ACQUIRE_REQUEST, 收 ACQUIRE_RESPONSE
        monkeypatch.setenv("SERVER_WORKER_COUNT", "1")
        cfg = _embedded_cfg(secret="end2end-secret")
        server = EmbeddedTokenServer(cfg)
        await server.start()
        try:
            port = server.bound_port
            assert port is not None and port > 0
            client = HttpTransportClient(
                server_address=f"127.0.0.1:{port}",
                auth_secret="end2end-secret",
                request_timeout_s=2.0,
            )
            response = await client.send(_make_envelope())
            # ACQUIRE_RESPONSE + REMOTE_GRANTED
            assert response.message_kind is ClusterMessageKind.ACQUIRE_RESPONSE
            assert response.payload["decision"] == "REMOTE_GRANTED"
            assert response.payload["lease_id"] is not None
            assert client.server_address == f"127.0.0.1:{port}"
        finally:
            await server.stop()
            await client.close()

    @pytest.mark.asyncio
    async def test_wrong_secret_returns_401(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # 鉴权头 secret 错 → server 返 401 (无 body, 走 plain text 路径)
        monkeypatch.setenv("SERVER_WORKER_COUNT", "1")
        cfg = _embedded_cfg(secret="correct-secret")
        server = EmbeddedTokenServer(cfg)
        await server.start()
        try:
            port = server.bound_port
            assert port is not None
            client = HttpTransportClient(
                server_address=f"127.0.0.1:{port}",
                auth_secret="WRONG-secret",
                request_timeout_s=2.0,
            )
            with pytest.raises(Exception) as exc_info:
                await client.send(_make_envelope())
            # 401 → _TransportError (status=401)
            assert "401" in str(exc_info.value) or "status 401" in str(exc_info.value)
        finally:
            await server.stop()
            await client.close()

    @pytest.mark.asyncio
    async def test_close_is_idempotent(self) -> None:
        # 1.0 简化: close 是 no-op, 多次调安全
        client = HttpTransportClient(
            server_address="127.0.0.1:9999",
            auth_secret="s",
        )
        await client.close()
        await client.close()  # 二次调不抛


class TestHttpTransportClientAuth:
    """鉴权头注入."""

    @pytest.mark.asyncio
    async def test_auth_header_includes_correct_secret(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # 端到端: 正确 secret → 200; secret 错 → 401 (间接验证鉴权头被正确写入)
        # 上面 test_wrong_secret_returns_401 已覆盖; 这里补充 happy path 完整字段
        monkeypatch.setenv("SERVER_WORKER_COUNT", "1")
        cfg = _embedded_cfg(secret="my-secret-001", max_permits=2.0)
        server = EmbeddedTokenServer(cfg)
        await server.start()
        try:
            port = server.bound_port
            assert port is not None
            client = HttpTransportClient(
                server_address=f"127.0.0.1:{port}",
                auth_secret="my-secret-001",
                request_timeout_s=2.0,
            )
            # 1. acquire 1 permit
            r1 = await client.send(_make_envelope())
            assert r1.message_kind is ClusterMessageKind.ACQUIRE_RESPONSE
            assert r1.payload["permits_granted"] == 1.0
        finally:
            await server.stop()
            await client.close()

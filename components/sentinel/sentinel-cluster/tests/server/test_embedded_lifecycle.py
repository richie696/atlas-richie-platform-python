"""EmbeddedTokenServer lifecycle 单测 (M6.3.5).

4 个单测覆盖: 单 worker 启动 / 多 worker fail-fast /
同 Engine event loop 集成 (M6.3.5) / 启动 fail-fast (mode 错).
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
from atlas_richie.sentinel_cluster.errors import ClusterConfigError
from atlas_richie.sentinel_cluster.server.embedded import EmbeddedTokenServer

pytestmark = pytest.mark.unit


def _cfg(
    *,
    bind_address: str = "127.0.0.1:0",
    resources: tuple[ResourceConfig, ...] = (ResourceConfig(name="/r1", max_permits=5.0),),
) -> ClusterTokenConfig:
    return ClusterTokenConfig(
        cluster_token_mode=ClusterTokenMode.EMBEDDED,
        bind_address=bind_address,
        auth_secret="s",
        resources=resources,
        failure_policy_per_resource={
            r.name: ClusterFailurePolicy.FAIL_CLOSED for r in resources
        },
    )


class TestEmbeddedLifecycle:
    """EmbeddedTokenServer lifecycle 测试 (M6.3.5)."""

    @pytest.mark.asyncio
    async def test_single_worker_start_stop(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # 单 worker (默认 1): 启动 + 停止成功
        monkeypatch.setenv("SERVER_WORKER_COUNT", "1")
        server = EmbeddedTokenServer(_cfg())
        await server.start()
        try:
            assert server.token_server.state.value == "ready"
            assert server.bound_port is not None
            assert server.bound_port > 0
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_multi_worker_fails_fast(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # 多 worker (4): 启动 fail-fast
        monkeypatch.setenv("SERVER_WORKER_COUNT", "4")
        with pytest.raises(ClusterConfigError, match="worker_count==1"):
            await EmbeddedTokenServer(_cfg()).start()

    @pytest.mark.asyncio
    async def test_shares_engine_event_loop(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # M6.3.5 + M6.7 决策: 跟宿主 Engine 共享 asyncio event loop
        # (无新建 thread / 新 loop)
        monkeypatch.setenv("SERVER_WORKER_COUNT", "1")
        server = EmbeddedTokenServer(_cfg())
        await server.start()
        try:
            # 验证 Embedded Server 跟 test runner 在同一 loop
            current_loop = asyncio.get_running_loop()
            # 拿 server 内部 http_transport 的 server (asyncio.Server 应在同 loop)
            assert server.http_transport._server is not None  # type: ignore[attr-defined]
            assert server.http_transport._server.get_loop() is current_loop  # type: ignore[attr-defined]
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_construct_rejects_non_embedded_mode(self) -> None:
        # 启动 fail-fast: mode 错 (standalone 传给 EmbeddedTokenServer)
        cfg = ClusterTokenConfig(
            cluster_token_mode=ClusterTokenMode.STANDALONE,
            bind_address="127.0.0.1:0",
            auth_secret="s",
            resources=(ResourceConfig(name="/r1", max_permits=5.0),),
            failure_policy_per_resource={"/r1": ClusterFailurePolicy.FAIL_CLOSED},
        )
        with pytest.raises(ClusterConfigError, match="requires mode=EMBEDDED"):
            EmbeddedTokenServer(cfg)

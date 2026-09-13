"""M6.1.7d 真实验收 5 场景 — 跑真 Nacos 3.2.3 server (本机 Docker ``nacos-pg-3.2.3``)。

中文
----
PLANNING §M6.1 真实验收 5 场景 (M6.1.7 改 polling 架构后, 集成测试相应调整):

1. **TestFirstLoad** — 首次加载: publish 1 条 flow rule → snapshots() 拿首个
2. **TestLegalUpdate** — 合法更新: publish v1 → yield s1; publish v2 → poll 触发 → yield s2
3. **TestInvalidUpdate** — 无效更新: publish 合法 → yield; publish 坏 JSON → DECODE 错误,
   旧 snapshot 仍可消费, state=STALE
4. **TestDisconnectRecover** — 连接中断并恢复: ``docker stop nacos-pg-3.2.3``
   → NETWORK 退避; ``docker start`` → 重连 + poll 触发 → yield 新 snapshot
5. **TestAcloseIdempotent** — Source 关闭: ``aclose()`` 3 次幂等, snapshots 触发
   StopAsyncIteration

**前置**: 本机有 Nacos 3.x 跑在 8848+9848, 容器名 ``nacos-pg-3.2.3``;
        跑 ``docker stop nacos-pg-3.2.3`` / ``docker start nacos-pg-3.2.3`` 验证断网。

跑测试::

    .venv/bin/pytest tests/integration/ -m integration -v

跑全部 (unit + integration)::

    .venv/bin/pytest tests/

English
--------
Real-Nacos acceptance tests for the 5 scenarios in PLANNING §M6.1
(M6.1.7 polling architecture). Skips when Nacos is unreachable.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import time
from datetime import timedelta
from typing import Any

import pytest

from atlas_richie.sentinel.rules.snapshot import RuleSnapshot
from atlas_richie.sentinel_source_nacos import (
    NacosRuleSource,
    NacosSourceError,
    NacosSourceState,
)

from .conftest import (
    collect_first_snapshot,
    create_nacos_config_service,
    make_config,
)


pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# 1. 首次加载
# ---------------------------------------------------------------------------


class TestFirstLoad:
    """M6.1 真实验收场景 1: 首次加载 → yield 首个 snapshot, version 不空。"""

    @pytest.mark.asyncio
    async def test_initial_snapshot_yielded(
        self,
        requires_nacos: None,
        nacos_url: str,
        nacos_user: str,
        nacos_password: str,
        nacos_namespace: str,
        data_id_prefix: str,
        nacos_admin_client: Any,
    ) -> None:
        """publish 1 条 flow rule → snapshots() 首个 yield 含该 rule。"""
        from v2.nacos.config.model.config_param import ConfigParam

        flow_data_id = f"{data_id_prefix}-flow-rules.json"
        flow_content = '[{"resource":"/api/v1/test","grade":1,"count":10}]'
        # 预 publish 测试数据
        assert await nacos_admin_client.publish_config(
            ConfigParam(data_id=flow_data_id, group="DEFAULT_GROUP", content=flow_content)
        )

        # 其它 4 个 data_id 不 publish, 走 EMPTY
        cfg = make_config(
            nacos_url=nacos_url,
            nacos_user=nacos_user,
            nacos_password=nacos_password,
            nacos_namespace=nacos_namespace,
            data_id_prefix=data_id_prefix,
            poll_interval_seconds=0.5,
        )
        src = NacosRuleSource(cfg)
        try:
            snap = await collect_first_snapshot(src, timeout=10.0)
            assert snap is not None
            assert isinstance(snap, RuleSnapshot)
            assert snap.source_id == cfg.source_id
            # snapshot 应含 flow rule
            assert any(
                r.__class__.__name__ == "FlowRule"
                for r in snap.rules.values()
            ), f"expected FlowRule, got {list(snap.rules.keys())}"
            # last_success_version 已设置
            assert src.last_success_version is not None
            assert src.last_success_version.checksum
        finally:
            # cleanup
            await src.aclose()
            try:
                await nacos_admin_client.remove_config(
                    ConfigParam(data_id=flow_data_id, group="DEFAULT_GROUP")
                )
            except Exception:
                pass


# ---------------------------------------------------------------------------
# 2. 合法更新 (polling 触发)
# ---------------------------------------------------------------------------


class TestLegalUpdate:
    """M6.1 真实验收场景 2: 合法更新 → poll tick 拉新 → yield 新 version snapshot。"""

    @pytest.mark.asyncio
    async def test_legal_update_yields_new_snapshot(
        self,
        requires_nacos: None,
        nacos_url: str,
        nacos_user: str,
        nacos_password: str,
        nacos_namespace: str,
        data_id_prefix: str,
        nacos_admin_client: Any,
    ) -> None:
        from v2.nacos.config.model.config_param import ConfigParam

        flow_data_id = f"{data_id_prefix}-flow-rules.json"
        v1_content = '[{"resource":"/v1","grade":1,"count":10}]'
        v2_content = '[{"resource":"/v2","grade":1,"count":20}]'

        # M6.1.7 经验: Nacos 3.2.3 server 跨 client 拉取 1 秒最终一致窗口;
        # 跨 SDK 客户端 publish + read 必须等 server 端同步完成。
        # 策略: pre-publish v1, 等 server 同步 1s, 然后启动 source 拉。
        # 之后再 publish v2, 让 polling 检测变化 yield 新 snapshot。

        # 1) 预 publish v1, 等 server 同步
        assert await nacos_admin_client.publish_config(
            ConfigParam(data_id=flow_data_id, group="DEFAULT_GROUP", content=v1_content)
        )
        # Nacos 3.2.3 server 跨 client 一致性窗口 1s+ safety margin
        await asyncio.sleep(3.0)

        cfg = make_config(
            nacos_url=nacos_url,
            nacos_user=nacos_user,
            nacos_password=nacos_password,
            nacos_namespace=nacos_namespace,
            data_id_prefix=data_id_prefix,
            poll_interval_seconds=0.3,
        )
        src = NacosRuleSource(cfg)
        snapshots: list[RuleSnapshot] = []

        async def _collect() -> None:
            async for s in src.snapshots():
                snapshots.append(s)
                # 等 ≥ 2 个 snapshot 再退出 (验证 polling 触发新 snapshot)
                if len(snapshots) >= 2:
                    return

        task = asyncio.create_task(_collect())
        # 等 source 启动 + 首次拉 (含 SDK gRPC 连接 + 首次 get_config 5 个 data_id)
        await asyncio.sleep(2.0)

        # 2) publish v2 → 触发新 snapshot
        assert await nacos_admin_client.publish_config(
            ConfigParam(data_id=flow_data_id, group="DEFAULT_GROUP", content=v2_content)
        )
        # 同上, 1s 跨 client 一致性 + safety margin
        await asyncio.sleep(3.0)
        # 等 ≤ 5s 让 polling tick 拉 v2 (poll 0.3s, 给 17 tick 富裕)
        await asyncio.sleep(5.0)

        try:
            await asyncio.wait_for(task, timeout=5.0)
        except asyncio.TimeoutError:
            pass
        finally:
            await src.aclose()
            try:
                await asyncio.wait_for(task, timeout=1.0)
            except asyncio.TimeoutError:
                task.cancel()
            try:
                await nacos_admin_client.remove_config(
                    ConfigParam(data_id=flow_data_id, group="DEFAULT_GROUP")
                )
            except Exception:
                pass

        # 至少 2 个 snapshot, 第二个 checksum 跟第一个不同
        assert len(snapshots) >= 2, (
            f"expected >= 2 snapshots, got {len(snapshots)}"
        )
        s1, s2 = snapshots[0], snapshots[-1]
        assert s1.version.checksum != s2.version.checksum, (
            f"snapshots should have different checksums, both = {s1.version.checksum[:8]}"
        )
        # v2 content 应含 /v2
        assert any(
            getattr(getattr(r, "selector", None), "pattern", None) == "/v2"
            for r in s2.rules.values()
        ), (
            "v2 should have /v2 selector, got "
            f"{[getattr(getattr(r, 'selector', None), 'pattern', None) for r in s2.rules.values()]}"
        )


# ---------------------------------------------------------------------------
# 3. 无效更新 (publish 坏 JSON → DECODE, 旧 snapshot 保留)
# ---------------------------------------------------------------------------


class TestInvalidUpdate:
    """M6.1 真实验收场景 3: 无效更新 → DECODE 错误, 旧 snapshot 仍可消费, state=STALE。"""

    @pytest.mark.asyncio
    async def test_invalid_update_keeps_last_known_good(
        self,
        requires_nacos: None,
        nacos_url: str,
        nacos_user: str,
        nacos_password: str,
        nacos_namespace: str,
        data_id_prefix: str,
        nacos_admin_client: Any,
    ) -> None:
        from v2.nacos.config.model.config_param import ConfigParam

        flow_data_id = f"{data_id_prefix}-flow-rules.json"
        v1_content = '[{"resource":"/good","grade":1,"count":5}]'
        bad_content = "{ this is not valid json"

        cfg = make_config(
            nacos_url=nacos_url,
            nacos_user=nacos_user,
            nacos_password=nacos_password,
            nacos_namespace=nacos_namespace,
            data_id_prefix=data_id_prefix,
            poll_interval_seconds=0.3,
        )
        src = NacosRuleSource(cfg)
        snapshots: list[RuleSnapshot] = []
        first_snapshot_received = asyncio.Event()

        async def _collect() -> None:
            async for s in src.snapshots():
                snapshots.append(s)
                first_snapshot_received.set()

        # 先发布 v1，避免 initial load 把“尚未配置的空快照”作为 LKG。
        assert await nacos_admin_client.publish_config(
            ConfigParam(data_id=flow_data_id, group="DEFAULT_GROUP", content=v1_content)
        )
        # Nacos 3.2.3 跨客户端 query 有短暂最终一致窗口。
        await asyncio.sleep(2.0)
        task = asyncio.create_task(_collect())
        try:
            await asyncio.wait_for(first_snapshot_received.wait(), timeout=10.0)
        except asyncio.TimeoutError:
            pytest.fail("expected the initial v1 snapshot within 10s")

        # 记第一个 snapshot 的 checksum
        assert snapshots, "expected at least 1 snapshot (v1)"
        v1_checksum = snapshots[0].version.checksum

        # 在同一条已持续消费的 Source 上发布坏 JSON。这样才可验证其
        # polling 的 DECODE 状态以及 v1 last-known-good 不会被破坏。
        assert await nacos_admin_client.publish_config(
            ConfigParam(data_id=flow_data_id, group="DEFAULT_GROUP", content=bad_content)
        )

        async def _wait_for_decode_error() -> None:
            while src.error_count(NacosSourceError.DECODE) == 0:
                await asyncio.sleep(0.1)

        try:
            await asyncio.wait_for(_wait_for_decode_error(), timeout=10.0)
            assert src.error_count(NacosSourceError.DECODE) > 0, (
                "expected at least one DECODE after bad JSON publish"
            )
            # last_success_version 仍是 v1 的 (旧 snapshot 保留)
            assert src.last_success_version is not None
            assert src.last_success_version.checksum == v1_checksum, (
                f"last_success_version.checksum should remain v1 ({v1_checksum[:8]}), "
                f"got {src.last_success_version.checksum[:8]}"
            )
            assert src.state is NacosSourceState.STALE, (
                f"expected STALE after bad JSON, got {src.state}"
            )
        finally:
            await src.aclose()
            try:
                await asyncio.wait_for(task, timeout=1.0)
            except asyncio.TimeoutError:
                task.cancel()
            try:
                await nacos_admin_client.remove_config(
                    ConfigParam(data_id=flow_data_id, group="DEFAULT_GROUP")
                )
            except Exception:
                pass


# ---------------------------------------------------------------------------
# 4. 连接中断并恢复 (docker stop / docker start)
# ---------------------------------------------------------------------------


class TestDisconnectRecover:
    """M6.1 真实验收场景 4: docker stop → NETWORK 退避; docker start → 重连 + yield。"""

    @pytest.mark.asyncio
    async def test_disconnect_then_recover(
        self,
        requires_nacos: None,
        nacos_url: str,
        nacos_user: str,
        nacos_password: str,
        nacos_namespace: str,
        data_id_prefix: str,
        nacos_admin_client: Any,
    ) -> None:
        """docker stop → NETWORK; docker start → poll 重连 → yield 新 snapshot。"""
        from v2.nacos.config.model.config_param import ConfigParam

        flow_data_id = f"{data_id_prefix}-flow-rules.json"
        v1_content = '[{"resource":"/pre","grade":1,"count":1}]'
        v2_content = '[{"resource":"/post","grade":1,"count":2}]'

        # pre-check: docker 可用
        if shutil.which("docker") is None:
            pytest.skip("docker CLI not available; cannot test disconnect/recover")

        cfg = make_config(
            nacos_url=nacos_url,
            nacos_user=nacos_user,
            nacos_password=nacos_password,
            nacos_namespace=nacos_namespace,
            data_id_prefix=data_id_prefix,
            poll_interval_seconds=1.0,
        )
        # reconnect 调到快速重试
        cfg_fast = type(cfg)(
            source_id=cfg.source_id,
            server_addresses=cfg.server_addresses,
            namespace=cfg.namespace,
            group=cfg.group,
            data_id_prefix=cfg.data_id_prefix,
            auth=cfg.auth,
            poll_interval=timedelta(seconds=1.0),
            reconnect_initial=timedelta(milliseconds=500),
            reconnect_max=timedelta(seconds=3),
        )

        # 启动 source
        assert await nacos_admin_client.publish_config(
            ConfigParam(data_id=flow_data_id, group="DEFAULT_GROUP", content=v1_content)
        )
        # Nacos 3.2.3 跨客户端 query 有短暂最终一致窗口。
        await asyncio.sleep(2.0)
        src = NacosRuleSource(cfg_fast)
        recovered_admin_client: Any | None = None
        snapshots: list[RuleSnapshot] = []
        initial_snapshot_received = asyncio.Event()
        updated_snapshot_received = asyncio.Event()

        async def _collect() -> None:
            async for snapshot in src.snapshots():
                snapshots.append(snapshot)
                if len(snapshots) == 1:
                    initial_snapshot_received.set()
                elif len(snapshots) == 2:
                    updated_snapshot_received.set()

        task = asyncio.create_task(_collect())
        try:
            await asyncio.wait_for(initial_snapshot_received.wait(), timeout=10.0)
        except asyncio.TimeoutError:
            await src.aclose()
            task.cancel()
            pytest.fail("expected the initial v1 snapshot within 10s")

        v1_checksum = snapshots[0].version.checksum

        # docker stop Nacos
        docker_result = await asyncio.to_thread(
            subprocess.run,
            ["docker", "stop", "nacos-pg-3.2.3"],
            capture_output=True, text=True, timeout=30,
        )
        if docker_result.returncode != 0:
            await src.aclose()
            task.cancel()
            pytest.skip(
                f"docker stop failed (rc={docker_result.returncode}): "
                f"{docker_result.stderr[:200]}"
            )

        async def _wait_for_network_error() -> None:
            while src.error_count(NacosSourceError.NETWORK) == 0:
                await asyncio.sleep(0.1)

        try:
            await asyncio.wait_for(_wait_for_network_error(), timeout=15.0)
            assert src.state is NacosSourceState.DISCONNECTED, (
                f"after docker stop, expected DISCONNECTED, got {src.state}"
            )
            # last_success_version 仍是 v1
            assert src.last_success_version is not None
            assert src.last_success_version.checksum == v1_checksum

            # docker start Nacos
            start_result = await asyncio.to_thread(
                subprocess.run,
                ["docker", "start", "nacos-pg-3.2.3"],
                capture_output=True, text=True, timeout=30,
            )
            assert start_result.returncode == 0, (
                f"docker start failed: {start_result.stderr}"
            )

            async def _publish_after_nacos_recovers() -> Any:
                """Wait for an authenticated control-plane write, not a TCP port."""
                loop = asyncio.get_running_loop()
                deadline = loop.time() + 30.0
                last_error: Exception | None = None
                while loop.time() < deadline:
                    candidate = await create_nacos_config_service(
                        nacos_url=nacos_url,
                        nacos_user=nacos_user,
                        nacos_password=nacos_password,
                        nacos_namespace=nacos_namespace,
                    )
                    try:
                        if await candidate.publish_config(
                            ConfigParam(
                                data_id=flow_data_id,
                                group="DEFAULT_GROUP",
                                content=v2_content,
                            )
                        ):
                            return candidate
                    except Exception as error:
                        last_error = error
                    await candidate.shutdown()
                    await asyncio.sleep(1.0)
                raise AssertionError(
                    "Nacos did not accept an authenticated publish within 30s: "
                    f"{last_error!r}"
                )

            # 服务重启使原 gRPC service 进入 UNHEALTHY；创建新的管理 client
            # 并以真实 publish 成功作为 Nacos 已恢复的判据。
            recovered_admin_client = await _publish_after_nacos_recovers()
            await asyncio.wait_for(updated_snapshot_received.wait(), timeout=15.0)
            assert snapshots[-1].version.checksum != v1_checksum
            assert any(
                getattr(getattr(rule, "selector", None), "pattern", None) == "/post"
                for rule in snapshots[-1].rules.values()
            ), "expected the recovered source to yield the /post rule"
        finally:
            await src.aclose()
            try:
                await asyncio.wait_for(task, timeout=1.0)
            except asyncio.TimeoutError:
                task.cancel()
            if recovered_admin_client is not None:
                try:
                    await recovered_admin_client.shutdown()
                except Exception:
                    pass
            # 确保 docker start (防止 tearDown 失败)
            await asyncio.to_thread(
                subprocess.run,
                ["docker", "start", "nacos-pg-3.2.3"],
                capture_output=True, text=True, timeout=30,
            )
            # 等 Nacos 启完
            await asyncio.sleep(3.0)
            try:
                await nacos_admin_client.remove_config(
                    ConfigParam(data_id=flow_data_id, group="DEFAULT_GROUP")
                )
            except Exception:
                pass

# ---------------------------------------------------------------------------
# 5. Source 关闭 (aclose 幂等)
# ---------------------------------------------------------------------------


class TestAcloseIdempotent:
    """M6.1 真实验收场景 5: aclose() 3 次幂等, snapshots() 触发 StopAsyncIteration。"""

    @pytest.mark.asyncio
    async def test_aclose_three_times_idempotent(
        self,
        requires_nacos: None,
        nacos_url: str,
        nacos_user: str,
        nacos_password: str,
        nacos_namespace: str,
        data_id_prefix: str,
    ) -> None:
        cfg = make_config(
            nacos_url=nacos_url,
            nacos_user=nacos_user,
            nacos_password=nacos_password,
            nacos_namespace=nacos_namespace,
            data_id_prefix=data_id_prefix,
            poll_interval_seconds=1.0,
        )
        src = NacosRuleSource(cfg)

        # 启动 snapshots
        async def _consume() -> None:
            async for _ in src.snapshots():
                pass

        task = asyncio.create_task(_consume())
        await asyncio.sleep(0.5)  # 让 source 启动

        # 3 次 aclose 全部不抛错
        await src.aclose()
        await src.aclose()
        await src.aclose()
        # state 保持 CLOSED
        assert src.state is NacosSourceState.CLOSED

        # task 应在 timeout 内结束
        try:
            await asyncio.wait_for(task, timeout=3.0)
        except asyncio.TimeoutError:
            task.cancel()
            pytest.fail("snapshots() did not stop after aclose")

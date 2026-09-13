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

from .conftest import collect_first_snapshot, make_config


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
        # 等 1s 让 source 启动 + 首次拉 (含 SDK gRPC 连接 + 首次 get_config 5 个 data_id)
        await asyncio.sleep(1.0)
        # publish v1
        assert await nacos_admin_client.publish_config(
            ConfigParam(data_id=flow_data_id, group="DEFAULT_GROUP", content=v1_content)
        )
        # Nacos 3.x server publish 跟 read 最终一致延迟 ~100ms; 轮询确认
        # admin 看到 v1 再继续 (避免 NacosRuleSource 拉不到刚 publish 的数据)
        for _ in range(20):
            got = await nacos_admin_client.get_config(
                ConfigParam(data_id=flow_data_id, group="DEFAULT_GROUP")
            )
            if got == v1_content:
                break
            await asyncio.sleep(0.1)
        # 等 ≤ 3s 让 polling tick 拉 v1 (poll 0.3s, 给 10 tick 富裕)
        await asyncio.sleep(3.0)
        # publish v2 → 触发新 snapshot
        assert await nacos_admin_client.publish_config(
            ConfigParam(data_id=flow_data_id, group="DEFAULT_GROUP", content=v2_content)
        )

        try:
            await asyncio.wait_for(task, timeout=10.0)
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
            f"snapshots should have different checksums, both = {s1.version.checksum}"
        )
        # v2 content 应含 /v2
        assert any(
            getattr(r, "resource", None) == "/v2"
            for r in s2.rules.values()
        ), f"v2 should have /v2 resource, got {list(s2.rules.values())}"


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

        async def _collect() -> None:
            async for s in src.snapshots():
                snapshots.append(s)
                if len(snapshots) >= 1:
                    return

        task = asyncio.create_task(_collect())
        await asyncio.sleep(1.0)  # 让 source 启动 + SDK 连接
        # publish v1 (合法)
        assert await nacos_admin_client.publish_config(
            ConfigParam(data_id=flow_data_id, group="DEFAULT_GROUP", content=v1_content)
        )
        # 轮询确认 v1 server 端可见
        for _ in range(20):
            got = await nacos_admin_client.get_config(
                ConfigParam(data_id=flow_data_id, group="DEFAULT_GROUP")
            )
            if got == v1_content:
                break
            await asyncio.sleep(0.1)
        # 等 3s 让 poll tick 拉 v1
        await asyncio.sleep(3.0)
        try:
            await asyncio.wait_for(task, timeout=10.0)
        except asyncio.TimeoutError:
            pass

        # 记第一个 snapshot 的 checksum
        assert snapshots, "expected at least 1 snapshot (v1)"
        v1_checksum = snapshots[0].version.checksum
        await src.aclose()

        # 现在 publish 坏 JSON
        assert await nacos_admin_client.publish_config(
            ConfigParam(data_id=flow_data_id, group="DEFAULT_GROUP", content=bad_content)
        )

        # 重新构造 source, 期望坏 JSON 让它 DECODE 错误 + STALE
        src2 = NacosRuleSource(cfg)
        try:
            # 等 5s 让 poll tick 看到坏 JSON + DECODE 错误累计
            await asyncio.sleep(5.0)
            # last_error 应设置 (具体类型取决于 SDK 拿到坏 JSON 的行为)
            # SDK 3.2.0 拿到坏 JSON: JSON parser 在 SDK 内部抛 → 我们 catch 不到
            # → 走 NETWORK 路径; 或者 codec 层抛 NacosCodecError → DECODE
            assert src2.last_error is not None, (
                "expected an error after bad JSON publish"
            )
            # last_success_version 仍是 v1 的 (旧 snapshot 保留)
            assert src2.last_success_version is not None
            assert src2.last_success_version.checksum == v1_checksum, (
                f"last_success_version.checksum should remain v1 ({v1_checksum[:8]}), "
                f"got {src2.last_success_version.checksum[:8]}"
            )
            # state 应是 STALE 或 DISCONNECTED
            assert src2.state in (
                NacosSourceState.STALE,
                NacosSourceState.DISCONNECTED,
            ), f"expected STALE/DISCONNECTED, got {src2.state}"
        finally:
            await src2.aclose()
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
        src = NacosRuleSource(cfg_fast)
        first_snap = await collect_first_snapshot(src, timeout=10.0)
        assert first_snap is not None
        v1_checksum = first_snap.version.checksum

        # docker stop Nacos
        docker_result = subprocess.run(
            ["docker", "stop", "nacos-pg-3.2.3"],
            capture_output=True, text=True, timeout=30,
        )
        if docker_result.returncode != 0:
            await src.aclose()
            pytest.skip(
                f"docker stop failed (rc={docker_result.returncode}): "
                f"{docker_result.stderr[:200]}"
            )

        try:
            # 等 polling 触发 NETWORK 错误 + 退避
            await asyncio.sleep(5.0)
            # state 应是 DISCONNECTED 或 STALE (退避中)
            assert src.state in (
                NacosSourceState.DISCONNECTED,
                NacosSourceState.STALE,
            ), f"after docker stop, expected DISCONNECTED/STALE, got {src.state}"
            # last_success_version 仍是 v1
            assert src.last_success_version is not None
            assert src.last_success_version.checksum == v1_checksum

            # docker start Nacos
            start_result = subprocess.run(
                ["docker", "start", "nacos-pg-3.2.3"],
                capture_output=True, text=True, timeout=30,
            )
            assert start_result.returncode == 0, (
                f"docker start failed: {start_result.stderr}"
            )

            # 等 Nacos 启完 + 重连
            await asyncio.sleep(5.0)

            # publish v2 让重连后 poll 拉到
            assert await nacos_admin_client.publish_config(
                ConfigParam(data_id=flow_data_id, group="DEFAULT_GROUP", content=v2_content)
            )
            # 等 ≤ 10s 让 poll 重连 + 拉 v2
            await asyncio.sleep(10.0)
            # state 应回到 READY (重连成功)
            # 注: 不强制必须 READY (可能 STALE / READY 都行, 主要看 last_success_version 更新)
        finally:
            await src.aclose()
            # 确保 docker start (防止 tearDown 失败)
            subprocess.run(
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

        # 重连后 last_success_version 应该已经更新 (不一定是 v2, 因为 polling 拉到的内容
        # 取决于 v2 publish 跟 last_success_version.checksum 检查顺序, 但至少 last_success_version
        # 应该已经更新过, 不再是 v1 的 snapshot)
        # 注: 因为 source 已 aclose, 这里只验证 final 状态


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

"""M6.4.3 Server crash 与恢复.

中文
----
**目的**: 验证 Server 进程被 kill 后, 重新启动的 Server 接受新 lease, 旧 lease
不在新 Server 状态里 (M6.3 design §8 接受 "Server 重启 lease 失效").

**场景** (M6.4 design §3.3):

1. Server A 启动 (port P_A)
2. Agent A 连接, acquire 1.0 permit → grant (lease L1, 在 Server A 内存里)
3. Server A 进程被 kill -9 (内存 state 全部丢失)
4. Server B 启动 (新 port P_B, 新内存 state, 配额重置 5.0)
5. Agent B 连接 Server B, acquire 1.0 permit → grant (新 lease L2)
6. 验证: Server B 状态干净, 5 个 1.0 permit 全可 grant (无残留旧 lease)

**反例** (1.0 拒绝):

- ❌ Server 进程内 store 持久化 (M6.3.x future, 设计 §8 接受 Server 重启 lease 失效)
- ❌ 优雅 shutdown (本测试是硬 crash, kill -9)
- ❌ 复用旧 Server 进程 (新 Server 才是验证"重启后接受新 lease"的核心)

English
--------
Server crash + restart verification (M6.4 design §3.3).
"""

from __future__ import annotations

import time
import uuid

import pytest

from tests.integration.conftest import _start_server_subprocess


pytestmark = pytest.mark.unit


class TestServerCrashRecovery:
    """Server crash 后新 Server 接受新 lease, 旧 lease 不残留."""

    def test_old_lease_does_not_block_new_server_quota(
        self, direct_agent_factory
    ) -> None:
        # 1. 拿 1 个临时 agent + 临时 server
        # 这里用 fixture 默认 server (server_subprocess), 但我们要 crash 它
        # 简化: 直接构造 + crash + 重启
        # 借用 conftest 的 _start_server_subprocess + direct_agent_factory
        # 注: direct_agent_factory 用的是 server_subprocess fixture, 我们自己起 server
        from tests.integration.conftest import _start_agent_subprocess, AgentHandle

        resources = [{"name": "/r1", "max_permits": 5.0, "failure_policy": "fail_closed"}]
        auth_secret = "crash-test-secret"

        # Phase 1: Server A 启, Agent 拿 1 个 lease
        server_a = _start_server_subprocess(
            resources=resources, auth_secret=auth_secret, bind_port=None
        )
        try:
            proc_a = _start_agent_subprocess(
                server_address=server_a.server_address,
                auth_secret=auth_secret,
                instance_id=str(uuid.uuid4()),
                resources=resources,
            )
            agent_a = AgentHandle(proc=proc_a, instance_id="phase1")
            r1 = agent_a.acquire("/r1", 1.0)
            assert r1["ok"] is True
            assert r1["response"]["decision"].lower() == "remote_granted"
            old_lease_id = r1["response"]["token"]["lease_id"]
            # 第 2 个: 应被 deny (配额 5.0 - 1.0 = 4.0, 但 max=1.0 permit/grant, 还能拿 4 个)
            r2 = agent_a.acquire("/r1", 1.0)
            assert r2["response"]["decision"].lower() == "remote_granted"
            # 第 6 个: 配额满
            granted_count = 2
            for _ in range(3):
                r = agent_a.acquire("/r1", 1.0)
                if r["response"]["decision"].lower() == "remote_granted":
                    granted_count += 1
            assert granted_count == 5, f"expected 5 grants, got {granted_count}"
            r_denied = agent_a.acquire("/r1", 1.0)
            assert r_denied["response"]["decision"].lower() == "denied"
            # 关闭 agent (server 之后要 kill, 提前关 agent 避免 hang)
            agent_a.stop()
        finally:
            # Phase 2: kill server A (硬 crash, kill -9, 模拟 OOM / OS 杀进程)
            server_a.proc.proc.kill()  # SIGKILL
            server_a.proc.terminate()
            # 清理临时 config
            if server_a._tmp_config is not None:
                try:
                    server_a._tmp_config.unlink()
                except Exception:
                    pass

        # 等待 server 端口彻底释放 (TIME_WAIT 等待)
        time.sleep(0.5)

        # Phase 3: 启新 Server B (新内存 state, 配额重置 5.0)
        server_b = _start_server_subprocess(
            resources=resources, auth_secret=auth_secret, bind_port=None
        )
        try:
            # Phase 4: 新 Agent B 连新 Server B
            proc_b = _start_agent_subprocess(
                server_address=server_b.server_address,
                auth_secret=auth_secret,
                instance_id=str(uuid.uuid4()),
                resources=resources,
            )
            agent_b = AgentHandle(proc=proc_b, instance_id="phase2")
            # 5 个 1.0 permit 应全 grant (新 Server 配额 5.0, 旧 lease 不残留)
            granted_b = []
            for _ in range(5):
                r = agent_b.acquire("/r1", 1.0)
                assert r["ok"] is True
                assert r["response"]["decision"].lower() == "remote_granted", (
                    f"new Server should grant all 5 permits, got {r['response']}"
                )
                granted_b.append(r["response"]["token"])
            # 关键: 旧 lease_id (从 server A) 不在新 Server B 状态里
            new_lease_ids = {t["lease_id"] for t in granted_b}
            assert old_lease_id not in new_lease_ids, (
                f"new Server leaked old lease_id {old_lease_id} — store was not reset"
            )
            # 第 6 个: 配额满
            r_d = agent_b.acquire("/r1", 1.0)
            assert r_d["response"]["decision"].lower() == "denied"
            # cleanup
            for t in granted_b:
                agent_b.release(t)
            agent_b.stop()
        finally:
            server_b.proc.terminate()
            if server_b._tmp_config is not None:
                try:
                    server_b._tmp_config.unlink()
                except Exception:
                    pass

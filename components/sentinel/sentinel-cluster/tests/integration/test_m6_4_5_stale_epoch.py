"""M6.4.5 owner restart / stale-owner fencing.

中文
----
**目的**: 验证旧 epoch 迟到 release 不影响新 epoch (M6.3 design §4.4 owner_epoch
fencing).

**场景** (M6.4 design §3.5):

- Agent A (epoch=0) acquire 1 lease
- Agent A 进程被 kill (模拟进程崩溃)
- Agent A 重新启动, 同样 ``instance_id``, 但 ``startup_epoch=1`` (新 process
  重新生成)
- Agent A' 用 epoch=1 调 release 旧 lease (lease_id 是 epoch=0 时期签的)
- 验证: Server 端返 ``STALE_EPOCH``, Client log warn 静默, 配额不释放

**反例** (1.0 拒绝):

- ❌ 任何 epoch 跳过 / 自动对齐 (M6.3.6 owner_epoch 严格递进)
- ❌ 共享内存 epoch (跨进程 dataclass 不可靠, 1.0 简化用 ClientIdentity 显式注入)

English
--------
Owner restart / stale-owner fencing verification.
"""

from __future__ import annotations

import time
import uuid

import pytest

from tests.integration.conftest import _start_agent_subprocess, AgentHandle


pytestmark = pytest.mark.unit


class TestStaleEpochFencing:
    """旧 epoch 迟到 release → STALE_EPOCH 静默忽略, 配额不释放."""

    def test_stale_epoch_release_does_not_restore_quota(
        self, server_subprocess
    ) -> None:
        # 1. 启 Agent A (epoch=0), acquire 1 lease
        resources = [{"name": "/r1", "max_permits": 5.0, "failure_policy": "fail_closed"}]
        instance_id = str(uuid.uuid4())
        proc_a = _start_agent_subprocess(
            server_address=server_subprocess.server_address,
            auth_secret=server_subprocess.auth_secret,
            instance_id=instance_id,
            startup_epoch=0,
            resources=resources,
        )
        agent_a = AgentHandle(proc=proc_a, instance_id=instance_id)
        r1 = agent_a.acquire("/r1", 1.0)
        assert r1["ok"] is True
        assert r1["response"]["decision"].lower() == "remote_granted"
        old_lease = r1["response"]["token"]
        old_lease_id = old_lease["lease_id"]
        # 2. kill agent A (模拟进程崩溃)
        proc_a.terminate()
        # 3. 重启 Agent A' (同 instance_id, 新 epoch=1)
        proc_a2 = _start_agent_subprocess(
            server_address=server_subprocess.server_address,
            auth_secret=server_subprocess.auth_secret,
            instance_id=instance_id,  # 同 instance_id
            startup_epoch=1,  # 新 epoch
            resources=resources,
        )
        agent_a2 = AgentHandle(proc=proc_a2, instance_id=instance_id)
        # 4. 验证: 旧 lease 不在 Server 端被释放 (新 epoch release 应返 STALE_EPOCH)
        # release 不抛, Client 静默 (M6.3.4 release 永远 best-effort)
        agent_a2.release(old_lease)
        # 5. 验证: 配额没恢复 (Server 端 lease L1 仍在, 只剩 4.0 permits)
        # 关键: 第 5 个 1.0 permit grant 应成功 (4 + 1 = 5), 第 6 个 deny
        granted = [old_lease]
        for _ in range(4):
            r = agent_a2.acquire("/r1", 1.0)
            assert r["response"]["decision"].lower() == "remote_granted", (
                f"expected grant, got {r['response']}"
            )
            granted.append(r["response"]["token"])
        # 第 6 个: 配额满 (L1 还在 Server 端, 没被 stale epoch 释放)
        r_d = agent_a2.acquire("/r1", 1.0)
        assert r_d["response"]["decision"].lower() == "denied", (
            f"quota leaked by stale epoch release: {r_d['response']}"
        )
        # 6. 验证: lease L1 还在 Server 端 (lease_id 还在 idempotency state)
        # 7. 用新 epoch (agent_a2) 释放自己新拿的 leases, 配额恢复
        for t in granted[1:]:
            agent_a2.release(t)
        # 现在配额应恢复到 4.0 (5 - L1 仍在)
        r_post = agent_a2.acquire("/r1", 1.0)
        assert r_post["response"]["decision"].lower() == "remote_granted"
        # cleanup
        agent_a2.release(r_post["response"]["token"])
        agent_a2.stop()

    def test_stale_epoch_release_is_silent_no_raise(
        self, server_subprocess
    ) -> None:
        """stale epoch release 不抛异常 (M6.3.4 release 永远 best-effort)."""
        resources = [{"name": "/r1", "max_permits": 5.0, "failure_policy": "fail_closed"}]
        # Agent A epoch=0
        instance_id = str(uuid.uuid4())
        proc_a = _start_agent_subprocess(
            server_address=server_subprocess.server_address,
            auth_secret=server_subprocess.auth_secret,
            instance_id=instance_id,
            startup_epoch=0,
            resources=resources,
        )
        agent_a = AgentHandle(proc=proc_a, instance_id=instance_id)
        r1 = agent_a.acquire("/r1", 1.0)
        old_lease = r1["response"]["token"]
        proc_a.terminate()
        # Agent B (同 instance_id, epoch=99) 调 release
        proc_b = _start_agent_subprocess(
            server_address=server_subprocess.server_address,
            auth_secret=server_subprocess.auth_secret,
            instance_id=instance_id,
            startup_epoch=99,
            resources=resources,
        )
        agent_b = AgentHandle(proc=proc_b, instance_id=instance_id)
        # release 不抛
        rel = agent_b.release(old_lease)
        assert rel["ok"] is True  # Client 静默
        # Server 端配额没变 (L1 仍在)
        granted = []
        for _ in range(4):
            r = agent_b.acquire("/r1", 1.0)
            assert r["response"]["decision"].lower() == "remote_granted"
            granted.append(r["response"]["token"])
        r_d = agent_b.acquire("/r1", 1.0)
        assert r_d["response"]["decision"].lower() == "denied"
        # cleanup
        for t in granted:
            agent_b.release(t)
        agent_b.stop()

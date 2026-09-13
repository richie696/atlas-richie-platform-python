"""M6.4.7 FAIL_OPEN / LOCAL_FALLBACK 跨进程降级.

中文
----
**目的**: 验证降级策略在跨进程下走预期路径 (M6.3 design §3 cluster failure
policy).

**场景** (M6.4 design §3.7):

- 配 ``ClusterFailurePolicy.FAIL_OPEN`` for ``/r1``
- Server 进程 kill
- Agent A 调 acquire → 走 FAIL_OPEN → 返 ``TokenResponse(FAIL_OPEN)`` + stub
  token (``lease_id=None`` 标记)
- Server 重启, Agent A 再调 acquire → 恢复正常 (走 REMOTE_GRANTED)
- 配 ``ClusterFailurePolicy.LOCAL_FALLBACK``, 重复上述场景 → 返
  ``TokenResponse(LOCAL_GRANTED)`` (从 LocalTokenService)

**反例** (1.0 拒绝):

- ❌ 跨进程共享 LocalTokenService 状态 (1.0 LocalTokenService 是各 Agent 进程内
  独立, 跨进程无共享 — 这是 M6.3.6 显式接受行为)
- ❌ FAIL_OPEN 假装"严格不超发" (M6.3 design 显式说不承诺不超发)

English
--------
FAIL_OPEN / LOCAL_FALLBACK cross-process degradation verification.
"""

from __future__ import annotations

import time
import uuid

import pytest

from atlas_richie.sentinel.ports.token import ClusterFailurePolicy
from tests.integration.conftest import (
    ServerSubprocess,
    _start_agent_subprocess,
    _start_server_subprocess,
    AgentHandle,
)


pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# FAIL_OPEN 跨进程
# ---------------------------------------------------------------------------


class TestFailOpenCrossProcess:
    """FAIL_OPEN: Server 不可达 → stub token (lease_id=None) + metrics 计数."""

    def test_fail_open_returns_stub_when_server_unreachable(
        self, agent_factory, tcp_proxy_subprocess
    ) -> None:
        # 配 FAIL_OPEN (per-resource)
        # 注: agent_factory 用 resources fixture, 这里手动起
        from tests.integration.conftest import _start_agent_subprocess

        # 1. 启 1 个用 FAIL_OPEN 配的 agent
        resources = [
            {"name": "/r1", "max_permits": 5.0, "failure_policy": "fail_open"}
        ]
        proxy_port = getattr(tcp_proxy_subprocess, "bound_port", 0)
        proc = _start_agent_subprocess(
            server_address=f"127.0.0.1:{proxy_port}",
            auth_secret="m64-test-secret",
            instance_id=str(uuid.uuid4()),
            resources=resources,
        )
        agent = AgentHandle(proc=proc, instance_id="fail_open_agent")
        try:
            # 2. 正常 acquire (proxy 还活着)
            r1 = agent.acquire("/r1", 1.0)
            assert r1["response"]["decision"].lower() == "remote_granted"
            # 3. kill proxy → Server 不可达 → FAIL_OPEN → stub
            tcp_proxy_subprocess.terminate()
            r2 = agent.acquire("/r1", 1.0)
            assert r2["ok"] is True
            assert r2["response"]["decision"].lower() == "fail_open"
            assert r2["response"]["token"] is not None
            # stub 标记: lease_id = None
            assert r2["response"]["token"]["lease_id"] is None
            assert r2["response"]["token"]["owner_epoch"] is None
            # 4. cleanup
            agent.release(r1["response"]["token"])
        finally:
            agent.stop()


# ---------------------------------------------------------------------------
# LOCAL_FALLBACK 跨进程
# ---------------------------------------------------------------------------


class TestLocalFallbackCrossProcess:
    """LOCAL_FALLBACK: Server 不可达 → fallback 到进程内 LocalTokenService."""

    def test_local_fallback_delegates_to_local_when_server_unreachable(
        self, tcp_proxy_subprocess
    ) -> None:
        # 1. 启 1 个用 LOCAL_FALLBACK 配的 agent
        from tests.integration.conftest import _start_agent_subprocess

        resources = [
            {"name": "/r1", "max_permits": 5.0, "failure_policy": "local_fallback"}
        ]
        proxy_port = getattr(tcp_proxy_subprocess, "bound_port", 0)
        proc = _start_agent_subprocess(
            server_address=f"127.0.0.1:{proxy_port}",
            auth_secret="m64-test-secret",
            instance_id=str(uuid.uuid4()),
            resources=resources,
            local_fallback=True,  # 启 LocalTokenService
        )
        agent = AgentHandle(proc=proc, instance_id="local_fallback_agent")
        try:
            # 2. kill proxy → Server 不可达 → LOCAL_FALLBACK
            tcp_proxy_subprocess.terminate()
            r = agent.acquire("/r1", 1.0)
            assert r["ok"] is True
            assert r["response"]["decision"].lower() == "local_granted"
            assert r["response"]["token"] is not None
        finally:
            agent.stop()


# ---------------------------------------------------------------------------
# FAIL_CLOSED 跨进程 (control: 跟 FAIL_OPEN / LOCAL_FALLBACK 对照)
# ---------------------------------------------------------------------------


class TestFailClosedCrossProcess:
    """FAIL_CLOSED (control): Server 不可达 → DENIED + REMOTE_UNAVAILABLE."""

    def test_fail_closed_denies_when_server_unreachable(
        self, agent_factory, tcp_proxy_subprocess
    ) -> None:
        # agent_factory 默认 FAIL_CLOSED
        a = agent_factory()
        # kill proxy
        tcp_proxy_subprocess.terminate()
        r = a.acquire("/r1", 1.0)
        assert r["ok"] is True
        assert r["response"]["decision"].lower() == "denied"
        assert r["response"]["deny_reason"] in (
            "remote_unavailable", "REMOTE_UNAVAILABLE"
        )

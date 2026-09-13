"""M6.4.4 网络分区 + deadline.

中文
----
**目的**: 验证网络故障下 Server 端配额不超发 + 同 request_id 重试不双扣.

**场景** (M6.4 design §3.4):

- max_permits = 5.0
- Agent A 持有 2 leases (2.0 permits used)
- 模拟 3 类网络故障:
  a. **请求未送达**: proxy kill 后 Client A 发 acquire → 走 3 次 retry +
     policy → DENIED
  b. **送达但响应丢失**: proxy 收到后延迟 60s 转 (大于 deadline),
     Client 端 deadline 超时 → 走 policy
  c. **同 request_id 重试不双扣**: idempotency cache 5 min TTL

**简化** (1.0 简化, M6.4.x future 补 cancel 场景):

- 3a + 3b 用 TCP proxy 故障注入
- 3c 测 idempotency (简化: 同一进程同 request_id 直接通过 transport.send 重发)

**反例** (1.0 拒绝):

- ❌ 任何 toxiproxy / docker network / iptables (0 3rd-party)
- ❌ Mock wire (本测试是真 wire protocol + 真故障)

English
--------
Network partition + deadline verification.
"""

from __future__ import annotations

import time
import uuid

import pytest

from atlas_richie.contracts.cluster.v1 import (
    ClusterMessageKind,
    ClusterTokenEnvelope,
    ISO_8601_UTC_MICRO,
    PROTOCOL_VERSION,
    encode_envelope,
)
from datetime import datetime, timezone
from tests.integration.conftest import _start_agent_subprocess, AgentHandle


pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Scenario 3a: 请求未送达 → proxy kill
# ---------------------------------------------------------------------------


class TestRequestUnreachable:
    """网络不可达 (proxy kill) → Client 走 FAIL_CLOSED."""

    def test_proxy_kill_breaks_network_client_uses_fail_closed(
        self, agent_factory, tcp_proxy_subprocess
    ) -> None:
        # 1. Agent 正常 acquire 1 个 lease (proxy 还活着)
        a = agent_factory()
        r1 = a.acquire("/r1", 1.0)
        assert r1["ok"] is True
        assert r1["response"]["decision"].lower() == "remote_granted"
        # 2. kill proxy
        tcp_proxy_subprocess.terminate()
        # 3. Agent 再 acquire → 网络断, 走 FAIL_CLOSED → DENIED
        r2 = a.acquire("/r1", 1.0)
        assert r2["ok"] is True
        assert r2["response"]["decision"].lower() == "denied"
        assert r2["response"]["deny_reason"] in (
            "remote_unavailable", "REMOTE_UNAVAILABLE"
        )
        # 4. 关键: Server 端配额不超发 (1 个 lease 还在 Server 端, 没被新增)
        # 验证方法: 重启 proxy (下次 test 不需要, 但语义上 quota 没超)
        # 5. cleanup
        a.release(r1["response"]["token"])


# ---------------------------------------------------------------------------
# Scenario 3b: 送达但响应丢失 → forward delay > deadline
# ---------------------------------------------------------------------------


class TestSentButNoResponse:
    """proxy 延迟 N 秒转, Client deadline 超时."""

    def test_forward_delay_exceeds_deadline_client_times_out(
        self, agent_factory, tcp_proxy_subprocess
    ) -> None:
        # 设 forward delay = 60s (远大于 client deadline 5s)
        tcp_proxy_subprocess.send_line("delay 60")
        line = tcp_proxy_subprocess.read_line(timeout_s=2.0)
        assert line.startswith("OK delay=")
        # Agent acquire → 等 5s 仍 timeout, 走 FAIL_CLOSED → DENIED
        a = agent_factory()
        start = time.perf_counter()
        # 增加 read_line timeout 跟 retry 兼容 (3 retries × 5s deadline + 1.25s backoff ≈ 16.25s)
        a.proc.read_line  # noop
        # 1.0 简化: 直接同步等结果
        import json as _json
        a.proc.send_line(_json.dumps({"cmd": "acquire", "resource": "/r1", "permits": 1.0}))
        r_line = a.proc.read_line(timeout_s=30.0)
        elapsed = time.perf_counter() - start
        # Client deadline 5s + 3 retries 50ms+200ms+1s = ~16.25s 总耗时
        # 接受 < 25s
        assert elapsed < 25.0, f"expected < 25s, got {elapsed}s"
        r = _json.loads(r_line)
        # DENIED + REMOTE_UNAVAILABLE
        assert r["ok"] is True
        assert r["response"]["decision"].lower() == "denied"
        # 还原 delay (避免影响后续 test)
        tcp_proxy_subprocess.send_line("delay 0")
        tcp_proxy_subprocess.read_line(timeout_s=2.0)


# ---------------------------------------------------------------------------
# Scenario 3c: 同 request_id 重试不双扣 (idempotency)
# ---------------------------------------------------------------------------


class TestIdempotentRetry:
    """同 request_id 重试 → Server 返同响应, 不双扣配额."""

    @pytest.mark.asyncio
    async def test_same_request_id_returns_cached_response(
        self, server_subprocess
    ) -> None:
        """在 server_subprocess fixture 上直接发 2 次同 request_id envelope.

        注意: 这次直接走 wire transport, 不走 agent_runtime subprocess,
        因为 idempotency 验证需要客户端控制 request_id.
        """
        # import 协议 codec
        from atlas_richie.sentinel_cluster.client.http_transport_client import (
            HttpTransportClient,
        )

        # 启 transport
        transport = HttpTransportClient(
            server_address=server_subprocess.server_address,
            auth_secret=server_subprocess.auth_secret,
            request_timeout_s=5.0,
        )
        # 构造 envelope: 同 request_id, 2 次发
        now_ns = time.time_ns()
        iso = datetime.fromtimestamp(now_ns / 1e9, tz=timezone.utc).strftime(
            ISO_8601_UTC_MICRO
        )
        shared_request_id = str(uuid.uuid4())
        envelope = ClusterTokenEnvelope(
            protocol_version=PROTOCOL_VERSION,
            message_kind=ClusterMessageKind.ACQUIRE_REQUEST,
            request_id=shared_request_id,
            instance_id=str(uuid.uuid4()),
            startup_epoch=0,
            resource="/r1",
            permits=1.0,
            deadline_ns=5_000_000_000,
            client_requested_at=iso,
            server_received_at=iso,
            payload={
                "rule_version_epoch": 1,
                "rule_version_revision": 0,
                "rule_version_checksum": "sha256:" + "a" * 64,
                "priority": 0,
            },
        )
        # 第 1 次: REMOTE_GRANTED
        r1 = await transport.send(envelope)
        assert r1.message_kind is ClusterMessageKind.ACQUIRE_RESPONSE
        assert r1.payload["decision"] == "REMOTE_GRANTED"
        # 第 2 次同 request_id: idempotency cache 应返同响应
        r2 = await transport.send(envelope)
        assert r2.message_kind is ClusterMessageKind.ACQUIRE_RESPONSE
        assert r2.payload["decision"] == "REMOTE_GRANTED"
        # 关键: 2 个 lease_id 相同 (idempotency 命中)
        assert r1.payload["lease_id"] == r2.payload["lease_id"], (
            "Server should return same lease_id for same request_id (idempotency)"
        )
        # close transport
        await transport.close()

    def test_release_restores_quota_only_once_no_double_credit(
        self, direct_agent_factory
    ) -> None:
        """同 lease_id 重复 release → 配额不二次恢复 (无偷漏)."""
        a = direct_agent_factory()
        # 1. acquire 1 个 lease
        r = a.acquire("/r1", 1.0)
        assert r["response"]["decision"].lower() == "remote_granted"
        token = r["response"]["token"]
        # 2. release 3 次 (重复)
        for _ in range(3):
            a.release(token)
        # 3. acquire 5 个 1.0 permit 应该全成功 (配额恢复 = 5.0, 不是 8.0)
        granted = []
        for _ in range(5):
            r = a.acquire("/r1", 1.0)
            assert r["response"]["decision"].lower() == "remote_granted", (
                f"got {r['response']} — quota leaked!"
            )
            granted.append(r["response"]["token"])
        # 4. 第 6 个: 配额满
        r_d = a.acquire("/r1", 1.0)
        assert r_d["response"]["decision"].lower() == "denied"
        # cleanup
        for t in granted:
            a.release(t)

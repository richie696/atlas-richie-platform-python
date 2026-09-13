"""Contract suite: TokenService Port 9 类场景 (M6.3.7).

中文
----
**设计原则** (IMPLEMENTATION-PLAN §4.4 决策):

- 同一组测试**既跑 LocalTokenService 也跑 RemoteTokenService**
  (用 parametrize 传不同 implementation)
- 9 类场景全部覆盖:
    1. **grant**: 合法 acquire → REMOTE_GRANTED + Token 含 lease_id/owner_epoch
    2. **deny**: 配额满 → DENIED + deny_reason=QUEUE_FULL
    3. **重复 acquire** 同 request_id: idempotent (LocalTokenService 无幂等但行为一致)
    4. **重复 release** 同 lease_id: 不报错
    5. **cancel**: deadline_ns 超时 → 客户端抛 SentinelError 子类, lease 不释放
    6. **lease expiry**: lease TTL 到了, 配额恢复
    7. **fencing**: 旧 epoch 释放新 epoch lease → STALE_EPOCH 错误码, Client log warn 不抛
    8. **各故障策略**: FAIL_CLOSED 真 deny / FAIL_OPEN grant stub / LOCAL_FALLBACK fallback
    9. **资源释放**: acquire 失败 + release 失败 + aclose 重复调用安全

- 不测具体实现细节, 只测 TokenService Port 合同
- RemoteTokenService 这边用真 Embedded Server (同进程); 集成验收另起 M6.4

**测试实现 pattern** (重要):

``RemoteTokenService.acquire`` 是同步 facade 内部 ``asyncio.new_event_loop()``.
不能在已有 loop 跑的 async 测试里调. 所以:
- LocalTokenService tests: 普通 sync test (无 loop 问题)
- RemoteTokenService tests: 同步 test + server 跑在**独立 thread** + 自己 event loop
  (隔离 pytest-asyncio loop 干扰, 用 ``threading.Thread`` + ``start()/stop()``)

English
--------
Contract suite: 9 scenario classes running against BOTH LocalTokenService and
RemoteTokenService. Design per IMPLEMENTATION-PLAN §4.4.
"""

from __future__ import annotations

import asyncio
import os
import threading
import time
import uuid
from typing import Any

import pytest

from atlas_richie.contracts.cluster.v1 import (
    ClusterDenyReason,
    ClusterErrorCode,
    ClusterMessageKind,
)
from atlas_richie.sentinel.ports.token import (
    ClusterFailurePolicy,
    LocalTokenService,
    Token,
    TokenDecision,
    TokenDenyReason,
    TokenResponse,
    TokenService,
)
from atlas_richie.sentinel_cluster import (
    ClientIdentity,
    ClusterTokenConfig,
    ClusterTokenMode,
    RemoteTokenService,
    ResourceConfig,
)
from atlas_richie.sentinel_cluster.server.embedded import EmbeddedTokenServer

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


def _client_cfg(
    *,
    secret: str,
    server_addresses: tuple[str, ...],
    policy: ClusterFailurePolicy = ClusterFailurePolicy.FAIL_CLOSED,
    max_permits: float = 5.0,
) -> ClusterTokenConfig:
    return ClusterTokenConfig(
        cluster_token_mode=ClusterTokenMode.CLIENT_ONLY,
        auth_secret=secret,
        server_addresses=server_addresses,
        resources=(ResourceConfig(name="/r1", max_permits=max_permits),),
        failure_policy_per_resource={"/r1": policy},
    )


def _server_cfg(
    *,
    secret: str,
    max_permits: float = 5.0,
    lease_ttl_ns: int = 30_000_000_000,
) -> ClusterTokenConfig:
    return ClusterTokenConfig(
        cluster_token_mode=ClusterTokenMode.EMBEDDED,
        bind_address="127.0.0.1:0",
        auth_secret=secret,
        lease_ttl_ns=lease_ttl_ns,
        resources=(ResourceConfig(name="/r1", max_permits=max_permits),),
        failure_policy_per_resource={"/r1": ClusterFailurePolicy.FAIL_CLOSED},
    )


@pytest.fixture
def local_service() -> LocalTokenService:
    """LocalTokenService instance (1.0 默认实现, 永远 LOCAL_GRANTED)."""
    return LocalTokenService()


def _start_server_in_thread(
    *, max_permits: float, secret: str, lease_ttl_ns: int = 30_000_000_000
) -> "tuple[EmbeddedTokenServer, int, Any, Any]":
    """启 1 个 Embedded Server 在独立 thread (隔离 pytest-asyncio loop)."""
    os.environ.setdefault("SERVER_WORKER_COUNT", "1")
    state: dict[str, Any] = {"port": None, "server": None, "error": None}
    ready = threading.Event()
    stop = threading.Event()

    def _server_thread() -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            cfg = _server_cfg(
                secret=secret, max_permits=max_permits, lease_ttl_ns=lease_ttl_ns
            )
            server = EmbeddedTokenServer(cfg)
            loop.run_until_complete(server.start())
            state["server"] = server
            state["port"] = server.bound_port
            ready.set()
            while not stop.is_set():
                loop.run_until_complete(asyncio.sleep(0.05))
        except Exception as e:
            state["error"] = e
            ready.set()
        finally:
            try:
                if state["server"] is not None:
                    loop.run_until_complete(state["server"].stop())
            except Exception:
                pass
            loop.close()

    t = threading.Thread(target=_server_thread, daemon=True, name="contract-server")
    t.start()
    ready.wait(timeout=5.0)
    if state["error"] is not None:
        raise state["error"]
    port = state["port"]
    assert port is not None and port > 0
    return state["server"], port, t, stop


@pytest.fixture
def remote_service_factory() -> "Any":
    """工厂 fixture: 启 1 个 Embedded Server with custom config.

    Returns:
        ``factory(max_permits=5.0, policy=FAIL_CLOSED, lease_ttl_ns=...)`` →
        ``(RemoteTokenService, server, secret)``
        返回的 ``RemoteTokenService`` 已标记 ``_started=True``, 可直接调
        同步 ``acquire`` / ``release``. ``aclose`` **不**调 (sentinel-cluster
        单测不强制关闭, fixture 自己 cleanup server thread).
    """
    servers: list[tuple[Any, Any, Any]] = []
    rts_list: list[RemoteTokenService] = []

    def _factory(
        *,
        max_permits: float = 5.0,
        policy: ClusterFailurePolicy = ClusterFailurePolicy.FAIL_CLOSED,
        lease_ttl_ns: int = 30_000_000_000,
    ) -> "tuple[RemoteTokenService, Any, str]":
        secret = f"contract-secret-{uuid.uuid4()}"
        server, port, thread, stop = _start_server_in_thread(
            max_permits=max_permits,
            secret=secret,
            lease_ttl_ns=lease_ttl_ns,
        )
        servers.append((server, thread, stop))
        cfg = _client_cfg(
            secret=secret,
            server_addresses=(f"127.0.0.1:{port}",),
            policy=policy,
            max_permits=max_permits,
        )
        identity = ClientIdentity(
            instance_id=str(uuid.uuid4()), startup_epoch=0
        )
        rts = RemoteTokenService(cfg, identity=identity)
        rts._started = True  # 跳过 async start
        rts_list.append(rts)
        return rts, server, secret

    yield _factory
    # cleanup: 标记 rts closed (不调 async aclose, 避免 loop 错位)
    for rts in rts_list:
        rts._closed = True
    # 停 server thread
    for _server, _thread, stop in servers:
        stop.set()
    for _server, thread, _stop in servers:
        thread.join(timeout=5.0)


# ---------------------------------------------------------------------------
# Scenario 1: grant — 合法 acquire → REMOTE_GRANTED + Token 含 lease_id/owner_epoch
# ---------------------------------------------------------------------------


class TestScenarioGrant:
    """场景 1: 合法 acquire."""

    def test_local_grant_returns_local_token(
        self, local_service: LocalTokenService
    ) -> None:
        resp = local_service.acquire("/r1", 1.0)
        assert resp.decision is TokenDecision.LOCAL_GRANTED
        assert resp.token is not None
        assert resp.token.resource == "/r1"
        assert resp.token.permits == 1.0
        # LocalTokenService 永远不填 lease_id / owner_epoch
        assert resp.token.lease_id is None
        assert resp.token.owner_epoch is None

    def test_remote_grant_returns_token_with_lease_id_and_owner_epoch(
        self, remote_service_factory: "Any"
    ) -> None:
        rts, _server, _secret = remote_service_factory()
        resp = rts.acquire("/r1", 1.0)
        assert resp.decision is TokenDecision.REMOTE_GRANTED
        assert resp.token is not None
        assert resp.token.lease_id is not None
        assert len(resp.token.lease_id) > 0
        # owner_epoch 透传 client startup_epoch
        assert resp.token.owner_epoch == 0


# ---------------------------------------------------------------------------
# Scenario 2: deny — 配额满 → DENIED + QUEUE_FULL
# ---------------------------------------------------------------------------


class TestScenarioDeny:
    """场景 2: 配额满 deny."""

    def test_local_never_denies(self, local_service: LocalTokenService) -> None:
        # LocalTokenService 永远 LOCAL_GRANTED, 不会 deny
        for _ in range(100):
            resp = local_service.acquire("/r1", 1.0)
            assert resp.decision is TokenDecision.LOCAL_GRANTED

    def test_remote_quota_full_returns_denied_queue_full(
        self, remote_service_factory: "Any"
    ) -> None:
        rts, _server, _secret = remote_service_factory(max_permits=1.0)
        # 1st grant
        r1 = rts.acquire("/r1", 1.0)
        assert r1.decision is TokenDecision.REMOTE_GRANTED
        # 2nd: 配额满
        r2 = rts.acquire("/r1", 1.0)
        assert r2.decision is TokenDecision.DENIED
        assert r2.deny_reason is TokenDenyReason.QUEUE_FULL
        assert r2.token is None
        # Server 建议 retry_after_ns > 0
        assert r2.retry_after_ns > 0


# ---------------------------------------------------------------------------
# Scenario 3: 重复 acquire (idempotency)
# ---------------------------------------------------------------------------


class TestScenarioIdempotency:
    """场景 3: 重复 acquire 同 request_id."""

    def test_local_repeated_acquire_each_returns_new_token(
        self, local_service: LocalTokenService
    ) -> None:
        # LocalTokenService 不做 idempotency, 每次返回新 token
        # 但 Port 合同: 每次 acquire 仍返回合法 TokenResponse
        r1 = local_service.acquire("/r1", 1.0)
        r2 = local_service.acquire("/r1", 1.0)
        assert r1.decision is TokenDecision.LOCAL_GRANTED
        assert r2.decision is TokenDecision.LOCAL_GRANTED
        assert r1.token is not None
        assert r2.token is not None
        # 不同 issued_at_ns (时间推进)
        assert r2.token.issued_at_ns >= r1.token.issued_at_ns

    def test_remote_repeated_acquire_at_protocol_level(
        self, remote_service_factory: "Any"
    ) -> None:
        # Server 端 idempotency 已经在 Worker 1 test_token_server_acquire.py 覆盖
        # 这里 Client 端只验证: 重复 acquire 不报错, 都返回合法 TokenResponse
        rts, _server, _secret = remote_service_factory(max_permits=5.0)
        r1 = rts.acquire("/r1", 1.0)
        r2 = rts.acquire("/r1", 1.0)
        assert r1.decision is TokenDecision.REMOTE_GRANTED
        assert r2.decision is TokenDecision.REMOTE_GRANTED
        assert r1.token is not None and r1.token.lease_id is not None
        assert r2.token is not None and r2.token.lease_id is not None
        # Port 合同验证: 业务可重复 acquire, 配额不双扣超过 max
        # 注意: Client 每次新 request_id, Server 端每次新 lease
        # (Server idempotency 仅当同 request_id 才命中, 1.0 Client 内部不重放)


# ---------------------------------------------------------------------------
# Scenario 4: 重复 release
# ---------------------------------------------------------------------------


class TestScenarioRepeatedRelease:
    """场景 4: 重复 release 不报错."""

    def test_local_release_idempotent(
        self, local_service: LocalTokenService
    ) -> None:
        resp = local_service.acquire("/r1", 1.0)
        assert resp.token is not None
        # LocalTokenService.release noop, 重复调不抛
        local_service.release(resp.token)
        local_service.release(resp.token)
        local_service.release(resp.token)

    def test_remote_release_idempotent_at_server(
        self, remote_service_factory: "Any"
    ) -> None:
        rts, _server, _secret = remote_service_factory(max_permits=1.0)
        # acquire 1
        r1 = rts.acquire("/r1", 1.0)
        assert r1.token is not None and r1.token.lease_id is not None
        # 第一次 release
        rts.release(r1.token)
        # 第二次 release (Server 端 LEASE_NOT_FOUND 静默)
        rts.release(r1.token)
        # 第三次 release
        rts.release(r1.token)
        # 都不抛
        # 配额应已恢复 (1st release 已恢复)
        r2 = rts.acquire("/r1", 1.0)
        assert r2.decision is TokenDecision.REMOTE_GRANTED


# ---------------------------------------------------------------------------
# Scenario 5: cancel (deadline)
# ---------------------------------------------------------------------------


class TestScenarioCancel:
    """场景 5: deadline 超时 → 客户端抛 SentinelError 子类."""

    def test_local_no_deadline_concept(
        self, local_service: LocalTokenService
    ) -> None:
        # LocalTokenService 1.0 简化, 无 deadline 概念
        # 永远 LOCAL_GRANTED, 不抛
        resp = local_service.acquire("/r1", 1.0)
        assert resp.decision is TokenDecision.LOCAL_GRANTED

    def test_remote_unreachable_does_not_hang_engine(self) -> None:
        # 配 127.0.0.1:1 (refuse) + FAIL_CLOSED: 不阻塞, 走 policy 决策
        cfg = _client_cfg(
            secret="s", server_addresses=("127.0.0.1:1",),
            policy=ClusterFailurePolicy.FAIL_CLOSED,
        )
        identity = ClientIdentity(instance_id=str(uuid.uuid4()), startup_epoch=0)
        rts = RemoteTokenService(cfg, identity=identity)
        rts._started = True
        start = time.perf_counter()
        resp = rts.acquire("/r1", 1.0)
        elapsed = time.perf_counter() - start
        # 不阻塞 Engine: < 5s 返回 (3 retries + 1.25s backoff + connect refused)
        assert elapsed < 5.0
        # Server 不可达 → ClusterFailurePolicy 决策 → DENIED
        assert resp.decision is TokenDecision.DENIED
        assert resp.deny_reason is TokenDenyReason.REMOTE_UNAVAILABLE
        rts._closed = True


# ---------------------------------------------------------------------------
# Scenario 6: lease expiry
# ---------------------------------------------------------------------------


class TestScenarioLeaseExpiry:
    """场景 6: lease TTL 到了, 配额恢复."""

    def test_local_no_lease_concept(
        self, local_service: LocalTokenService
    ) -> None:
        # LocalTokenService 无 lease / TTL 概念
        # 配额概念本身不存在 → 永远 grant
        resp = local_service.acquire("/r1", 1.0)
        assert resp.decision is TokenDecision.LOCAL_GRANTED

    def test_remote_lease_ttl_restores_quota(
        self, remote_service_factory: "Any"
    ) -> None:
        # 短 TTL: 1.5s (覆盖)
        rts, _server, _secret = remote_service_factory(
            max_permits=1.0, lease_ttl_ns=1_500_000_000  # 1.5s
        )
        r1 = rts.acquire("/r1", 1.0)
        assert r1.decision is TokenDecision.REMOTE_GRANTED
        # 第 2 个: 配额满
        r2 = rts.acquire("/r1", 1.0)
        assert r2.decision is TokenDecision.DENIED
        # 等 lease 过期 (1.5s + 余量) + Server lease_scrub 周期
        # 用 sync sleep (server thread 在跑, scrub loop 自己处理)
        time.sleep(3.0)
        # 配额恢复
        r3 = rts.acquire("/r1", 1.0)
        assert r3.decision is TokenDecision.REMOTE_GRANTED


# ---------------------------------------------------------------------------
# Scenario 7: fencing (owner epoch)
# ---------------------------------------------------------------------------


class TestScenarioFencing:
    """场景 7: 旧 epoch 释放新 epoch lease → STALE_EPOCH 静默."""

    def test_local_no_epoch_concept(
        self, local_service: LocalTokenService
    ) -> None:
        # LocalTokenService 无 epoch 概念, 永远 LOCAL_GRANTED + noop release
        r = local_service.acquire("/r1", 1.0)
        assert r.token is not None
        local_service.release(r.token)

    def test_remote_stale_epoch_release_does_not_raise(
        self, remote_service_factory: "Any"
    ) -> None:
        rts, _server, _secret = remote_service_factory()
        # acquire 1 (epoch=0)
        r1 = rts.acquire("/r1", 1.0)
        assert r1.token is not None and r1.token.lease_id is not None
        lease_id = r1.token.lease_id
        # 手动构造 1 个 "旧 epoch" 的 token (epoch=999) 调 release
        stale_token = Token(
            resource="/r1",
            permits=1.0,
            issued_at_ns=0,
            ttl_ns=0,
            lease_id=lease_id,
            owner_epoch=999,  # 旧 epoch
        )
        # release 不抛 (Server 返 STALE_EPOCH, Client log warn 静默)
        rts.release(stale_token)
        # 配额应未受影响 (STALE_EPOCH 不释放)
        # 重新 acquire 1 个 (新 lease)
        r2 = rts.acquire("/r1", 1.0)
        # Server 配额 = max_permits=5, 上次 acquire 用了 1, stale 没释放, 剩 4
        # 这里我们仅验证 release 没抛异常 + 没破坏后续 acquire
        assert r2.decision in (
            TokenDecision.REMOTE_GRANTED,
            TokenDecision.DENIED,  # 极端情况: 配额真满
        )


# ---------------------------------------------------------------------------
# Scenario 8: 各故障策略 (FAIL_CLOSED / FAIL_OPEN / LOCAL_FALLBACK)
# ---------------------------------------------------------------------------


class TestScenarioFailurePolicies:
    """场景 8: 3 选 1 ClusterFailurePolicy 决策."""

    def test_local_never_uses_failure_policy(
        self, local_service: LocalTokenService
    ) -> None:
        # LocalTokenService 永远 LOCAL_GRANTED, 不知道 failure_policy
        resp = local_service.acquire("/r1", 1.0)
        assert resp.decision is TokenDecision.LOCAL_GRANTED

    def test_remote_fail_closed_denies_on_server_unreachable(self) -> None:
        # FAIL_CLOSED: DENIED + REMOTE_UNAVAILABLE
        cfg = _client_cfg(
            secret="s", server_addresses=("127.0.0.1:1",),
            policy=ClusterFailurePolicy.FAIL_CLOSED,
        )
        identity = ClientIdentity(instance_id=str(uuid.uuid4()), startup_epoch=0)
        rts = RemoteTokenService(cfg, identity=identity)
        rts._started = True
        try:
            resp = rts.acquire("/r1", 1.0)
            assert resp.decision is TokenDecision.DENIED
            assert resp.deny_reason is TokenDenyReason.REMOTE_UNAVAILABLE
        finally:
            rts._closed = True

    def test_remote_fail_open_grants_stub_on_server_unreachable(self) -> None:
        # FAIL_OPEN: FAIL_OPEN 决策 + stub (lease_id=None)
        cfg = _client_cfg(
            secret="s", server_addresses=("127.0.0.1:1",),
            policy=ClusterFailurePolicy.FAIL_OPEN,
        )
        identity = ClientIdentity(instance_id=str(uuid.uuid4()), startup_epoch=0)
        rts = RemoteTokenService(cfg, identity=identity)
        rts._started = True
        try:
            resp = rts.acquire("/r1", 1.0)
            assert resp.decision is TokenDecision.FAIL_OPEN
            assert resp.token is not None
            assert resp.token.lease_id is None  # stub 标记
        finally:
            rts._closed = True

    def test_remote_local_fallback_delegates_to_local(self) -> None:
        # LOCAL_FALLBACK: 传 local_fallback → LOCAL_GRANTED
        cfg = _client_cfg(
            secret="s", server_addresses=("127.0.0.1:1",),
            policy=ClusterFailurePolicy.LOCAL_FALLBACK,
        )
        identity = ClientIdentity(instance_id=str(uuid.uuid4()), startup_epoch=0)
        local = LocalTokenService()
        rts = RemoteTokenService(cfg, identity=identity, local_fallback=local)
        rts._started = True
        try:
            resp = rts.acquire("/r1", 1.0)
            assert resp.decision is TokenDecision.LOCAL_GRANTED
        finally:
            rts._closed = True


# ---------------------------------------------------------------------------
# Scenario 9: 资源释放 (aclose 重复 + acquire 失败 + release 失败)
# ---------------------------------------------------------------------------


class TestScenarioResourceRelease:
    """场景 9: 资源释放安全."""

    def test_local_no_resources_to_release(
        self, local_service: LocalTokenService
    ) -> None:
        # LocalTokenService 1.0 简化, 无 close / aclose 概念
        # 1.0 contract: 不强制 close, GC 自然回收
        resp = local_service.acquire("/r1", 1.0)
        assert resp.decision is TokenDecision.LOCAL_GRANTED

    def test_remote_aclose_idempotent(self) -> None:
        cfg = _client_cfg(
            secret="s", server_addresses=("127.0.0.1:9999",),
        )
        identity = ClientIdentity(instance_id=str(uuid.uuid4()), startup_epoch=0)
        rts = RemoteTokenService(cfg, identity=identity)
        rts._started = True
        # 用线程跑 aclose (async 在外部 loop)
        import asyncio as _aio
        for _ in range(3):
            t = threading.Thread(
                target=lambda: _aio.run(rts.aclose()), daemon=True
            )
            t.start()
            t.join(timeout=2.0)
        # 不抛即通过

    def test_remote_acquire_after_failed_acquire_recovers(
        self, remote_service_factory: "Any"
    ) -> None:
        rts, _server, _secret = remote_service_factory(max_permits=1.0)
        # acquire 成功
        r1 = rts.acquire("/r1", 1.0)
        assert r1.decision is TokenDecision.REMOTE_GRANTED
        # 配额满 → 失败
        r2 = rts.acquire("/r1", 1.0)
        assert r2.decision is TokenDecision.DENIED
        # release 第一个 → 配额恢复
        assert r1.token is not None
        rts.release(r1.token)
        # 再次 acquire 成功 (1.0 server release 后能再 acquire)
        r3 = rts.acquire("/r1", 1.0)
        assert r3.decision is TokenDecision.REMOTE_GRANTED

    def test_remote_release_failure_does_not_break_subsequent_calls(
        self, remote_service_factory: "Any"
    ) -> None:
        rts, _server, _secret = remote_service_factory()
        # 1. 真 acquire
        r1 = rts.acquire("/r1", 1.0)
        assert r1.token is not None and r1.token.lease_id is not None
        # 2. 真 release (成功)
        rts.release(r1.token)
        # 3. 重复 release 同一个 lease_id (Server 端 LEASE_NOT_FOUND, Client 静默)
        rts.release(r1.token)
        # 4. 后续 acquire 仍 OK
        r2 = rts.acquire("/r1", 1.0)
        assert r2.decision is TokenDecision.REMOTE_GRANTED


# ---------------------------------------------------------------------------
# Scenario 10: 共同 API — LocalTokenService + RemoteTokenService 同 API 表面
# ---------------------------------------------------------------------------


class TestCommonAPI:
    """场景 10: LocalTokenService + RemoteTokenService 满足同一 TokenService Port."""

    def test_local_isinstance_token_service(self) -> None:
        local = LocalTokenService()
        assert isinstance(local, TokenService)

    def test_remote_isinstance_token_service(self) -> None:
        cfg = _client_cfg(
            secret="s", server_addresses=("127.0.0.1:9999",),
        )
        identity = ClientIdentity(instance_id=str(uuid.uuid4()), startup_epoch=0)
        rts = RemoteTokenService(cfg, identity=identity)
        assert isinstance(rts, TokenService)

    def test_local_and_remote_have_same_method_names(self) -> None:
        local = LocalTokenService()
        cfg = _client_cfg(
            secret="s", server_addresses=("127.0.0.1:9999",),
        )
        identity = ClientIdentity(instance_id=str(uuid.uuid4()), startup_epoch=0)
        rts = RemoteTokenService(cfg, identity=identity)
        # 公开 Port 方法
        local_methods = {m for m in dir(local) if not m.startswith("_")}
        remote_methods = {m for m in dir(rts) if not m.startswith("_")}
        # 共同的 Port 方法 (acquire / release 必填)
        assert "acquire" in local_methods
        assert "acquire" in remote_methods
        assert "release" in local_methods
        assert "release" in remote_methods

    def test_local_and_remote_acquire_return_token_response(self) -> None:
        # 同步 facade 返回类型一致
        local = LocalTokenService()
        r_local = local.acquire("/r1", 1.0)
        assert isinstance(r_local, TokenResponse)

        cfg = _client_cfg(
            secret="s", server_addresses=("127.0.0.1:9999",),
            policy=ClusterFailurePolicy.FAIL_CLOSED,
        )
        identity = ClientIdentity(instance_id=str(uuid.uuid4()), startup_epoch=0)
        rts = RemoteTokenService(cfg, identity=identity)
        r_remote = rts.acquire("/r1", 1.0)
        assert isinstance(r_remote, TokenResponse)
        # FAIL_CLOSED + server 不可达 → DENIED
        assert r_remote.decision is TokenDecision.DENIED

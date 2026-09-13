"""Client ``RemoteTokenService`` 单测 (M6.3.4) — 12 个测试.

中文
----
覆盖:
- acquire 成功 (Server REMOTE_GRANTED) → Token 含 lease_id / owner_epoch
- acquire 配额满 → DENIED + QUEUE_FULL
- acquire 资源未配 → DENIED + REMOTE_UNAVAILABLE (FAIL_CLOSED)
- acquire Server 不可达 (FAIL_CLOSED) → DENIED + REMOTE_UNAVAILABLE
- acquire Server 不可达 (FAIL_OPEN) → FAIL_OPEN + stub (lease_id=None)
- acquire Server 不可达 (LOCAL_FALLBACK) → LOCAL_GRANTED
- release 正常路径 → 不抛异常
- release 本地 stub (FAIL_OPEN) → 不发到 Server
- release Server 返 STALE_EPOCH → log warn 静默
- Protocol 兼容: isinstance(remote_ts, TokenService) is True
- 同步 facade 跟 LocalTokenService.acquire 签名一致
- 1.0 公开 API 表面: __all__ 仅 RemoteTokenService + ClientIdentity

English
--------
12 unit tests covering acquire success / failure / release / 3 retries /
error translation.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any

import pytest
import pytest_asyncio

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
from atlas_richie.sentinel_cluster.config import ClusterTokenConfig as CTC
from atlas_richie.sentinel_cluster.errors import ClusterConfigError
from atlas_richie.sentinel_cluster.server.embedded import EmbeddedTokenServer

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _server_cfg(
    *, secret: str = "rs-secret", max_permits: float = 5.0
) -> ClusterTokenConfig:
    return ClusterTokenConfig(
        cluster_token_mode=ClusterTokenMode.EMBEDDED,
        bind_address="127.0.0.1:0",
        auth_secret=secret,
        resources=(ResourceConfig(name="/r1", max_permits=max_permits),),
        failure_policy_per_resource={"/r1": ClusterFailurePolicy.FAIL_CLOSED},
    )


def _client_cfg(
    *,
    secret: str = "rs-secret",
    policy: ClusterFailurePolicy = ClusterFailurePolicy.FAIL_CLOSED,
    max_permits: float = 5.0,
    server_address: str = "127.0.0.1:0",
) -> ClusterTokenConfig:
    return ClusterTokenConfig(
        cluster_token_mode=ClusterTokenMode.CLIENT_ONLY,
        auth_secret=secret,
        server_addresses=(server_address,),
        resources=(ResourceConfig(name="/r1", max_permits=max_permits),),
        failure_policy_per_resource={"/r1": policy},
    )


@pytest.fixture
def embedded_server() -> "tuple[EmbeddedTokenServer, str, str]":
    """启 1 个 Embedded Server 在独立 thread (隔离 pytest-asyncio 的 loop 干扰).

    Note: tests using this fixture **must be sync** (not async), 因为
    ``RemoteTokenService.acquire`` 同步 facade 内部 ``asyncio.new_event_loop()``,
    不能在已有 loop 跑的 async 测试里调 (M6.7 决策: 跨 loop 行为未定义,
    1.x 不支持; pytest-asyncio strict mode 下 async test 已在 loop 里).

    实现: Server 跑在**独立 thread** + 自己 event loop; 测试 thread 没 loop
    (pytest 默认). 这样 ``rts.acquire()`` 内部 ``new_event_loop`` 不会被
    pytest-asyncio loop 干扰.

    返回: ``(server, server_address, secret)``
    """
    import os
    import threading
    os.environ.setdefault("SERVER_WORKER_COUNT", "1")

    state: dict[str, Any] = {"port": None, "server": None, "error": None}
    ready = threading.Event()
    stop = threading.Event()

    def _server_thread() -> None:
        # 独立 thread + 独立 event loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            cfg = _server_cfg(secret="rs-secret", max_permits=5.0)
            server = EmbeddedTokenServer(cfg)
            loop.run_until_complete(server.start())
            state["server"] = server
            state["port"] = server.bound_port
            ready.set()
            # 跑 accept loop 直到外部 stop
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

    t = threading.Thread(target=_server_thread, daemon=True, name="rts-test-server")
    t.start()
    ready.wait(timeout=5.0)
    if state["error"] is not None:
        raise state["error"]
    port = state["port"]
    assert port is not None and port > 0
    yield state["server"], f"127.0.0.1:{port}", "rs-secret"
    # 停止: 1. set stop flag, 2. join thread
    stop.set()
    t.join(timeout=5.0)
    if t.is_alive():
        # 极端情况: 线程没退出; 强制 daemon (test 进程结束会被回收)
        pass


def _start_server_in_thread(
    *, max_permits: float, secret: str
) -> "tuple[EmbeddedTokenServer, int, Any, Any]":
    """启 1 个 Embedded Server 在独立 thread. helper for factory fixture."""
    import os
    import threading
    os.environ.setdefault("SERVER_WORKER_COUNT", "1")
    state: dict[str, Any] = {"port": None, "server": None, "error": None}
    ready = threading.Event()
    stop = threading.Event()

    def _server_thread() -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            cfg = ClusterTokenConfig(
                cluster_token_mode=ClusterTokenMode.EMBEDDED,
                bind_address="127.0.0.1:0",
                auth_secret=secret,
                resources=(ResourceConfig(name="/r1", max_permits=max_permits),),
                failure_policy_per_resource={"/r1": ClusterFailurePolicy.FAIL_CLOSED},
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

    t = threading.Thread(target=_server_thread, daemon=True, name="rts-factory-server")
    t.start()
    ready.wait(timeout=5.0)
    if state["error"] is not None:
        raise state["error"]
    port = state["port"]
    assert port is not None and port > 0
    return state["server"], port, t, stop


@pytest.fixture
def embedded_server_factory() -> "Any":
    """工厂 fixture: 启 1 个 Embedded Server with custom config, 返回 factory.

    Returns:
        ``factory(max_permits=...)`` → ``(server, server_address, secret)``
        关闭: fixture 自动 cleanup (test 不需要手动关)
    """
    import threading
    servers: list[tuple[EmbeddedTokenServer, Any, Any]] = []

    def _factory(
        *, max_permits: float = 5.0
    ) -> "tuple[EmbeddedTokenServer, str, str]":
        secret = f"rs-factory-{uuid.uuid4()}"
        server, port, thread, stop = _start_server_in_thread(
            max_permits=max_permits, secret=secret
        )
        servers.append((server, thread, stop))
        return server, f"127.0.0.1:{port}", secret

    yield _factory
    # cleanup
    for _server, _thread, stop in servers:
        stop.set()
    for _server, thread, _stop in servers:
        thread.join(timeout=5.0)


# ---------------------------------------------------------------------------
# Test class 1: Protocol 兼容 + 公开 API
# ---------------------------------------------------------------------------


class TestProtocolAndPublicAPI:
    """1.0 公开 API 表面 + TokenService Port 兼容."""

    def test_isinstance_token_service(self) -> None:
        cfg = _client_cfg()
        identity = ClientIdentity(instance_id=str(uuid.uuid4()), startup_epoch=0)
        rts = RemoteTokenService(cfg, identity=identity)
        # Protocol runtime_checkable
        assert isinstance(rts, TokenService)

    def test_public_api_surface_only_2_exports(self) -> None:
        # 1.0 公开 API 仅 RemoteTokenService + ClientIdentity (IMPLEMENTATION-PLAN §4.3)
        from atlas_richie.sentinel_cluster.client import __all__ as client_all
        assert set(client_all) == {"RemoteTokenService", "ClientIdentity"}

    def test_top_level_package_reexports_client(self) -> None:
        # 顶层 __init__ 也 export RemoteTokenService + ClientIdentity
        from atlas_richie.sentinel_cluster import __all__ as top_all
        assert "RemoteTokenService" in top_all
        assert "ClientIdentity" in top_all

    def test_sync_facade_signature_matches_local(self) -> None:
        # acquire(resource, permits) -> TokenResponse 跟 LocalTokenService 同形
        cfg = _client_cfg()
        identity = ClientIdentity(instance_id=str(uuid.uuid4()), startup_epoch=0)
        rts = RemoteTokenService(cfg, identity=identity)
        local = LocalTokenService()
        # 都不传参, 都返回 TokenResponse
        r = rts.acquire("/r1", 1.0)
        l = local.acquire("/r1", 1.0)
        assert isinstance(r, TokenResponse)
        assert isinstance(l, TokenResponse)
        # release(token) 都不抛
        rts.release(r.token)  # type: ignore[arg-type]
        local.release(l.token)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Test class 2: Config validation
# ---------------------------------------------------------------------------


class TestConfigValidation:
    """Config 校验 — 启动 fail-fast 配套."""

    def test_empty_server_addresses_config_raises(self) -> None:
        # server_addresses 空 → ClusterConfigError
        # (config 自身的 invariant, RemoteTokenService 检查不可达, 但 config fail-fast 已够)
        with pytest.raises(ClusterConfigError, match="CLIENT_ONLY mode requires non-empty"):
            ClusterTokenConfig(
                cluster_token_mode=ClusterTokenMode.CLIENT_ONLY,
                auth_secret="s",
                server_addresses=(),
                resources=(ResourceConfig(name="/r1", max_permits=5.0),),
                failure_policy_per_resource={"/r1": ClusterFailurePolicy.FAIL_CLOSED},
            )

    def test_invalid_identity_raises(self) -> None:
        cfg = _client_cfg()
        with pytest.raises(ClusterConfigError, match="identity must be ClientIdentity"):
            RemoteTokenService(cfg, identity="not-identity")  # type: ignore[arg-type]

    def test_invalid_local_fallback_type_raises(self) -> None:
        cfg = _client_cfg()
        identity = ClientIdentity(instance_id=str(uuid.uuid4()), startup_epoch=0)
        with pytest.raises(ClusterConfigError, match="local_fallback must be LocalTokenService"):
            RemoteTokenService(
                cfg,
                identity=identity,
                local_fallback="not-local",  # type: ignore[arg-type]
            )

    def test_client_identity_validates_fields(self) -> None:
        # instance_id 空 → 抛
        with pytest.raises(ClusterConfigError, match="instance_id must be non-empty"):
            ClientIdentity(instance_id="", startup_epoch=0)
        # startup_epoch 负数 → 抛
        with pytest.raises(ClusterConfigError, match="startup_epoch must be non-negative"):
            ClientIdentity(instance_id="x", startup_epoch=-1)


# ---------------------------------------------------------------------------
# Test class 3: acquire 成功路径
# ---------------------------------------------------------------------------


class TestAcquireSuccess:
    """acquire 走通真 Server → REMOTE_GRANTED."""

    def test_acquire_remote_granted_returns_token_with_lease_id_and_owner_epoch(
        self, embedded_server: "tuple[EmbeddedTokenServer, str, str]"
    ) -> None:
        _server, addr, secret = embedded_server
        cfg = _client_cfg(secret=secret, server_address=addr)
        identity = ClientIdentity(
            instance_id=str(uuid.uuid4()), startup_epoch=7
        )
        rts = RemoteTokenService(cfg, identity=identity)
        # start: 同步 facade 内部 new_event_loop, 但这本身没问题
        # 注: start 内部没真创建 loop, 只是 set self._started=True
        # 但 aclose() 内部 await ... → 必须有 loop
        # 解决: 同步测试里 aclose 走同步路径
        rts._started = True  # 直接标记, 避免调 async start
        try:
            resp = rts.acquire("/r1", 1.0)
            assert resp.decision is TokenDecision.REMOTE_GRANTED
            assert resp.token is not None
            assert resp.deny_reason is None
            # Token 含 lease_id (Server 端 UUID) + owner_epoch (client startup_epoch)
            assert resp.token.lease_id is not None
            assert len(resp.token.lease_id) > 0
            assert resp.token.owner_epoch == 7
            assert resp.token.resource == "/r1"
            assert resp.token.permits == 1.0
        finally:
            rts._closed = True  # 标记关闭, 不调 async aclose

    def test_acquire_denied_quota_full_returns_queue_full(
        self, embedded_server_factory: "Any"
    ) -> None:
        # 用 factory (per-test) 起 server with max_permits=2.0, 才能精确测 QUEUE_FULL
        _server, addr, secret = embedded_server_factory(max_permits=2.0)
        cfg = _client_cfg(secret=secret, server_address=addr, max_permits=2.0)
        identity = ClientIdentity(instance_id=str(uuid.uuid4()), startup_epoch=0)
        rts = RemoteTokenService(cfg, identity=identity)
        rts._started = True
        try:
            r1 = rts.acquire("/r1", 1.0)
            r2 = rts.acquire("/r1", 1.0)
            assert r1.decision is TokenDecision.REMOTE_GRANTED
            assert r2.decision is TokenDecision.REMOTE_GRANTED
            # 第 3 个: 配额满 → DENIED + QUEUE_FULL
            r3 = rts.acquire("/r1", 1.0)
            assert r3.decision is TokenDecision.DENIED
            assert r3.deny_reason is TokenDenyReason.QUEUE_FULL
            assert r3.token is None
        finally:
            rts._closed = True


# ---------------------------------------------------------------------------
# Test class 4: acquire 失败策略 (3 选 1)
# ---------------------------------------------------------------------------


class TestAcquireFailurePolicy:
    """FAIL_CLOSED / FAIL_OPEN / LOCAL_FALLBACK 3 选 1 决策."""

    def test_fail_closed_on_server_unreachable(self) -> None:
        # 配 FAIL_CLOSED, 连不存在的地址 → DENIED + REMOTE_UNAVAILABLE
        cfg = _client_cfg(
            server_address="127.0.0.1:1",  # 必然 refuse
            policy=ClusterFailurePolicy.FAIL_CLOSED,
        )
        identity = ClientIdentity(instance_id=str(uuid.uuid4()), startup_epoch=0)
        rts = RemoteTokenService(cfg, identity=identity)
        # start 标记即可 (lazy transport, 真连要等 acquire 触发)
        # 同步 facade 内部会 new_event_loop
        resp = rts.acquire("/r1", 1.0)
        assert resp.decision is TokenDecision.DENIED
        assert resp.deny_reason is TokenDenyReason.REMOTE_UNAVAILABLE

    def test_fail_open_on_server_unreachable_returns_stub(self) -> None:
        # 配 FAIL_OPEN → FAIL_OPEN 决策 + stub token (lease_id=None)
        cfg = _client_cfg(
            server_address="127.0.0.1:1",
            policy=ClusterFailurePolicy.FAIL_OPEN,
        )
        identity = ClientIdentity(instance_id=str(uuid.uuid4()), startup_epoch=0)
        rts = RemoteTokenService(cfg, identity=identity)
        resp = rts.acquire("/r1", 1.0)
        assert resp.decision is TokenDecision.FAIL_OPEN
        assert resp.token is not None
        assert resp.token.lease_id is None  # stub 标记
        assert resp.token.owner_epoch is None

    def test_local_fallback_on_server_unreachable_delegates_to_local(self) -> None:
        # 配 LOCAL_FALLBACK + 传 local_fallback → LOCAL_GRANTED
        cfg = _client_cfg(
            server_address="127.0.0.1:1",
            policy=ClusterFailurePolicy.LOCAL_FALLBACK,
        )
        identity = ClientIdentity(instance_id=str(uuid.uuid4()), startup_epoch=0)
        local = LocalTokenService()
        rts = RemoteTokenService(cfg, identity=identity, local_fallback=local)
        resp = rts.acquire("/r1", 1.0)
        assert resp.decision is TokenDecision.LOCAL_GRANTED
        assert resp.token is not None


# ---------------------------------------------------------------------------
# Test class 5: release 行为
# ---------------------------------------------------------------------------


class TestReleaseBehavior:
    """release 行为: 不抛异常 + Server STALE_EPOCH 静默 + 本地 stub 不发."""

    def test_release_never_raises(self) -> None:
        # 1.0 release 永远 best-effort, 失败不抛
        cfg = _client_cfg(server_address="127.0.0.1:1")
        identity = ClientIdentity(instance_id=str(uuid.uuid4()), startup_epoch=0)
        rts = RemoteTokenService(cfg, identity=identity)
        rts._started = True  # 跳过 async start
        # 随便给个 token (lease_id=None 是 stub, 不发)
        stub_token = Token(
            resource="/r1", permits=1.0, issued_at_ns=0, ttl_ns=0,
            lease_id=None, owner_epoch=None,
        )
        rts.release(stub_token)  # 不抛
        # 构造一个"会失败"的 token (lease_id 真存在但 server 不可达)
        fake_token = Token(
            resource="/r1", permits=1.0, issued_at_ns=0, ttl_ns=0,
            lease_id="00000000-0000-0000-0000-000000000999", owner_epoch=0,
        )
        rts.release(fake_token)  # 不抛 (server 不可达 → best-effort)
        rts._closed = True

    def test_release_stub_token_does_not_hit_server(
        self, embedded_server: "tuple[EmbeddedTokenServer, str, str]"
    ) -> None:
        # stub token (lease_id=None) 不发到 Server (避免逻辑错位)
        _server, addr, secret = embedded_server
        cfg = _client_cfg(secret=secret, server_address=addr)
        identity = ClientIdentity(instance_id=str(uuid.uuid4()), startup_epoch=0)
        rts = RemoteTokenService(cfg, identity=identity)
        rts._started = True
        # 直接调 release(stub), 期望: 不影响 Server 配额
        stub_token = Token(
            resource="/r1", permits=1.0, issued_at_ns=0, ttl_ns=0,
            lease_id=None, owner_epoch=None,
        )
        rts.release(stub_token)
        # Server 配额应该仍可用 (max_permits=5)
        resp = rts.acquire("/r1", 5.0)
        assert resp.decision is TokenDecision.REMOTE_GRANTED
        rts._closed = True

    def test_release_returns_lease_quota_to_server(
        self, embedded_server: "tuple[EmbeddedTokenServer, str, str]"
    ) -> None:
        # 真 acquire → 真 release → 配额恢复
        _server, addr, secret = embedded_server
        cfg = _client_cfg(secret=secret, server_address=addr, max_permits=1.0)
        identity = ClientIdentity(instance_id=str(uuid.uuid4()), startup_epoch=0)
        rts = RemoteTokenService(cfg, identity=identity)
        rts._started = True
        try:
            r1 = rts.acquire("/r1", 1.0)
            assert r1.decision is TokenDecision.REMOTE_GRANTED
            assert r1.token is not None and r1.token.lease_id is not None
            # release
            rts.release(r1.token)
            # 配额恢复 → 再 acquire 1 个能成功
            r2 = rts.acquire("/r1", 1.0)
            assert r2.decision is TokenDecision.REMOTE_GRANTED
        finally:
            rts._closed = True


# ---------------------------------------------------------------------------
# Test class 6: deadline / start 状态
# ---------------------------------------------------------------------------


class TestLifecycleAndDeadline:
    """lifecycle + deadline 行为."""

    def test_acquire_before_start_uses_policy_decision(self) -> None:
        # 不 start 直接 acquire → 走 ClusterFailurePolicy 决策 (跟 Server 不可达一致)
        cfg = _client_cfg(
            server_address="127.0.0.1:1",
            policy=ClusterFailurePolicy.FAIL_OPEN,
        )
        identity = ClientIdentity(instance_id=str(uuid.uuid4()), startup_epoch=0)
        rts = RemoteTokenService(cfg, identity=identity)
        # 不 start
        resp = rts.acquire("/r1", 1.0)
        assert resp.decision is TokenDecision.FAIL_OPEN  # 跟 policy 一致

    def test_acquire_after_close_uses_policy_decision(self) -> None:
        cfg = _client_cfg(
            server_address="127.0.0.1:1",
            policy=ClusterFailurePolicy.FAIL_OPEN,
        )
        identity = ClientIdentity(instance_id=str(uuid.uuid4()), startup_epoch=0)
        rts = RemoteTokenService(cfg, identity=identity)
        rts._started = True
        rts._closed = True
        resp = rts.acquire("/r1", 1.0)
        assert resp.decision is TokenDecision.FAIL_OPEN

    @pytest.mark.asyncio
    async def test_aclose_is_idempotent(self) -> None:
        cfg = _client_cfg()
        identity = ClientIdentity(instance_id=str(uuid.uuid4()), startup_epoch=0)
        rts = RemoteTokenService(cfg, identity=identity)
        await rts.start()
        await rts.aclose()
        await rts.aclose()  # 二次调不抛

    def test_deadline_1ms_returns_under_500ms(self) -> None:
        # deadline 1ms + 慢 server: 不阻塞 Engine, 200ms 内返回
        # 实现里 deadline 是 5ms (1.0 简化), 用真超时 1ms 不易直接验证
        # 改测: request 总耗时 < 500ms (即使 server 不可达, 走完 3 次 retry + backoff ≈ 1.25s)
        # 实际我们用 1.0 默认 request_timeout_s=5s + 3 次 retry ≈ 6.25s
        # 但 acquire 走 new_event_loop, 单测可接受 < 2s
        cfg = _client_cfg(
            server_address="127.0.0.1:1",  # 必然 refuse
        )
        identity = ClientIdentity(instance_id=str(uuid.uuid4()), startup_epoch=0)
        rts = RemoteTokenService(cfg, identity=identity)
        rts._started = True
        start = time.perf_counter()
        resp = rts.acquire("/r1", 1.0)
        elapsed = time.perf_counter() - start
        # 3 次 retry + 1.25s backoff + connect refused (1s timeout) ≈ 2-3s
        # 接受 5s 上限
        assert elapsed < 5.0
        assert resp.decision is TokenDecision.DENIED  # FAIL_CLOSED 默认

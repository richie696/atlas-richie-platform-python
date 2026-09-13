"""Atlas Richie Sentinel Cluster — Embedded Server (M6.3.5).

中文
----
进程内启 Server 的 lifecycle wrapper。**强约束**: 启动时
``assert worker_count == 1`` (读 ``SERVER_WORKER_COUNT`` env 或强制
``--workers 1``)。

**为什么多 worker 禁**: Server 进程内 store (lease + idempotency cache)
用单 asyncio event loop 保护; 多 worker fork 后会出现 lease 状态分裂
(子进程各持一份, 资源配额不准确)。

**典型用法** (单 worker 进程内启 Server)::

    config = ClusterTokenConfig(
        cluster_token_mode=ClusterTokenMode.EMBEDDED,
        bind_address="127.0.0.1:0",  # ephemeral port OK
        auth_secret="...",
        resources=(ResourceConfig(name="/api/v1/users", max_permits=100),),
        failure_policy_per_resource={
            "/api/v1/users": ClusterFailurePolicy.FAIL_CLOSED,
        },
    )
    embedded = EmbeddedTokenServer(config)
    await embedded.start()
    try:
        # Server 在 background 跑; 业务代码用 Engine 调 acquire
        await embedded.wait_for_shutdown()
    finally:
        await embedded.stop()

**跟 ``StandaloneTokenServer`` 的区别**:

- Embedded 不接 signal handler (跟宿主进程 lifecycle 一致)
- Embedded 强制单 worker 校验 (启动 fail-fast if multi-worker)
- Embedded 不强制 bind_address (允许 ephemeral port ``bind_address="127.0.0.1:0"``)
- Embedded 跟 Engine 共享同一 event loop (M6.7 决策, 跨线程共享禁止)

**反例** (M6.3.5 决策, 跟 IMPLEMENTATION-PLAN §1.4 一致):

- ❌ 按 Uvicorn worker ordinal 选主
- ❌ leader election (etcd / redis lock)
- ❌ 服务发现猜测 owner

English
--------
Lifecycle wrapper for in-process Server. **Strict invariant**: at
startup, ``assert worker_count == 1`` (read ``SERVER_WORKER_COUNT``
env or force ``--workers 1``).

Why multi-worker forbidden: the in-process store (lease + idempotency
cache) is protected by a single asyncio event loop; multi-worker fork
yields lease state split (each child holds its own copy, quota
inconsistent).

Typical usage (in-process Server in single-worker host)::

    config = ClusterTokenConfig(
        cluster_token_mode=ClusterTokenMode.EMBEDDED,
        bind_address="127.0.0.1:0",  # ephemeral port OK
        auth_secret="...",
        resources=(ResourceConfig(name="/api/v1/users", max_permits=100),),
        failure_policy_per_resource={
            "/api/v1/users": ClusterFailurePolicy.FAIL_CLOSED,
        },
    )
    embedded = EmbeddedTokenServer(config)
    await embedded.start()
    try:
        await embedded.wait_for_shutdown()
    finally:
        await embedded.stop()

Differences from ``StandaloneTokenServer``:

- Embedded does not install signal handlers (lifecycle tied to host)
- Embedded enforces single-worker check (fail-fast on multi-worker)
- Embedded allows ephemeral port (``bind_address="127.0.0.1:0"``)
- Embedded shares Engine event loop (M6.7 decision; cross-thread
  sharing forbidden)

Anti-patterns (M6.3.5 decision, IMPLEMENTATION-PLAN §1.4):

- ❌ master selection by Uvicorn worker ordinal
- ❌ leader election (etcd / redis lock)
- ❌ owner inference via service discovery
"""

from __future__ import annotations

import asyncio
import logging
import os

from atlas_richie.sentinel.ports.token import ClusterFailurePolicy

from ..config import ClusterTokenConfig, ClusterTokenMode, ResourceConfig
from ..errors import ClusterConfigError
from .http_transport import HttpTransport
from .token_server import TokenServer

_log = logging.getLogger("atlas_richie.sentinel_cluster.embedded")


def _detect_worker_count() -> int:
    """读 ``SERVER_WORKER_COUNT`` env, 默认 1.

    Returns:
        报告的 worker 数 (单 worker 校验的输入)

    **注意**: 仅读 env, 不探测 uvicorn / gunicorn 实际 worker 状态
    (避免隐式依赖框架)。用户必须显式 export ``SERVER_WORKER_COUNT=1``
    或强制 ``--workers 1``。
    """
    raw = os.environ.get("SERVER_WORKER_COUNT", "1")
    try:
        n = int(raw)
    except ValueError as e:
        raise ClusterConfigError(
            f"SERVER_WORKER_COUNT must be int, got {raw!r}",
            code="CONFIG_ERROR",
        ) from e
    if n < 1:
        raise ClusterConfigError(
            f"SERVER_WORKER_COUNT must be >= 1, got {n}",
            code="CONFIG_ERROR",
        )
    return n


class EmbeddedTokenServer:
    """进程内 Cluster Server lifecycle wrapper (M6.3.5, 1.0 公开).

    **强约束** (启动 fail-fast):

    - ``worker_count == 1`` (读 ``SERVER_WORKER_COUNT`` env, 默认 1)
    - 多 worker 直接 fail-fast (避免 lease 状态分裂)
    - 跟宿主进程 / Engine 共享同一 event loop (跨线程共享禁止, M6.7 决策)
    """

    def __init__(self, config: ClusterTokenConfig) -> None:
        if not isinstance(config, ClusterTokenConfig):
            raise ClusterConfigError(
                "config must be ClusterTokenConfig", code="CONFIG_ERROR"
            )
        if config.cluster_token_mode is not ClusterTokenMode.EMBEDDED:
            raise ClusterConfigError(
                f"EmbeddedTokenServer requires mode=EMBEDDED, got "
                f"{config.cluster_token_mode.value}",
                code="CONFIG_ERROR",
            )
        self._config = config
        self._token_server = TokenServer(config)
        self._http_transport = HttpTransport(
            self._token_server,
            max_payload_bytes=config.max_payload_bytes,
        )
        self._shutdown_event = asyncio.Event()

    @property
    def token_server(self) -> TokenServer:
        return self._token_server

    @property
    def http_transport(self) -> HttpTransport:
        return self._http_transport

    @property
    def bound_port(self) -> int | None:
        return self._http_transport.bound_port

    async def start(self) -> None:
        """启动 Embedded Server (含单 worker 校验 + 启动 fail-fast).

        Raises:
            ClusterConfigError: 多 worker / 资源未配 / 鉴权缺 secret
        """
        # 1. 单 worker 校验 (强约束, M6.3.5 决策)
        worker_count = _detect_worker_count()
        if worker_count != 1:
            raise ClusterConfigError(
                f"Embedded Server requires worker_count==1, got {worker_count}. "
                f"Multi-worker forbidden to avoid lease state split. "
                f"Use --workers 1 or export SERVER_WORKER_COUNT=1, or switch to "
                f"StandaloneTokenServer / client_only mode.",
                code="EMBEDDED_MULTI_WORKER",
            )
        # 2. 启动 TokenServer (内部校验 resource → failure_policy)
        await self._token_server.start()
        # 3. 启动 HTTP transport (允许 ephemeral port "127.0.0.1:0")
        try:
            await self._http_transport.start(self._config.bind_address)
        except Exception:
            await self._token_server.stop()
            raise
        _log.info(
            "EmbeddedTokenServer started on %s:%d",
            self._http_transport.bound_host or "?",
            self._http_transport.bound_port or 0,
        )

    async def stop(self) -> None:
        """停止 Embedded Server."""
        await self._http_transport.stop()
        await self._token_server.stop()
        self._shutdown_event.set()

    async def wait_for_shutdown(self) -> None:
        """挂起直到 ``stop()`` 被调 (供 main task 等待)."""
        await self._shutdown_event.wait()

    def request_shutdown(self) -> None:
        """非阻塞触发 shutdown (单测 / 业务代码用)."""
        self._shutdown_event.set()


__all__ = ["EmbeddedTokenServer"]

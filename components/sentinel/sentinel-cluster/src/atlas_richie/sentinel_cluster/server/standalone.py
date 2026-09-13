"""Atlas Richie Sentinel Cluster — Standalone Server Entry Point (M6.3.5).

中文
----
独立进程入口 (``python -m atlas_richie.sentinel_cluster``), 接收 CLI
参数启动 Server。

**CLI 参数** (1.0 公开, 跟 IMPLEMENTATION-PLAN §2.5 一致):

- ``--bind 0.0.0.0:8765`` (默认)
- ``--config /path/to/config.json`` (stdlib json 描述 ``ClusterTokenConfig``)
- ``--auth-secret <secret>`` (从 CLI 显式传入, 不从 JSON 读)
- ``--shutdown-timeout 5.0`` (秒, 默认 5.0)
- ``--mode standalone`` (1.0 强制, 留扩展位)

**注意**: 不引入 ``pyyaml`` / ``toml`` (Cluster wheel 0 3rd-party);
YAML / TOML 支持留 M6.3.x future, 用户自带解析器转 dict。

**启动流程**:

1. parse CLI
2. 构造 ``ClusterTokenConfig`` (frozen, ``__post_init__`` 校验)
3. 构造 ``TokenServer`` (校验 resource 在 failure_policy_per_resource)
4. 构造 ``HttpTransport``
5. ``await token_server.start()``
6. ``await http_transport.start(bind)``
7. 等待 SIGTERM / SIGINT, 或 KeyboardInterrupt
8. graceful shutdown: ``http_transport.stop()`` → ``token_server.stop()``

**退出码**:

- 0 — 正常 SIGTERM 关闭
- 1 — 启动失败 (config / bind 错误)
- 2 — runtime 错误 (uncaught exception)

English
--------
Standalone process entry point (``python -m atlas_richie.sentinel_cluster``),
accepts CLI args to start the Server.

CLI args (1.0 public, per IMPLEMENTATION-PLAN §2.5):

- ``--bind 0.0.0.0:8765`` (default)
- ``--config /path/to/config.json`` (stdlib json for ``ClusterTokenConfig``)
- ``--auth-secret <secret>`` (CLI-only, never from JSON)
- ``--shutdown-timeout 5.0`` (seconds, default 5.0)
- ``--mode standalone`` (1.0 forces, reserved for future)

No ``pyyaml`` / ``toml`` (Cluster wheel is 0 3rd-party); YAML / TOML
deferred to M6.3.x future.

Startup flow:

1. parse CLI
2. build ``ClusterTokenConfig`` (frozen, ``__post_init__`` invariants)
3. build ``TokenServer`` (validates resource → failure_policy keys)
4. build ``HttpTransport``
5. ``await token_server.start()``
6. ``await http_transport.start(bind)``
7. wait for SIGTERM / SIGINT / KeyboardInterrupt
8. graceful shutdown: ``http_transport.stop()`` → ``token_server.stop()``

Exit codes:

- 0 — normal SIGTERM shutdown
- 1 — startup failure (config / bind)
- 2 — runtime error (uncaught exception)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import signal
import sys
from typing import Sequence

from atlas_richie.contracts.cluster.v1 import DEFAULT_LEASE_TTL_NS, ENVELOPE_MAX_SIZE_BYTES

from ..config import ClusterTokenConfig, ClusterTokenMode
from ..errors import ClusterConfigError, ClusterServerError
from .http_transport import HttpTransport
from .token_server import TokenServer

_log = logging.getLogger("atlas_richie.sentinel_cluster.standalone")


def _build_arg_parser() -> argparse.ArgumentParser:
    """构造 CLI argparse."""
    parser = argparse.ArgumentParser(
        prog="atlas-richie-sentinel-cluster",
        description=(
            "Atlas Richie Sentinel Cluster — Standalone Server (M6.3.5). "
            "Token allocation state machine over HTTP/1.1 + JSON."
        ),
    )
    parser.add_argument(
        "--bind",
        default=os.environ.get("CLUSTER_SERVER_BIND", "0.0.0.0:8765"),
        help="Bind address (host:port, default: 0.0.0.0:8765 or $CLUSTER_SERVER_BIND)",
    )
    parser.add_argument(
        "--config",
        default=os.environ.get("CLUSTER_SERVER_CONFIG", ""),
        help=(
            "Path to config JSON (stdlib json, no YAML). "
            "Defaults to $CLUSTER_SERVER_CONFIG; empty = use defaults."
        ),
    )
    parser.add_argument(
        "--auth-secret",
        default=os.environ.get("CLUSTER_SERVER_AUTH_SECRET", ""),
        help=(
            "Shared secret for X-Atlas-Cluster-Token header. "
            "Required; may come from $CLUSTER_SERVER_AUTH_SECRET. "
            "If absent from both CLI and env, startup fails (fail-fast)."
        ),
    )
    parser.add_argument(
        "--shutdown-timeout",
        type=float,
        default=float(os.environ.get("CLUSTER_SERVER_SHUTDOWN_TIMEOUT", "5.0")),
        help="Graceful shutdown timeout in seconds (default: 5.0)",
    )
    parser.add_argument(
        "--lease-ttl-ns",
        type=int,
        default=int(
            os.environ.get("CLUSTER_SERVER_LEASE_TTL_NS", str(DEFAULT_LEASE_TTL_NS))
        ),
        help=f"Lease TTL in ns (default: {DEFAULT_LEASE_TTL_NS} = 30 s)",
    )
    parser.add_argument(
        "--max-payload-bytes",
        type=int,
        default=int(
            os.environ.get("CLUSTER_SERVER_MAX_PAYLOAD_BYTES", str(ENVELOPE_MAX_SIZE_BYTES))
        ),
        help=f"Max envelope bytes (default: {ENVELOPE_MAX_SIZE_BYTES} = 8 KB)",
    )
    parser.add_argument(
        "--max-inflight",
        type=int,
        default=int(os.environ.get("CLUSTER_SERVER_MAX_INFLIGHT", "1024")),
        help="Max in-flight requests (default: 1024)",
    )
    parser.add_argument(
        "--log-level",
        default=os.environ.get("CLUSTER_SERVER_LOG_LEVEL", "INFO"),
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Log level (default: INFO)",
    )
    return parser


def _build_config_from_args(args: argparse.Namespace) -> ClusterTokenConfig:
    """从 argparse 构造 ``ClusterTokenConfig`` (1.0 公开, 内部使用)."""
    if not args.auth_secret:
        raise ClusterConfigError(
            "auth_secret is required (--auth-secret or $CLUSTER_SERVER_AUTH_SECRET)",
            code="CONFIG_ERROR",
        )
    # 1. 加载 config JSON (如果提供)
    if args.config:
        with open(args.config, "r", encoding="utf-8") as f:
            raw = f.read()
        base = ClusterTokenConfig.from_json(raw, auth_secret=args.auth_secret)
        # 2. CLI 覆盖 config JSON (CLI 优先)
        overrides: dict = {}
        if args.shutdown_timeout != 5.0:
            overrides["shutdown_timeout_s"] = args.shutdown_timeout
        if args.lease_ttl_ns != DEFAULT_LEASE_TTL_NS:
            overrides["lease_ttl_ns"] = args.lease_ttl_ns
        if args.max_payload_bytes != ENVELOPE_MAX_SIZE_BYTES:
            overrides["max_payload_bytes"] = args.max_payload_bytes
        if args.max_inflight != 1024:
            overrides["max_inflight"] = args.max_inflight
        if overrides:
            from dataclasses import replace
            base = replace(base, **overrides)
        return base
    # 3. 无 config 文件 → 用 CLI 默认; 但 resource / failure_policy 为空,
    #    启动会 fail-fast (RESOURCE_NOT_CONFIGURED) — 这是正确行为
    return ClusterTokenConfig(
        cluster_token_mode=ClusterTokenMode.STANDALONE,
        bind_address=args.bind,
        auth_secret=args.auth_secret,
        lease_ttl_ns=args.lease_ttl_ns,
        max_payload_bytes=args.max_payload_bytes,
        max_inflight=args.max_inflight,
        shutdown_timeout_s=args.shutdown_timeout,
    )


def _configure_logging(level: str) -> None:
    """配置 stderr logging (1.0 简化, 不写文件)."""
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )


async def _run_standalone(args: argparse.Namespace) -> int:
    """异步 run loop: 启动 Server + 等 signal + 优雅关闭."""
    _configure_logging(args.log_level)
    try:
        config = _build_config_from_args(args)
    except ClusterConfigError as e:
        _log.error("config error: %s", e)
        return 1
    except (OSError, json.JSONDecodeError) as e:
        _log.error("failed to load config: %s", e)
        return 1
    # 强制 standalone mode (即使 config 里写错, 也覆盖)
    if config.cluster_token_mode is not ClusterTokenMode.STANDALONE:
        _log.error(
            "standalone entry only allows mode=STANDALONE, got %s",
            config.cluster_token_mode.value,
        )
        return 1
    token_server = TokenServer(config)
    http_transport = HttpTransport(
        token_server,
        max_payload_bytes=config.max_payload_bytes,
    )
    # 启动
    try:
        await token_server.start()
    except ClusterConfigError as e:
        _log.error("server startup failed: %s", e)
        return 1
    except ClusterServerError as e:
        _log.error("server startup failed: %s", e)
        return 1
    try:
        await http_transport.start(config.bind_address)
    except (OSError, ClusterServerError, ClusterConfigError) as e:
        _log.error("http transport start failed: %s", e)
        await token_server.stop()
        return 1
    _log.info(
        "Standalone Cluster Server ready on %s:%d (mode=%s)",
        http_transport.bound_host or "?",
        http_transport.bound_port or 0,
        config.cluster_token_mode.value,
    )
    # 等 signal
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    def _signal_handler() -> None:
        _log.info("received shutdown signal")
        stop_event.set()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except (NotImplementedError, RuntimeError):  # pragma: no cover (Windows)
            pass
    try:
        await stop_event.wait()
    except asyncio.CancelledError:
        pass
    finally:
        # 优雅关闭
        _log.info("shutting down (timeout=%ss)", config.shutdown_timeout_s)
        try:
            await http_transport.stop()
        except Exception as e:  # pragma: no cover (defensive)
            _log.warning("http_transport.stop error: %s", e)
        try:
            await token_server.stop()
        except Exception as e:  # pragma: no cover (defensive)
            _log.warning("token_server.stop error: %s", e)
        _log.info("shutdown complete")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """CLI 主入口 (synchronous wrapper).

    Returns:
        进程退出码
    """
    parser = _build_arg_parser()
    args = parser.parse_args(argv)
    try:
        return asyncio.run(_run_standalone(args))
    except KeyboardInterrupt:
        _log.info("interrupted")
        return 0
    except Exception as e:  # pragma: no cover (defensive)
        _log.exception("unexpected error: %s", e)
        return 2


__all__ = ["main", "StandaloneTokenServer"]


# ---------------------------------------------------------------------------
# StandaloneTokenServer wrapper class (公开 API)
# ---------------------------------------------------------------------------


class StandaloneTokenServer:
    """Standalone Cluster Server 包装 (1.0 公开, M6.3.5).

    适用场景: 用户在 Python 代码里启 Server (非 CLI), 跟 CLI 等价,
    但用 ``start()`` / ``stop()`` coroutine 控制生命周期。

    **典型用法**::

        config = ClusterTokenConfig(
            cluster_token_mode=ClusterTokenMode.STANDALONE,
            bind_address="0.0.0.0:8765",
            auth_secret="...",
            resources=(ResourceConfig(name="/api/v1/users", max_permits=100),),
            failure_policy_per_resource={"/api/v1/users": ClusterFailurePolicy.FAIL_CLOSED},
        )
        server = StandaloneTokenServer(config)
        await server.start()
        try:
            await server.wait_for_shutdown()
        finally:
            await server.stop()

    **跟 ``TokenServer`` 的区别**:
    - ``TokenServer``: 纯状态机, 跟 HTTP transport 解耦
    - ``StandaloneTokenServer``: 含 HttpTransport + signal handling
      (CLI 路径完整封装)
    """

    def __init__(self, config: ClusterTokenConfig) -> None:
        if not isinstance(config, ClusterTokenConfig):
            raise ClusterConfigError(
                "config must be ClusterTokenConfig", code="CONFIG_ERROR"
            )
        if config.cluster_token_mode is not ClusterTokenMode.STANDALONE:
            raise ClusterConfigError(
                f"StandaloneTokenServer requires mode=STANDALONE, got "
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
        """启动 Server + HTTP transport."""
        await self._token_server.start()
        try:
            await self._http_transport.start(self._config.bind_address)
        except Exception:
            await self._token_server.stop()
            raise

    async def stop(self) -> None:
        """停止 HTTP transport + Server."""
        await self._http_transport.stop()
        await self._token_server.stop()
        self._shutdown_event.set()

    async def wait_for_shutdown(self) -> None:
        """挂起直到 ``stop()`` 被调 (含 signal handler 由 CLI 路径设置)."""
        await self._shutdown_event.wait()

    def request_shutdown(self) -> None:
        """非阻塞触发 shutdown (供 signal handler / 测试用)."""
        self._shutdown_event.set()

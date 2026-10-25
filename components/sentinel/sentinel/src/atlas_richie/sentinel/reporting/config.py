"""Atlas Richie Sentinel — Agent Reporting V1 config (M6.5.x).

中文
----
``AgentReporterConfig`` 是 frozen slots dataclass, 锁死 1.0 公开 API 字段.
启动时 fail-fast 校验 (走 ``SentinelConfigurationError`` 父类, 跟
主包 M1.1 决策一致):

- ``collector_address`` loopback 强制 (协议 §3.5)
- ``auth_token`` ≥ 16 字符
- ``outbox_max_size`` ≥ 1
- ``outbox_overflow_policy`` 必须 ``OverflowPolicy`` 3 选 1
- ``batch_max_events`` 协议强制 = 256, 不允许改
- ``batch_max_bytes`` 协议强制 = 64 KiB, 不允许改
- ``batch_send_interval_ns`` 必须 ≥ 0
- ``max_contiguous_sequence`` 必须 ≥ 0

``OverflowPolicy`` 严格 3 选 1 (显式, 无 default / auto / silent /
inherit), 跟 Mavis 治理一致.

English
--------
``AgentReporterConfig`` is a frozen slots dataclass, locking down
1.0 public API fields. Startup fail-fast validation (via the
``SentinelConfigurationError`` parent class, per M1.1 main-package
decision):

- ``collector_address`` loopback enforced (protocol §3.5)
- ``auth_token`` ≥ 16 chars
- ``outbox_max_size`` ≥ 1
- ``outbox_overflow_policy`` must be one of 3 ``OverflowPolicy`` values
- ``batch_max_events`` protocol-fixed = 256, immutable
- ``batch_max_bytes`` protocol-fixed = 64 KiB, immutable
- ``batch_send_interval_ns`` must be ≥ 0
- ``max_contiguous_sequence`` must be ≥ 0

``OverflowPolicy`` is strictly 3-of-3 (explicit, no default / auto /
silent / inherit), per Mavis governance.
"""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from enum import StrEnum

from ..errors import SentinelConfigurationError


# Protocol-fixed limits (跟协议 §3.4 / §7.1 一致, 不可改)
BATCH_MAX_EVENTS: int = 256
BATCH_MAX_BYTES: int = 64 * 1024


class OverflowPolicy(StrEnum):
    """Outbox 满时 3 选 1 显式策略 (Mavis 治理: 无 default / auto / silent).

    中文
    ----
    - ``DROP_OLDEST`` — 静默淘汰最老的 event, 增加 ``dropped_count``,
      调用方无感知
    - ``DROP_NEWEST`` — 拒绝新的 event, 抛 :class:`ReporterOverflowError`,
      调用方需 catch 处理
    - ``BLOCK_WITH_TIMEOUT`` — 阻塞直到 outbox 有空间或
      ``block_timeout_ns`` 超时, 后者抛 :class:`ReporterOverflowError`

    English
    --------
    - ``DROP_OLDEST`` — silently evict oldest event, increment
      ``dropped_count``, caller has no awareness
    - ``DROP_NEWEST`` — reject new event, raise
      :class:`ReporterOverflowError`, caller must catch
    - ``BLOCK_WITH_TIMEOUT`` — block until outbox has space or
      ``block_timeout_ns`` elapses; latter raises
      :class:`ReporterOverflowError`
    """

    DROP_OLDEST = "drop_oldest"
    DROP_NEWEST = "drop_newest"
    BLOCK_WITH_TIMEOUT = "block_with_timeout"


def _validate_loopback_address(addr: str) -> None:
    """loopback bind 强制 (协议 §3.5 跟 M6.3 实施一致).

    Raises:
        SentinelConfigurationError: 格式错 / 端口错 / 非 loopback
    """
    if not isinstance(addr, str) or ":" not in addr:
        raise SentinelConfigurationError(
            f"collector_address must be host:port, got {addr!r}",
            field="collector_address",
            reason="missing port separator",
            value=addr,
        )
    host, _, port_str = addr.rpartition(":")
    if not host or not port_str:
        raise SentinelConfigurationError(
            f"collector_address must be host:port, got {addr!r}",
            field="collector_address",
            reason="empty host or port",
            value=addr,
        )
    try:
        port = int(port_str)
    except ValueError as e:
        raise SentinelConfigurationError(
            f"collector_address port must be int, got {port_str!r}",
            field="collector_address",
            reason="port not int",
            value=addr,
        ) from e
    if not (1 <= port <= 65535):
        raise SentinelConfigurationError(
            f"collector_address port must be in [1, 65535], got {port}",
            field="collector_address",
            reason="port out of range",
            value=addr,
        )
    # loopback 强制 — 接受 127.0.0.0/8 + "localhost" / "::1" (含
    # IPv6 缩写形式 "[::1]" 跟 "::1" 都接受)
    loopback_ok = False
    # 规范化 host: 去 IPv6 brackets
    host_normalized = host
    if host.startswith("[") and host.endswith("]"):
        host_normalized = host[1:-1]
    if host_normalized == "localhost" or host_normalized == "::1":
        loopback_ok = True
    else:
        try:
            ip = ipaddress.ip_address(host_normalized)
            if ip.is_loopback:
                loopback_ok = True
        except ValueError:
            pass
    if not loopback_ok:
        raise SentinelConfigurationError(
            f"collector_address host must be loopback (127.0.0.0/8 or ::1 or localhost), "
            f"got {host!r} (protocol §3.5 + M6.3 实施: TLS 不支持, 仅 loopback)",
            field="collector_address",
            reason="non-loopback host rejected",
            value=addr,
        )
    # 进一步校验 DNS 解析 (本地解析, 不联网, 避免 hostname typo)
    try:
        resolved = socket.getaddrinfo(host_normalized, port, type=socket.SOCK_STREAM)
        if not resolved:
            raise SentinelConfigurationError(
                f"collector_address host {host_normalized!r} does not resolve",
                field="collector_address",
                reason="DNS resolution failed",
                value=addr,
            )
    except socket.gaierror as e:
        raise SentinelConfigurationError(
            f"collector_address host {host_normalized!r} does not resolve: {e}",
            field="collector_address",
            reason="DNS resolution failed",
            value=addr,
        ) from e


@dataclass(slots=True, frozen=True)
class AgentReporterConfig:
    """Agent Reporter 1.0 公开配置 (frozen slots dataclass).

    中文
    ----
    字段语义详见 § M6.5.1 + 协议 spec; 这里只列 wire/行为约束.

    - ``collector_address``: loopback 强制, e.g. ``"127.0.0.1:8765"``
    - ``auth_token``: ≥ 16 字符 (跟 Mavis 决策 + 协议 §5.1 一致)
    - ``instance_id_persistence_path``: 可选 startup_epoch 持久化路径,
      None 表示进程内 (重启后 startup_epoch 重新生成, 协议允许
      Server 识别为新 instance)
    - ``outbox_max_size``: ≥ 1, 默认 10000
    - ``outbox_overflow_policy``: 3 选 1 显式
    - ``batch_max_events``: 协议强制 = 256, 不可改
    - ``batch_max_bytes``: 协议强制 = 64 * 1024, 不可改
    - ``batch_send_interval_ns``: 默认 100ms (100_000_000 ns), 跟
      M6.1.7 Nacos 1s polling 不冲突 (Mavis 决策)
    - ``max_contiguous_sequence``: ≥ 0, Reporter 内部状态, 0 表示新
      startup (无 ack 过任何 batch)
    - ``connect_timeout_ns``: 5s (5_000_000_000 ns)
    - ``request_timeout_ns``: 5s (5_000_000_000 ns)
    - ``reconnect_initial_ns``: 100ms (100_000_000 ns)
    - ``reconnect_max_ns``: 30s (30_000_000_000 ns)
    - ``reconnect_jitter_ns``: 50ms (50_000_000 ns), exponential
      backoff 抖动

    ``__post_init__`` 触发 fail-fast 校验 (跟 Mavis 治理一致: 构造
    时即 fail-fast, 而不是构造后由调用方校验). 校验失败抛
    :class:`SentinelConfigurationError` (主包根 ``SentinelError`` 子类).

    English
    --------
    Field semantics: see M6.5.1 + protocol spec; here only wire/behavior
    constraints are listed.

    ``__post_init__`` triggers fail-fast validation (per Mavis
    governance: fail-fast at construction, not by caller after).
    Raises :class:`SentinelConfigurationError` (subclass of main
    root ``SentinelError``) on validation failure.
    """

    collector_address: str
    auth_token: str
    instance_id_persistence_path: str | None
    outbox_max_size: int
    outbox_overflow_policy: OverflowPolicy
    batch_max_events: int
    batch_max_bytes: int
    batch_send_interval_ns: int
    max_contiguous_sequence: int
    connect_timeout_ns: int
    request_timeout_ns: int
    reconnect_initial_ns: int
    reconnect_max_ns: int
    reconnect_jitter_ns: int

    def __post_init__(self) -> None:
        # 构造时 fail-fast 校验 (Mavis 治理)
        validate_config(self)


def validate_config(config: AgentReporterConfig) -> None:
    """``AgentReporterConfig`` 启动 fail-fast 校验.

    中文
    ----
    全部 14 字段 + collector_address 强校验 (DNS 解析 + loopback).
    失败抛 ``SentinelConfigurationError`` (主包根 ``SentinelError``
    子类, 1.x 兼容入口).

    English
    --------
    All 14 fields + collector_address hard validation (DNS resolution
    + loopback). Raises ``SentinelConfigurationError`` (subclass of
    main-package root ``SentinelError``; 1.x compatible entry).
    """
    if not isinstance(config, AgentReporterConfig):
        raise SentinelConfigurationError(
            f"config must be AgentReporterConfig, got {type(config).__name__}",
            field="config",
            reason="type mismatch",
            value=type(config).__name__,
        )
    # 1. collector_address
    _validate_loopback_address(config.collector_address)
    # 2. auth_token ≥ 16 字符 (跟 Mavis 决策 + 协议 §5.1)
    if not isinstance(config.auth_token, str) or len(config.auth_token) < 16:
        raise SentinelConfigurationError(
            f"auth_token must be string ≥ 16 chars, got len={len(config.auth_token or '')}",
            field="auth_token",
            reason="auth_token too short (Mavis 决策 ≥ 16)",
            value=(
                f"<{len(config.auth_token)} chars>" if config.auth_token else "<empty>"
            ),
        )
    # 3. instance_id_persistence_path 允许 None, 字符串或 None
    if config.instance_id_persistence_path is not None and not isinstance(
        config.instance_id_persistence_path, str
    ):
        raise SentinelConfigurationError(
            f"instance_id_persistence_path must be str or None, "
            f"got {type(config.instance_id_persistence_path).__name__}",
            field="instance_id_persistence_path",
            reason="type mismatch",
            value=type(config.instance_id_persistence_path).__name__,
        )
    # 4. outbox_max_size ≥ 1
    if not isinstance(config.outbox_max_size, int) or config.outbox_max_size < 1:
        raise SentinelConfigurationError(
            f"outbox_max_size must be int ≥ 1, got {config.outbox_max_size!r}",
            field="outbox_max_size",
            reason="must be ≥ 1",
            value=config.outbox_max_size,
        )
    # 5. outbox_overflow_policy 枚举
    if not isinstance(config.outbox_overflow_policy, OverflowPolicy):
        raise SentinelConfigurationError(
            f"outbox_overflow_policy must be OverflowPolicy, "
            f"got {type(config.outbox_overflow_policy).__name__}",
            field="outbox_overflow_policy",
            reason="type mismatch",
            value=type(config.outbox_overflow_policy).__name__,
        )
    # 6. batch_max_events 协议强制 = 256
    if config.batch_max_events != BATCH_MAX_EVENTS:
        raise SentinelConfigurationError(
            f"batch_max_events protocol-fixed = {BATCH_MAX_EVENTS}, "
            f"got {config.batch_max_events}",
            field="batch_max_events",
            reason="protocol-fixed",
            value=config.batch_max_events,
        )
    # 7. batch_max_bytes 协议强制 = 64 * 1024
    if config.batch_max_bytes != BATCH_MAX_BYTES:
        raise SentinelConfigurationError(
            f"batch_max_bytes protocol-fixed = {BATCH_MAX_BYTES}, "
            f"got {config.batch_max_bytes}",
            field="batch_max_bytes",
            reason="protocol-fixed",
            value=config.batch_max_bytes,
        )
    # 8. batch_send_interval_ns ≥ 0
    if (
        not isinstance(config.batch_send_interval_ns, int)
        or config.batch_send_interval_ns < 0
    ):
        raise SentinelConfigurationError(
            f"batch_send_interval_ns must be int ≥ 0, "
            f"got {config.batch_send_interval_ns!r}",
            field="batch_send_interval_ns",
            reason="must be ≥ 0",
            value=config.batch_send_interval_ns,
        )
    # 9. max_contiguous_sequence ≥ 0
    if (
        not isinstance(config.max_contiguous_sequence, int)
        or config.max_contiguous_sequence < 0
    ):
        raise SentinelConfigurationError(
            f"max_contiguous_sequence must be int ≥ 0, "
            f"got {config.max_contiguous_sequence!r}",
            field="max_contiguous_sequence",
            reason="must be ≥ 0",
            value=config.max_contiguous_sequence,
        )
    # 10-14. timeout / reconnect 字段 ≥ 0
    for field_name in (
        "connect_timeout_ns",
        "request_timeout_ns",
        "reconnect_initial_ns",
        "reconnect_max_ns",
        "reconnect_jitter_ns",
    ):
        v = getattr(config, field_name)
        if not isinstance(v, int) or v < 0:
            raise SentinelConfigurationError(
                f"{field_name} must be int ≥ 0, got {v!r}",
                field=field_name,
                reason="must be ≥ 0",
                value=v,
            )
    # reconnect_max ≥ reconnect_initial
    if config.reconnect_max_ns < config.reconnect_initial_ns:
        raise SentinelConfigurationError(
            f"reconnect_max_ns ({config.reconnect_max_ns}) must be ≥ "
            f"reconnect_initial_ns ({config.reconnect_initial_ns})",
            field="reconnect_max_ns",
            reason="max < initial",
            value=config.reconnect_max_ns,
        )


__all__ = [
    "BATCH_MAX_BYTES",
    "BATCH_MAX_EVENTS",
    "AgentReporterConfig",
    "OverflowPolicy",
    "validate_config",
]

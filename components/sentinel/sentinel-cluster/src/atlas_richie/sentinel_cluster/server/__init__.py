"""Atlas Richie Sentinel Cluster — Server 端公开 API (M6.3.3 + M6.3.5).

中文
----
Server 端 (sentinel-cluster wheel) 1.0 公开 API surface。

**导出** (1.0 公开, 跟 IMPLEMENTATION-PLAN §2.3 一致):

- ``TokenServer`` — 状态机 (acquire / release / renew / lease expiry / fencing)
- ``TokenServerState`` — 状态枚举
- ``TokenServerStats`` — 运行时统计 snapshot
- ``StandaloneTokenServer`` — 独立进程 wrapper
- ``EmbeddedTokenServer`` — 进程内 wrapper (单 worker 强约束)
- ``HttpTransport`` — HTTP/1.1 + JSON 传输层
- ``LeaseStore`` — 进程内 lease + 配额 store
- ``Lease`` — Server 生成的 opaque lease 句柄
- ``IdempotencyCache`` — request_id 短期 cache (5 min TTL)

**不导出** (1.0 内部, 显式不暴露):

- 私有 helper / ``_ResourceState`` / epoch_index 内部结构
- ``_envelope_to_cached`` / ``_envelope_from_cached`` 序列化 helper
- 内部 lock / scrub task 引用

**M6.3.5 决策** (3 种启动形态):

- ``StandaloneTokenServer`` — 独立进程 (含 signal handler)
- ``EmbeddedTokenServer`` — 进程内 (单 worker 强约束, M6.3.5 fail-fast)
- ``ClientOnly`` (留 Worker 2 M6.3.4 实施) — 永远只连外部 Server

English
--------
Server-side (sentinel-cluster wheel) 1.0 public API surface.

Exports (1.0 public, per IMPLEMENTATION-PLAN §2.3):

- ``TokenServer`` — state machine (acquire / release / renew / lease expiry / fencing)
- ``TokenServerState`` — state enum
- ``TokenServerStats`` — runtime stats snapshot
- ``StandaloneTokenServer`` — standalone process wrapper
- ``EmbeddedTokenServer`` — in-process wrapper (single-worker strict)
- ``HttpTransport`` — HTTP/1.1 + JSON transport
- ``LeaseStore`` — in-process lease + quota store
- ``Lease`` — Server-generated opaque lease handle
- ``IdempotencyCache`` — request_id short-term cache (5 min TTL)

Not exported (1.0 internal, explicitly not exposed):

- private helpers / ``_ResourceState`` / epoch_index internals
- ``_envelope_to_cached`` / ``_envelope_from_cached`` serialization helpers
- internal lock / scrub task references
"""

from __future__ import annotations

from .embedded import EmbeddedTokenServer
from .http_transport import HttpTransport
from .idempotency_cache import CacheEntry, IdempotencyCache
from .lease_store import Lease, LeaseStore, epoch_key
from .standalone import StandaloneTokenServer, main
from .token_server import TokenServer, TokenServerState, TokenServerStats

__all__ = [
    # 1.0 公开 API
    "TokenServer",
    "TokenServerState",
    "TokenServerStats",
    "StandaloneTokenServer",
    "EmbeddedTokenServer",
    "HttpTransport",
    "LeaseStore",
    "Lease",
    "IdempotencyCache",
    "CacheEntry",
    "epoch_key",
    # CLI 入口 (sentinel-cluster standalone)
    "main",
]

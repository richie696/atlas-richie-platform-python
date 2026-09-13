"""Atlas Richie Agent Reporting Protocol V1 — ingress envelope (7 字段).

1:1 镜像 ``docs/protocol/上报协议-01-envelope-v1.md`` §3.

V1 协议 BUG 收口 (richie696 2026-09-13) 关键变更:
- 8 字段 → 7 字段 (移除 ``received_at``)
- ``received_at`` 只由 Collector 在 Ack / 持久化投影写入, 不是 ingress 字段
- Reporter 不得猜测 / 写入 / 回传 ``received_at``

DRAFT, 待 5-owner sign-off + 跨语言合同测试通过后冻结.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Protocol version 固定值 (协议 §4.1)
PROTOCOL_VERSION = "atlas-richie.reporting/v1"

# 大小限制 (协议 §3.4)
ENVELOPE_MAX_SIZE_BYTES = 16 * 1024  # 16 KiB

# int64 范围 (协议 §2: 0 ~ 2^53-1, JavaScript 安全整数)
INT64_MIN = 0
INT64_MAX = 2**53 - 1

# ISO 8601 UTC microsecond 格式
ISO_8601_UTC_MICRO = "%Y-%m-%dT%H:%M:%S.%fZ"

# UUID v4 8-4-4-4-12 hex
UUID_V4_REGEX = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"


@dataclass(frozen=True, slots=True)
class ReportingEnvelope:
    """Agent Reporting Protocol V1 — ingress envelope (7 字段, DRAFT).

    字段定义见 ``docs/protocol/上报协议-01-envelope-v1.md`` §3.2.
    """

    protocol_version: str
    event_kind: str  # ReportingEventKind value
    event_payload: dict[str, Any]
    instance_id: str  # UUID v4, 同一 Reporter 跨重启保持不变
    startup_epoch: int  # int64, 跨重启持久化 + 严格递增 + 不得复用
    sequence: int  # int64, 按 (instance_id, startup_epoch) 单调递增, 从 1 开始
    captured_at: str  # ISO 8601 UTC microsecond, Reporter 本地 UTC (仅诊断)


__all__ = [
    "ENVELOPE_MAX_SIZE_BYTES",
    "INT64_MAX",
    "INT64_MIN",
    "ISO_8601_UTC_MICRO",
    "PROTOCOL_VERSION",
    "ReportingEnvelope",
    "UUID_V4_REGEX",
]

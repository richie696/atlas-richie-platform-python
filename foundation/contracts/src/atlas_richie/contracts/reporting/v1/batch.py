"""Atlas Richie Agent Reporting Protocol V1 — batch + ack + error envelope frozen dataclasses.

1:1 镜像 ``docs/protocol/上报协议-02-transport-v1.md``:
- ``ReportingBatch`` (8 字段, §7.1)
- ``AckEnvelope`` + ``AckSequence`` (5 + 3 字段, §9.1 / §9.2)
- ``ErrorEnvelope`` + ``ErrorDetails`` (协议 transport §6)

DRAFT, 待 5-owner sign-off + 跨语言合同测试通过后冻结.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# 大小限制 (协议 §3.4 / §7.3)
BATCH_MAX_SIZE_BYTES = 64 * 1024     # 64 KiB
BATCH_MAX_EVENTS = 256                # 单 batch 最多 256 envelopes

# 鉴权 HTTP header (协议 §5.1)
X_ATLAS_REPORTING_TOKEN_HEADER = "X-Atlas-Reporting-Token"

# 鉴权 key 长度下限 (避免空 key 配置错误)
AUTH_TOKEN_MIN_LEN = 16

# 错误 message 长度上限
ERROR_MESSAGE_MAX_LEN = 1024


@dataclass(frozen=True, slots=True)
class ReportingBatch:
    """Agent Reporting Protocol V1 — batch (8 字段, 协议 §7.1).

    强制单一 identity/generation, 禁止混装 (协议 §7.2):
    所有 event 的 ``protocol_version`` / ``instance_id`` / ``startup_epoch``
    必须与 batch 同值; 任一不一致, Collector 以 ``MALFORMED_ENVELOPE``
    原子拒绝.
    """

    protocol_version: str
    instance_id: str  # UUID v4
    startup_epoch: int  # int64
    batch_id: str  # UUID v4, 每 batch 唯一, 不用于去重
    sent_at: str  # ISO 8601 UTC microsecond
    events: list[Any]  # 1 ≤ length ≤ 256 ReportingEnvelope 实例
    dropped_count: int  # int64, ≥ 0


@dataclass(frozen=True, slots=True)
class AckSequence:
    """Ack 单条 sequence 信息 (协议 §9.1 / §9.2)."""

    instance_id: str
    startup_epoch: int
    max_contiguous_sequence: int  # int64


@dataclass(frozen=True, slots=True)
class AckEnvelope:
    """Ack envelope (协议 §9.1, 5 字段).

    ``received_at`` 由 Collector 写入, 是唯一 server-authoritative 时间字段.
    Reporter 不得猜测 / 写入 / 回传该值.
    """

    protocol_version: str
    batch_id: str
    received_at: str  # ISO 8601 UTC microsecond, Collector 写入
    ack_sequences: list[AckSequence]  # length 必须为 1
    duplicate_count: int  # int64


@dataclass(frozen=True, slots=True)
class ErrorDetails:
    """Error envelope ``details`` 对象 (协议 transport §6 末尾示例).

    字段全部可选; 实际字段依赖 error_code.
    """

    field: str | None = None
    got_type: str | None = None


@dataclass(frozen=True, slots=True)
class ErrorEnvelope:
    """Error envelope (协议 transport §6).

    所有校验失败**整个 batch 原子拒绝**; V1 不支持 per-event disposition.
    """

    protocol_version: str
    error_code: str  # ReportingErrorCode value
    message: str = ""
    details: ErrorDetails | None = None


__all__ = [
    "AUTH_TOKEN_MIN_LEN",
    "AckEnvelope",
    "AckSequence",
    "BATCH_MAX_EVENTS",
    "BATCH_MAX_SIZE_BYTES",
    "ERROR_MESSAGE_MAX_LEN",
    "ErrorDetails",
    "ErrorEnvelope",
    "ReportingBatch",
    "X_ATLAS_REPORTING_TOKEN_HEADER",
]

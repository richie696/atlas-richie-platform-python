"""Atlas Richie Agent Reporting Protocol V1 — Python 投影 (DRAFT).

1:1 镜像 ``docs/protocol/上报协议-01-envelope-v1.md`` + ``上报协议-02-transport-v1.md`` +
``上报协议-03-freeze-v1.md`` (DRAFT, 待 5-owner sign-off + 跨语言合同测试通过后冻结).

V1 协议 BUG 收口 (richie696 2026-09-13) 关键变更:
- ingress envelope 7 字段 (无 ``received_at``, 由 Collector 在 Ack /
  持久化投影写入)
- ``startup_epoch`` 跨重启持久化 + 严格递增 + 不得复用
- V1 单 sender 严格 FIFO + 连续 sequence + 精确重传 +
  ``max_contiguous_sequence`` + 去重逻辑一致
- 错误 batch 原子拒绝 + Ack 用 ``duplicate_count`` (无 per-event disposition)
- 11 错误码 (新增 ``ENVELOPE_TOO_LARGE`` / ``BATCH_TOO_LARGE``)
- ReasonClass 7 冻结值
- Health "无有效规则快照" 3 rule_version_* 字段成组可选
- batch 强制单一 identity/generation, 禁止混装
- V1 Collector 强制 loopback bind, 统一鉴权 Header
  ``X-Atlas-Reporting-Token``

设计:
- 全部 frozen dataclass + StrEnum, 0 3rd-party 依赖
- 严格 JSON codec (拒绝未知 field / 类型错 / 超 size / 枚举不合法 /
  batch 混装 / sequence 不一致)
- 配套 sentinel + 未来 collector SDK 用, 不在主包

English
--------
Atlas Richie Agent Reporting Protocol V1 — Python projection (DRAFT).
"""

from .batch import (
    AUTH_TOKEN_MIN_LEN,
    AckEnvelope,
    AckSequence,
    BATCH_MAX_EVENTS,
    BATCH_MAX_SIZE_BYTES,
    ErrorDetails,
    ErrorEnvelope,
    ReportingBatch,
    X_ATLAS_REPORTING_TOKEN_HEADER,
)
from .codec import (
    ReportingProtocolError,
    decode_ack,
    decode_batch,
    decode_envelope,
    decode_error_envelope,
    encode_ack,
    encode_batch,
    encode_envelope,
    encode_error_envelope,
    validate_payload,
)
from .envelope import (
    ENVELOPE_MAX_SIZE_BYTES,
    INT64_MAX,
    INT64_MIN,
    ISO_8601_UTC_MICRO,
    PROTOCOL_VERSION,
    ReportingEnvelope,
    UUID_V4_REGEX,
)
from .error_codes import ReportingErrorCode
from .event_kind import (
    ExecResult,
    HealthClass,
    ReasonClass,
    ReportingEventKind,
)
from .payloads import (
    REASON_MESSAGE_MAX_LEN,
    RULE_ID_MAX_LEN,
    RULE_VERSION_CHECKSUM_HEX_LEN,
    RULE_VERSION_CHECKSUM_PREFIX,
    RuleExecPayload,
    RuleSourceActivatedPayload,
    RuleSourceHealthPayload,
    SOURCE_ID_MAX_LEN,
)

__all__ = [
    "AUTH_TOKEN_MIN_LEN",
    "AckEnvelope",
    "AckSequence",
    "BATCH_MAX_EVENTS",
    "BATCH_MAX_SIZE_BYTES",
    "ENVELOPE_MAX_SIZE_BYTES",
    "ERROR_MESSAGE_MAX_LEN",
    "ErrorDetails",
    "ErrorEnvelope",
    "ExecResult",
    "HealthClass",
    "INT64_MAX",
    "INT64_MIN",
    "ISO_8601_UTC_MICRO",
    "PROTOCOL_VERSION",
    "REASON_MESSAGE_MAX_LEN",
    "RULE_ID_MAX_LEN",
    "RULE_VERSION_CHECKSUM_HEX_LEN",
    "RULE_VERSION_CHECKSUM_PREFIX",
    "ReasonClass",
    "ReportingBatch",
    "ReportingEnvelope",
    "ReportingErrorCode",
    "ReportingEventKind",
    "ReportingProtocolError",
    "RuleExecPayload",
    "RuleSourceActivatedPayload",
    "RuleSourceHealthPayload",
    "SOURCE_ID_MAX_LEN",
    "UUID_V4_REGEX",
    "X_ATLAS_REPORTING_TOKEN_HEADER",
    "decode_ack",
    "decode_batch",
    "decode_envelope",
    "decode_error_envelope",
    "encode_ack",
    "encode_batch",
    "encode_envelope",
    "encode_error_envelope",
    "validate_payload",
]

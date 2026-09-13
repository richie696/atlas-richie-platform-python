"""Atlas Richie Agent Reporting Protocol V1 — Python 投影.

1:1 镜像 ``docs/protocols/AGENT_REPORTING_PROTOCOL.md`` (V1 frozen). 任何
变更走 V1.1 minor + ADR, V2 major 破坏兼容.

设计:
- 全部 frozen dataclass + StrEnum, 0 3rd-party 依赖
- 严格 JSON codec (拒绝未知 field / 类型错 / 超 size / 枚举值不合法)
- 配套 sentinel + 未来 collector SDK 用, 不在主包

English
--------
Atlas Richie Agent Reporting Protocol V1 — Python projection.

1:1 mirror of the V1-frozen wire schema. All public types are frozen
dataclasses or StrEnum. The strict codec rejects unknown fields, type
errors, oversized envelopes, and out-of-enum values.
"""

from .codec import (
    ENVELOPE_MAX_SIZE_BYTES,
    PROTOCOL_VERSION,
    ReportingErrorCode,
    ReportingProtocolError,
    decode_envelope,
    encode_envelope,
    validate_payload,
)
from .envelope import ReportingEnvelope
from .event_kind import ReportingEventKind
from .payloads import (
    EXEC_RESULT_VALUES,
    HEALTH_CLASS_VALUES,
    REASON_MESSAGE_MAX_LEN,
    RULE_ID_MAX_LEN,
    SOURCE_ID_MAX_LEN,
    RuleExecPayload,
    RuleSourceActivatedPayload,
    RuleSourceHealthPayload,
)

__all__ = [
    "ENVELOPE_MAX_SIZE_BYTES",
    "EXEC_RESULT_VALUES",
    "HEALTH_CLASS_VALUES",
    "PROTOCOL_VERSION",
    "REASON_MESSAGE_MAX_LEN",
    "RULE_ID_MAX_LEN",
    "ReportingEnvelope",
    "ReportingErrorCode",
    "ReportingEventKind",
    "ReportingProtocolError",
    "RuleExecPayload",
    "RuleSourceActivatedPayload",
    "RuleSourceHealthPayload",
    "decode_envelope",
    "encode_envelope",
    "validate_payload",
]

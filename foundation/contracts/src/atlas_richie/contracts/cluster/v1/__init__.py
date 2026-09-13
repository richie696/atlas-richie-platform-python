"""Atlas Richie Cluster Token Protocol V1 — Python 投影.

1:1 镜像 ``docs/protocols/CLUSTER_TOKEN_PROTOCOL.md`` (V1 frozen). 任何
变更走 V1.1 minor + ADR, V2 major 破坏兼容.

设计:
- 全部 frozen dataclass + StrEnum, 0 3rd-party 依赖
- 严格 JSON codec (拒绝未知 field / 类型错 / 超 size / 枚举值不合法)
- 配套 sentinel-cluster wheel 用, 不在主包

English
--------
Atlas Richie Cluster Token Protocol V1 — Python projection.

1:1 mirror of the V1-frozen wire schema. All public types are frozen
dataclasses or StrEnum. The strict codec rejects unknown fields, type
errors, oversized envelopes, and out-of-enum values.
"""

from .codec import (
    ClusterProtocolError,
    decode_envelope,
    encode_envelope,
    validate_payload,
)
from .deny_reasons import ClusterDenyReason
from .envelope import ClusterTokenEnvelope
from .error_codes import ClusterErrorCode
from .message_kind import ClusterMessageKind
from .payloads import (
    DEFAULT_LEASE_TTL_NS,
    ENVELOPE_MAX_SIZE_BYTES,
    ERROR_MESSAGE_MAX_LEN,
    IDEMPOTENCY_CACHE_TTL_NS,
    ISO_8601_UTC_MICRO,
    PROTOCOL_VERSION,
    RESOURCE_MAX_LEN,
    AcquireRequestPayload,
    AcquireResponsePayload,
    ErrorResponsePayload,
    ReleaseRequestPayload,
    RenewRequestPayload,
    RenewResponsePayload,
)

__all__ = [
    "AcquireRequestPayload",
    "AcquireResponsePayload",
    "ClusterDenyReason",
    "ClusterErrorCode",
    "ClusterMessageKind",
    "ClusterProtocolError",
    "ClusterTokenEnvelope",
    "DEFAULT_LEASE_TTL_NS",
    "ENVELOPE_MAX_SIZE_BYTES",
    "ERROR_MESSAGE_MAX_LEN",
    "ErrorResponsePayload",
    "IDEMPOTENCY_CACHE_TTL_NS",
    "ISO_8601_UTC_MICRO",
    "PROTOCOL_VERSION",
    "ReleaseRequestPayload",
    "RenewRequestPayload",
    "RenewResponsePayload",
    "RESOURCE_MAX_LEN",
    "decode_envelope",
    "encode_envelope",
    "validate_payload",
]

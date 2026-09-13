"""Atlas Richie Cluster Token Protocol V1 — payload frozen dataclasses.

1:1 镜像 ``docs/protocols/CLUSTER_TOKEN_PROTOCOL.md`` §4. 6 个 payload:
- AcquireRequestPayload
- AcquireResponsePayload
- ReleaseRequestPayload
- RenewRequestPayload
- RenewResponsePayload
- ErrorResponsePayload

V1 frozen, 字段名/类型/必填属性不可改. 任何变更走 V1.1 minor + ADR (V2 major
破坏兼容).

注意: 字段顺序不保证, JSON encoder / decoder 按 key 处理. 时间字段为
ISO 8601 UTC microsecond 字符串 (``str``), 跨语言时区序列化稳定.
"""

from __future__ import annotations

from dataclasses import dataclass

from .deny_reasons import ClusterDenyReason
from .error_codes import ClusterErrorCode

# Rule version checksum 固定前缀 + 64 hex chars (协议 §4.1)
RULE_VERSION_CHECKSUM_PREFIX = "sha256:"
RULE_VERSION_CHECKSUM_HEX_LEN = 64

# lease_id 格式: UUID v4 (协议 §4.2)
LEASE_ID_FORMAT = "uuid-v4"

# 时间字段: ISO 8601 UTC microsecond, ``YYYY-MM-DDTHH:MM:SS.ffffffZ`` (协议 §3.3)
ISO_8601_UTC_MICRO = "%Y-%m-%dT%H:%M:%S.%fZ"

# instance_id / request_id: UUID v4 (协议 §3.2)
INSTANCE_ID_FORMAT = "uuid-v4"
REQUEST_ID_FORMAT = "uuid-v4"

# resource 长度上限 (协议 §3.2)
RESOURCE_MAX_LEN = 256

# error_message 脱敏 reason 上限 (协议 §4.6)
ERROR_MESSAGE_MAX_LEN = 64

# envelope size 上限 (协议 §3.4)
ENVELOPE_MAX_SIZE_BYTES = 8 * 1024

# protocol_version 固定值 (协议 §3.2)
PROTOCOL_VERSION = "atlas-richie.cluster.token/v1"

# 默认 lease TTL (协议 §5.2 + design §1.2)
DEFAULT_LEASE_TTL_NS = 30 * 1_000_000_000  # 30 s

# idempotency cache TTL (协议 §5.1 + design §1.2)
IDEMPOTENCY_CACHE_TTL_NS = 5 * 60 * 1_000_000_000  # 5 min


@dataclass(frozen=True, slots=True)
class AcquireRequestPayload:
    """``ACQUIRE_REQUEST`` payload (协议 §4.1)."""

    rule_version_epoch: int
    rule_version_revision: int
    rule_version_checksum: str
    priority: int = 0


@dataclass(frozen=True, slots=True)
class AcquireResponsePayload:
    """``ACQUIRE_RESPONSE`` payload (协议 §4.2)."""

    decision: str  # V1: "REMOTE_GRANTED" | "DENIED"
    lease_id: str | None
    lease_expires_at: str | None  # ISO 8601 UTC
    permits_granted: float | None
    retry_after_ns: int
    deny_reason: str | None  # ClusterDenyReason value or None


@dataclass(frozen=True, slots=True)
class ReleaseRequestPayload:
    """``RELEASE_REQUEST`` payload (协议 §4.3)."""

    lease_id: str
    permits_released: float


@dataclass(frozen=True, slots=True)
class RenewRequestPayload:
    """``RENEW_REQUEST`` payload (协议 §4.4)."""

    lease_id: str
    extends_for_ns: int


@dataclass(frozen=True, slots=True)
class RenewResponsePayload:
    """``RENEW_RESPONSE`` payload (协议 §4.5).

    跟 ``AcquireResponsePayload`` 同 schema, decision 允许
    ``"RENEWED"`` / ``"DENIED"``.
    """

    decision: str  # V1: "RENEWED" | "DENIED"
    lease_id: str | None
    lease_expires_at: str | None  # ISO 8601 UTC
    permits_granted: float | None
    retry_after_ns: int
    deny_reason: str | None


@dataclass(frozen=True, slots=True)
class ErrorResponsePayload:
    """``ERROR_RESPONSE`` payload (协议 §4.6)."""

    error_code: ClusterErrorCode
    error_message: str = ""


__all__ = [
    "AcquireRequestPayload",
    "AcquireResponsePayload",
    "ReleaseRequestPayload",
    "RenewRequestPayload",
    "RenewResponsePayload",
    "ErrorResponsePayload",
    "DEFAULT_LEASE_TTL_NS",
    "ENVELOPE_MAX_SIZE_BYTES",
    "ERROR_MESSAGE_MAX_LEN",
    "IDEMPOTENCY_CACHE_TTL_NS",
    "ISO_8601_UTC_MICRO",
    "PROTOCOL_VERSION",
    "RESOURCE_MAX_LEN",
    "RULE_VERSION_CHECKSUM_HEX_LEN",
    "RULE_VERSION_CHECKSUM_PREFIX",
]

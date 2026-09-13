"""Atlas Richie Cluster Token Protocol V1 — JSON codec (strict).

严格 JSON 序列化 / 反序列化, 拒绝:
- 未知 field (V1 frozen, 不宽容)
- 缺必填 field
- ``message_kind`` / ``error_code`` / ``deny_reason`` 不在 V1 枚举
- ``protocol_version`` ≠ ``"atlas-richie.cluster.token/v1"``
- envelope size > 8 KB (协议 §3.4)
- 时间字段不符合 ISO 8601 UTC microsecond
- UUID 字段不符合 8-4-4-4-12 格式

参考: ``docs/protocols/CLUSTER_TOKEN_PROTOCOL.md`` §3 + §4 + §6.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from .deny_reasons import ClusterDenyReason
from .envelope import ClusterTokenEnvelope
from .error_codes import ClusterErrorCode
from .message_kind import ClusterMessageKind
from .payloads import (
    ENVELOPE_MAX_SIZE_BYTES,
    ERROR_MESSAGE_MAX_LEN,
    PROTOCOL_VERSION,
    RESOURCE_MAX_LEN,
    RULE_VERSION_CHECKSUM_HEX_LEN,
    RULE_VERSION_CHECKSUM_PREFIX,
)

# 必填 envelope 字段 (协议 §3.2)
_REQUIRED_ENVELOPE_FIELDS: frozenset[str] = frozenset({
    "protocol_version",
    "message_kind",
    "request_id",
    "instance_id",
    "startup_epoch",
    "resource",
    "permits",
    "deadline_ns",
    "client_requested_at",
    "server_received_at",
    "payload",
})

# UUID v4 8-4-4-4-12 hex (lowercase, 协议 §3.3)
_UUID_V4_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)

# ISO 8601 UTC microsecond 格式 (协议 §3.3)
_ISO_8601_UTC_MICRO_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$"
)

# rule_version_checksum 格式: ``sha256:`` + 64 hex chars (协议 §4.1)
_RULE_VERSION_CHECKSUM_RE = re.compile(
    r"^sha256:[0-9a-f]{64}$"
)


class ClusterProtocolError(ValueError):
    """Cluster Token Protocol V1 — 严格 codec 抛错 (含错误码)."""

    def __init__(self, code: ClusterErrorCode, message: str) -> None:
        super().__init__(f"[{code.value}] {message}")
        self.code = code
        self.message = message


def _validate_uuid(field: str, value: str) -> None:
    if not isinstance(value, str) or not _UUID_V4_RE.match(value):
        raise ClusterProtocolError(
            ClusterErrorCode.MALFORMED_ENVELOPE,
            f"{field} must be UUID v4 (8-4-4-4-12 lowercase hex)",
        )


def _validate_iso_utc_micro(field: str, value: Any) -> None:
    if not isinstance(value, str) or not _ISO_8601_UTC_MICRO_RE.match(value):
        raise ClusterProtocolError(
            ClusterErrorCode.MALFORMED_ENVELOPE,
            f"{field} must be ISO 8601 UTC microsecond (YYYY-MM-DDTHH:MM:SS.ffffffZ)",
        )


def _validate_envelope_dict(obj: dict[str, Any]) -> None:
    # 1. 必填字段齐全
    missing = _REQUIRED_ENVELOPE_FIELDS - set(obj.keys())
    if missing:
        raise ClusterProtocolError(
            ClusterErrorCode.MALFORMED_ENVELOPE,
            f"missing required fields: {sorted(missing)}",
        )
    # 2. 严格不允许未知字段 (V1 frozen)
    unknown = set(obj.keys()) - _REQUIRED_ENVELOPE_FIELDS
    if unknown:
        raise ClusterProtocolError(
            ClusterErrorCode.MALFORMED_ENVELOPE,
            f"unknown fields not allowed in V1: {sorted(unknown)}",
        )
    # 3. protocol_version 必须常量
    if obj["protocol_version"] != PROTOCOL_VERSION:
        raise ClusterProtocolError(
            ClusterErrorCode.PROTOCOL_VERSION_MISMATCH,
            f"expected protocol_version={PROTOCOL_VERSION!r}, "
            f"got {obj['protocol_version']!r}",
        )
    # 4. message_kind 必须在 V1 6 个枚举
    try:
        ClusterMessageKind(obj["message_kind"])
    except ValueError as e:
        raise ClusterProtocolError(
            ClusterErrorCode.UNKNOWN_MESSAGE_KIND,
            f"unknown message_kind: {obj['message_kind']!r}",
        ) from e
    # 5. UUID 字段
    _validate_uuid("request_id", obj["request_id"])
    _validate_uuid("instance_id", obj["instance_id"])
    # 6. int / float 字段
    if not isinstance(obj["startup_epoch"], int) or obj["startup_epoch"] < 0:
        raise ClusterProtocolError(
            ClusterErrorCode.MALFORMED_ENVELOPE,
            "startup_epoch must be non-negative int",
        )
    if not isinstance(obj["permits"], (int, float)) or obj["permits"] < 0.0:
        raise ClusterProtocolError(
            ClusterErrorCode.MALFORMED_ENVELOPE,
            "permits must be non-negative number",
        )
    if not isinstance(obj["deadline_ns"], int) or obj["deadline_ns"] < 0:
        raise ClusterProtocolError(
            ClusterErrorCode.MALFORMED_ENVELOPE,
            "deadline_ns must be non-negative int",
        )
    # 7. resource 长度
    if not isinstance(obj["resource"], str) or len(obj["resource"]) == 0:
        raise ClusterProtocolError(
            ClusterErrorCode.MALFORMED_ENVELOPE,
            "resource must be non-empty string",
        )
    if len(obj["resource"]) > RESOURCE_MAX_LEN:
        raise ClusterProtocolError(
            ClusterErrorCode.MALFORMED_ENVELOPE,
            f"resource exceeds {RESOURCE_MAX_LEN} chars",
        )
    # 8. 时间字段
    _validate_iso_utc_micro("client_requested_at", obj["client_requested_at"])
    _validate_iso_utc_micro("server_received_at", obj["server_received_at"])
    # 9. payload 必须是 object
    if not isinstance(obj["payload"], dict):
        raise ClusterProtocolError(
            ClusterErrorCode.MALFORMED_ENVELOPE,
            "payload must be a JSON object",
        )


def encode_envelope(envelope: ClusterTokenEnvelope) -> bytes:
    """ClusterTokenEnvelope → 严格 JSON bytes.

    校验 message_kind 必须在 V1 6 个枚举, 其余字段值合法性由
    ClusterTokenEnvelope 的 dataclass 类型系统保证.

    Raises:
        ClusterProtocolError: 校验失败
    """
    if envelope.protocol_version != PROTOCOL_VERSION:
        raise ClusterProtocolError(
            ClusterErrorCode.PROTOCOL_VERSION_MISMATCH,
            f"envelope.protocol_version must be {PROTOCOL_VERSION!r}, "
            f"got {envelope.protocol_version!r}",
        )
    obj = {
        "protocol_version": envelope.protocol_version,
        "message_kind": envelope.message_kind.value,
        "request_id": envelope.request_id,
        "instance_id": envelope.instance_id,
        "startup_epoch": envelope.startup_epoch,
        "resource": envelope.resource,
        "permits": envelope.permits,
        "deadline_ns": envelope.deadline_ns,
        "client_requested_at": envelope.client_requested_at,
        "server_received_at": envelope.server_received_at,
        "payload": envelope.payload,
    }
    raw = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(raw) > ENVELOPE_MAX_SIZE_BYTES:
        raise ClusterProtocolError(
            ClusterErrorCode.MALFORMED_ENVELOPE,
            f"envelope exceeds {ENVELOPE_MAX_SIZE_BYTES} bytes "
            f"(actual: {len(raw)})",
        )
    return raw


def decode_envelope(raw: bytes) -> ClusterTokenEnvelope:
    """严格 JSON bytes → ClusterTokenEnvelope.

    Raises:
        ClusterProtocolError: 任何字段不满足 V1 冻结 schema
    """
    if len(raw) > ENVELOPE_MAX_SIZE_BYTES:
        raise ClusterProtocolError(
            ClusterErrorCode.MALFORMED_ENVELOPE,
            f"envelope exceeds {ENVELOPE_MAX_SIZE_BYTES} bytes "
            f"(actual: {len(raw)})",
        )
    try:
        obj = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ClusterProtocolError(
            ClusterErrorCode.MALFORMED_ENVELOPE,
            f"invalid JSON: {e}",
        ) from e
    if not isinstance(obj, dict):
        raise ClusterProtocolError(
            ClusterErrorCode.MALFORMED_ENVELOPE,
            "envelope must be a JSON object",
        )
    _validate_envelope_dict(obj)
    # Decode 阶段也校验 per-kind payload (V1 frozen, 严格 schema 锁定)
    message_kind = ClusterMessageKind(obj["message_kind"])
    validate_payload(message_kind, obj["payload"])
    return ClusterTokenEnvelope(
        protocol_version=obj["protocol_version"],
        message_kind=ClusterMessageKind(obj["message_kind"]),
        request_id=obj["request_id"],
        instance_id=obj["instance_id"],
        startup_epoch=obj["startup_epoch"],
        resource=obj["resource"],
        permits=obj["permits"],
        deadline_ns=obj["deadline_ns"],
        client_requested_at=obj["client_requested_at"],
        server_received_at=obj["server_received_at"],
        payload=obj["payload"],
    )


# ---------------------------------------------------------------------------
# Payload 校验 (per-kind, 协议 §4)
# ---------------------------------------------------------------------------


def _validate_acquire_request_payload(payload: dict[str, Any]) -> None:
    required = {"rule_version_epoch", "rule_version_revision", "rule_version_checksum"}
    if set(payload.keys()) != required | {"priority"}:
        raise ClusterProtocolError(
            ClusterErrorCode.MALFORMED_ENVELOPE,
            f"AcquireRequestPayload must have {sorted(required | {'priority'})}, "
            f"got {sorted(payload.keys())}",
        )
    if not isinstance(payload["rule_version_epoch"], int) or payload["rule_version_epoch"] < 0:
        raise ClusterProtocolError(
            ClusterErrorCode.MALFORMED_ENVELOPE,
            "rule_version_epoch must be non-negative int",
        )
    if not isinstance(payload["rule_version_revision"], int) or payload["rule_version_revision"] < 0:
        raise ClusterProtocolError(
            ClusterErrorCode.MALFORMED_ENVELOPE,
            "rule_version_revision must be non-negative int",
        )
    checksum = payload["rule_version_checksum"]
    if not isinstance(checksum, str) or not _RULE_VERSION_CHECKSUM_RE.match(checksum):
        raise ClusterProtocolError(
            ClusterErrorCode.MALFORMED_ENVELOPE,
            f"rule_version_checksum must be {RULE_VERSION_CHECKSUM_PREFIX!r}+"
            f"{RULE_VERSION_CHECKSUM_HEX_LEN} hex chars",
        )
    if "priority" in payload and (
        not isinstance(payload["priority"], int) or not 0 <= payload["priority"] <= 9
    ):
        raise ClusterProtocolError(
            ClusterErrorCode.MALFORMED_ENVELOPE,
            "priority must be int in [0, 9]",
        )


def _validate_acquire_or_renew_response_payload(
    payload: dict[str, Any], expected_decisions: tuple[str, ...]
) -> None:
    required_granted = {"decision", "lease_id", "lease_expires_at",
                        "permits_granted", "retry_after_ns", "deny_reason"}
    if set(payload.keys()) != required_granted:
        raise ClusterProtocolError(
            ClusterErrorCode.MALFORMED_ENVELOPE,
            f"response payload must have {sorted(required_granted)}, "
            f"got {sorted(payload.keys())}",
        )
    if payload["decision"] not in expected_decisions:
        raise ClusterProtocolError(
            ClusterErrorCode.MALFORMED_ENVELOPE,
            f"decision must be one of {expected_decisions}, got {payload['decision']!r}",
        )
    if not isinstance(payload["retry_after_ns"], int) or payload["retry_after_ns"] < 0:
        raise ClusterProtocolError(
            ClusterErrorCode.MALFORMED_ENVELOPE,
            "retry_after_ns must be non-negative int",
        )
    if payload["decision"].endswith("GRANTED") or payload["decision"] == "RENEWED":
        # REMOTE_GRANTED / RENEWED 必填 lease_id / lease_expires_at / permits_granted
        if payload["lease_id"] is None:
            raise ClusterProtocolError(
                ClusterErrorCode.MALFORMED_ENVELOPE,
                f"{payload['decision']} requires lease_id not None",
            )
        if payload["lease_expires_at"] is None:
            raise ClusterProtocolError(
                ClusterErrorCode.MALFORMED_ENVELOPE,
                f"{payload['decision']} requires lease_expires_at not None",
            )
        if payload["permits_granted"] is None:
            raise ClusterProtocolError(
                ClusterErrorCode.MALFORMED_ENVELOPE,
                f"{payload['decision']} requires permits_granted not None",
            )
        _validate_uuid("lease_id", payload["lease_id"])
        _validate_iso_utc_micro("lease_expires_at", payload["lease_expires_at"])
        if (
            not isinstance(payload["permits_granted"], (int, float))
            or payload["permits_granted"] < 0.0
        ):
            raise ClusterProtocolError(
                ClusterErrorCode.MALFORMED_ENVELOPE,
                "permits_granted must be non-negative number",
            )
    else:  # DENIED
        if payload["deny_reason"] is None:
            raise ClusterProtocolError(
                ClusterErrorCode.MALFORMED_ENVELOPE,
                "DENIED requires deny_reason not None",
            )
        try:
            ClusterDenyReason(payload["deny_reason"])
        except ValueError as e:
            raise ClusterProtocolError(
                ClusterErrorCode.MALFORMED_ENVELOPE,
                f"unknown deny_reason: {payload['deny_reason']!r}",
            ) from e


def _validate_release_request_payload(payload: dict[str, Any]) -> None:
    required = {"lease_id", "permits_released"}
    if set(payload.keys()) != required:
        raise ClusterProtocolError(
            ClusterErrorCode.MALFORMED_ENVELOPE,
            f"ReleaseRequestPayload must have {sorted(required)}, "
            f"got {sorted(payload.keys())}",
        )
    _validate_uuid("lease_id", payload["lease_id"])
    if (
        not isinstance(payload["permits_released"], (int, float))
        or payload["permits_released"] < 0.0
    ):
        raise ClusterProtocolError(
            ClusterErrorCode.MALFORMED_ENVELOPE,
            "permits_released must be non-negative number",
        )


def _validate_renew_request_payload(payload: dict[str, Any]) -> None:
    required = {"lease_id", "extends_for_ns"}
    if set(payload.keys()) != required:
        raise ClusterProtocolError(
            ClusterErrorCode.MALFORMED_ENVELOPE,
            f"RenewRequestPayload must have {sorted(required)}, "
            f"got {sorted(payload.keys())}",
        )
    _validate_uuid("lease_id", payload["lease_id"])
    if not isinstance(payload["extends_for_ns"], int) or payload["extends_for_ns"] <= 0:
        raise ClusterProtocolError(
            ClusterErrorCode.MALFORMED_ENVELOPE,
            "extends_for_ns must be positive int",
        )


def _validate_error_response_payload(payload: dict[str, Any]) -> None:
    required = {"error_code"}
    if set(payload.keys()) - required - {"error_message"}:
        raise ClusterProtocolError(
            ClusterErrorCode.MALFORMED_ENVELOPE,
            f"ErrorResponsePayload must have {sorted(required | {'error_message'})}, "
            f"got {sorted(payload.keys())}",
        )
    try:
        ClusterErrorCode(payload["error_code"])
    except ValueError as e:
        raise ClusterProtocolError(
            ClusterErrorCode.MALFORMED_ENVELOPE,
            f"unknown error_code: {payload['error_code']!r}",
        ) from e
    if "error_message" in payload:
        msg = payload["error_message"]
        if not isinstance(msg, str):
            raise ClusterProtocolError(
                ClusterErrorCode.MALFORMED_ENVELOPE,
                "error_message must be string",
            )
        if len(msg.encode("utf-8")) > ERROR_MESSAGE_MAX_LEN:
            raise ClusterProtocolError(
                ClusterErrorCode.MALFORMED_ENVELOPE,
                f"error_message exceeds {ERROR_MESSAGE_MAX_LEN} bytes (脱敏 reason 上限)",
            )


def validate_payload(message_kind: ClusterMessageKind, payload: dict[str, Any]) -> None:
    """Per-kind payload 严格校验 (协议 §4).

    Raises:
        ClusterProtocolError: 字段缺失 / 未知 / 类型错
    """
    if message_kind is ClusterMessageKind.ACQUIRE_REQUEST:
        _validate_acquire_request_payload(payload)
    elif message_kind is ClusterMessageKind.ACQUIRE_RESPONSE:
        _validate_acquire_or_renew_response_payload(
            payload, expected_decisions=("REMOTE_GRANTED", "DENIED")
        )
    elif message_kind is ClusterMessageKind.RELEASE_REQUEST:
        _validate_release_request_payload(payload)
    elif message_kind is ClusterMessageKind.RENEW_REQUEST:
        _validate_renew_request_payload(payload)
    elif message_kind is ClusterMessageKind.RENEW_RESPONSE:
        _validate_acquire_or_renew_response_payload(
            payload, expected_decisions=("RENEWED", "DENIED")
        )
    elif message_kind is ClusterMessageKind.ERROR_RESPONSE:
        _validate_error_response_payload(payload)
    else:  # pragma: no cover (StrEnum exhaustive)
        raise ClusterProtocolError(
            ClusterErrorCode.UNKNOWN_MESSAGE_KIND,
            f"unsupported message_kind: {message_kind!r}",
        )


__all__ = [
    "ClusterProtocolError",
    "decode_envelope",
    "encode_envelope",
    "validate_payload",
]

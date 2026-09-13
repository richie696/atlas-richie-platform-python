"""Atlas Richie Agent Reporting Protocol V1 — JSON codec (strict).

严格 JSON 序列化 / 反序列化, 拒绝:
- 未知 field (V1 frozen, 不宽容)
- 缺必填 field
- ``event_kind`` 不在 V1 6 个枚举
- ``protocol_version`` ≠ ``"atlas-richie.reporting/v1"``
- envelope size > 16 KB (协议 §2.5)
- 时间字段不符合 ISO 8601 UTC microsecond
- UUID 字段不符合 8-4-4-4-12 格式
- per-kind payload 字段缺失 / 类型错

参考: ``docs/protocols/AGENT_REPORTING_PROTOCOL.md`` §2 + §3 + §4 + §5.
"""

from __future__ import annotations

import json
import re
from enum import StrEnum
from typing import Any

from .envelope import ReportingEnvelope
from .event_kind import ReportingEventKind
from .payloads import (
    EXEC_RESULT_VALUES,
    HEALTH_CLASS_VALUES,
    REASON_MESSAGE_MAX_LEN,
    RULE_ID_MAX_LEN,
    SOURCE_ID_MAX_LEN,
)

# protocol_version 固定值 (协议 §2.2)
PROTOCOL_VERSION = "atlas-richie.reporting/v1"

# envelope size 上限 (协议 §2.5)
ENVELOPE_MAX_SIZE_BYTES = 16 * 1024

# 必填 envelope 字段 (协议 §2.1)
_REQUIRED_ENVELOPE_FIELDS: frozenset[str] = frozenset({
    "protocol_version",
    "event_kind",
    "event_payload",
    "instance_id",
    "startup_epoch",
    "sequence",
    "captured_at",
    "received_at",
})

# UUID v4 8-4-4-4-12 hex (lowercase, 协议 §2.3)
_UUID_V4_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)

# ISO 8601 UTC microsecond (协议 §2.3)
_ISO_8601_UTC_MICRO_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$"
)

# rule_version_checksum 格式: ``sha256:`` + 64 hex chars (协议 §4.1)
_RULE_VERSION_CHECKSUM_RE = re.compile(
    r"^sha256:[0-9a-f]{64}$"
)


# ---------------------------------------------------------------------------
# 错误码 (协议 §5)
# ---------------------------------------------------------------------------


class ReportingErrorCode(StrEnum):
    """协议错误码 (V1, 协议 §5). 仅本地错误传播用, 不进入 wire."""

    PROTOCOL_VERSION_MISMATCH = "ProtocolVersionMismatch"
    MALFORMED_ENVELOPE = "MalformedEnvelope"
    UNKNOWN_EVENT_KIND = "UnknownEventKind"
    PAYLOAD_SCHEMA_MISMATCH = "PayloadSchemaMismatch"
    INSTANCE_ID_EMPTY = "InstanceIdEmpty"
    SEQUENCE_NOT_MONOTONIC = "SequenceNotMonotonic"
    SEQUENCE_GAP = "SequenceGap"
    STALE_EPOCH = "StaleEpoch"
    ENVELOPE_TOO_LARGE = "EnvelopeTooLarge"


class ReportingProtocolError(ValueError):
    """Reporting Protocol V1 — 严格 codec 抛错 (含错误码)."""

    def __init__(self, code: ReportingErrorCode, message: str) -> None:
        super().__init__(f"[{code.value}] {message}")
        self.code = code
        self.message = message


# ---------------------------------------------------------------------------
# 校验
# ---------------------------------------------------------------------------


def _validate_uuid(field: str, value: str) -> None:
    if not isinstance(value, str) or not _UUID_V4_RE.match(value):
        raise ReportingProtocolError(
            ReportingErrorCode.MALFORMED_ENVELOPE,
            f"{field} must be UUID v4 (8-4-4-4-12 lowercase hex)",
        )


def _validate_iso_utc_micro(field: str, value: Any) -> None:
    if not isinstance(value, str) or not _ISO_8601_UTC_MICRO_RE.match(value):
        raise ReportingProtocolError(
            ReportingErrorCode.MALFORMED_ENVELOPE,
            f"{field} must be ISO 8601 UTC microsecond "
            f"(YYYY-MM-DDTHH:MM:SS.ffffffZ)",
        )


def _validate_common_rule_version_triplet(payload: dict[str, Any]) -> None:
    if not isinstance(payload["rule_version_epoch"], int) or payload["rule_version_epoch"] < 0:
        raise ReportingProtocolError(
            ReportingErrorCode.PAYLOAD_SCHEMA_MISMATCH,
            "rule_version_epoch must be non-negative int",
        )
    if not isinstance(payload["rule_version_revision"], int) or payload["rule_version_revision"] < 0:
        raise ReportingProtocolError(
            ReportingErrorCode.PAYLOAD_SCHEMA_MISMATCH,
            "rule_version_revision must be non-negative int",
        )
    checksum = payload["rule_version_checksum"]
    if not isinstance(checksum, str) or not _RULE_VERSION_CHECKSUM_RE.match(checksum):
        raise ReportingProtocolError(
            ReportingErrorCode.PAYLOAD_SCHEMA_MISMATCH,
            "rule_version_checksum must be 'sha256:' + 64 hex chars",
        )


def _validate_source_id(payload: dict[str, Any]) -> None:
    source_id = payload.get("source_id")
    if not isinstance(source_id, str) or not source_id:
        raise ReportingProtocolError(
            ReportingErrorCode.PAYLOAD_SCHEMA_MISMATCH,
            "source_id must be non-empty string",
        )
    if len(source_id) > SOURCE_ID_MAX_LEN:
        raise ReportingProtocolError(
            ReportingErrorCode.PAYLOAD_SCHEMA_MISMATCH,
            f"source_id exceeds {SOURCE_ID_MAX_LEN} chars",
        )


def _validate_payload_rule_source_activated(payload: dict[str, Any]) -> None:
    required = {"source_id", "rule_version_epoch", "rule_version_revision", "rule_version_checksum"}
    if set(payload.keys()) != required:
        raise ReportingProtocolError(
            ReportingErrorCode.PAYLOAD_SCHEMA_MISMATCH,
            f"RuleSourceActivatedPayload must have {sorted(required)}, "
            f"got {sorted(payload.keys())}",
        )
    _validate_source_id(payload)
    _validate_common_rule_version_triplet(payload)


def _validate_payload_rule_source_health(payload: dict[str, Any]) -> None:
    required = {
        "source_id", "rule_version_epoch", "rule_version_revision",
        "rule_version_checksum", "health_class", "reason_class",
    }
    if set(payload.keys()) - required - {"reason_message"}:
        raise ReportingProtocolError(
            ReportingErrorCode.PAYLOAD_SCHEMA_MISMATCH,
            f"RuleSourceHealthPayload must have {sorted(required | {'reason_message'})}, "
            f"got {sorted(payload.keys())}",
        )
    _validate_source_id(payload)
    _validate_common_rule_version_triplet(payload)
    if payload["health_class"] not in HEALTH_CLASS_VALUES:
        raise ReportingProtocolError(
            ReportingErrorCode.PAYLOAD_SCHEMA_MISMATCH,
            f"health_class must be one of {sorted(HEALTH_CLASS_VALUES)}, "
            f"got {payload['health_class']!r}",
        )
    if not isinstance(payload["reason_class"], str) or not payload["reason_class"]:
        raise ReportingProtocolError(
            ReportingErrorCode.PAYLOAD_SCHEMA_MISMATCH,
            "reason_class must be non-empty string (stable error class)",
        )
    if "reason_message" in payload:
        msg = payload["reason_message"]
        if not isinstance(msg, str):
            raise ReportingProtocolError(
                ReportingErrorCode.PAYLOAD_SCHEMA_MISMATCH,
                "reason_message must be string",
            )
        if len(msg.encode("utf-8")) > REASON_MESSAGE_MAX_LEN:
            raise ReportingProtocolError(
                ReportingErrorCode.PAYLOAD_SCHEMA_MISMATCH,
                f"reason_message exceeds {REASON_MESSAGE_MAX_LEN} bytes "
                f"(脱敏 reason 上限, 协议 §4.2)",
            )


def _validate_payload_rule_exec(payload: dict[str, Any]) -> None:
    required = {
        "source_id", "rule_id", "rule_version_epoch",
        "rule_version_revision", "rule_version_checksum", "exec_result",
    }
    if set(payload.keys()) - required - {"failure_class"}:
        raise ReportingProtocolError(
            ReportingErrorCode.PAYLOAD_SCHEMA_MISMATCH,
            f"RuleExecPayload must have {sorted(required | {'failure_class'})}, "
            f"got {sorted(payload.keys())}",
        )
    _validate_source_id(payload)
    _validate_common_rule_version_triplet(payload)
    rule_id = payload["rule_id"]
    if not isinstance(rule_id, str) or not rule_id:
        raise ReportingProtocolError(
            ReportingErrorCode.PAYLOAD_SCHEMA_MISMATCH,
            "rule_id must be non-empty string",
        )
    if len(rule_id) > RULE_ID_MAX_LEN:
        raise ReportingProtocolError(
            ReportingErrorCode.PAYLOAD_SCHEMA_MISMATCH,
            f"rule_id exceeds {RULE_ID_MAX_LEN} chars",
        )
    if payload["exec_result"] not in EXEC_RESULT_VALUES:
        raise ReportingProtocolError(
            ReportingErrorCode.PAYLOAD_SCHEMA_MISMATCH,
            f"exec_result must be one of {sorted(EXEC_RESULT_VALUES)}, "
            f"got {payload['exec_result']!r}",
        )
    if payload["exec_result"] == "FAILED":
        if "failure_class" not in payload or payload["failure_class"] is None:
            raise ReportingProtocolError(
                ReportingErrorCode.PAYLOAD_SCHEMA_MISMATCH,
                "exec_result=FAILED requires failure_class not None",
            )
        if not isinstance(payload["failure_class"], str) or not payload["failure_class"]:
            raise ReportingProtocolError(
                ReportingErrorCode.PAYLOAD_SCHEMA_MISMATCH,
                "failure_class must be non-empty string (stable error class)",
            )


def _validate_envelope_dict(obj: dict[str, Any]) -> None:
    # 1. 必填字段齐全
    missing = _REQUIRED_ENVELOPE_FIELDS - set(obj.keys())
    if missing:
        raise ReportingProtocolError(
            ReportingErrorCode.MALFORMED_ENVELOPE,
            f"missing required fields: {sorted(missing)}",
        )
    # 2. 严格不允许未知字段 (V1 frozen)
    unknown = set(obj.keys()) - _REQUIRED_ENVELOPE_FIELDS
    if unknown:
        raise ReportingProtocolError(
            ReportingErrorCode.MALFORMED_ENVELOPE,
            f"unknown fields not allowed in V1: {sorted(unknown)}",
        )
    # 3. protocol_version 必须常量
    if obj["protocol_version"] != PROTOCOL_VERSION:
        raise ReportingProtocolError(
            ReportingErrorCode.PROTOCOL_VERSION_MISMATCH,
            f"expected protocol_version={PROTOCOL_VERSION!r}, "
            f"got {obj['protocol_version']!r}",
        )
    # 4. event_kind 必须在 V1 6 个枚举
    try:
        ReportingEventKind(obj["event_kind"])
    except ValueError as e:
        raise ReportingProtocolError(
            ReportingErrorCode.UNKNOWN_EVENT_KIND,
            f"unknown event_kind: {obj['event_kind']!r}",
        ) from e
    # 5. instance_id 不能空, 必须是 UUID
    instance_id = obj["instance_id"]
    if not isinstance(instance_id, str) or not instance_id:
        raise ReportingProtocolError(
            ReportingErrorCode.INSTANCE_ID_EMPTY,
            "instance_id must be non-empty string",
        )
    _validate_uuid("instance_id", instance_id)
    # 6. 数字字段
    if not isinstance(obj["startup_epoch"], int) or obj["startup_epoch"] < 0:
        raise ReportingProtocolError(
            ReportingErrorCode.MALFORMED_ENVELOPE,
            "startup_epoch must be non-negative int",
        )
    if not isinstance(obj["sequence"], int) or obj["sequence"] < 0:
        raise ReportingProtocolError(
            ReportingErrorCode.MALFORMED_ENVELOPE,
            "sequence must be non-negative int",
        )
    # 7. 时间字段
    _validate_iso_utc_micro("captured_at", obj["captured_at"])
    _validate_iso_utc_micro("received_at", obj["received_at"])
    # 8. event_payload 必须是 object
    if not isinstance(obj["event_payload"], dict):
        raise ReportingProtocolError(
            ReportingErrorCode.MALFORMED_ENVELOPE,
            "event_payload must be a JSON object",
        )


def encode_envelope(envelope: ReportingEnvelope) -> bytes:
    """ReportingEnvelope → 严格 JSON bytes.

    Raises:
        ReportingProtocolError: 字段不合法 / 超出 size
    """
    if envelope.protocol_version != PROTOCOL_VERSION:
        raise ReportingProtocolError(
            ReportingErrorCode.PROTOCOL_VERSION_MISMATCH,
            f"envelope.protocol_version must be {PROTOCOL_VERSION!r}, "
            f"got {envelope.protocol_version!r}",
        )
    obj = {
        "protocol_version": envelope.protocol_version,
        "event_kind": envelope.event_kind.value,
        "event_payload": envelope.event_payload,
        "instance_id": envelope.instance_id,
        "startup_epoch": envelope.startup_epoch,
        "sequence": envelope.sequence,
        "captured_at": envelope.captured_at,
        "received_at": envelope.received_at,
    }
    raw = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(raw) > ENVELOPE_MAX_SIZE_BYTES:
        raise ReportingProtocolError(
            ReportingErrorCode.ENVELOPE_TOO_LARGE,
            f"envelope exceeds {ENVELOPE_MAX_SIZE_BYTES} bytes (actual: {len(raw)})",
        )
    return raw


def decode_envelope(raw: bytes) -> ReportingEnvelope:
    """严格 JSON bytes → ReportingEnvelope.

    Raises:
        ReportingProtocolError: 任何字段不满足 V1 冻结 schema
    """
    if len(raw) > ENVELOPE_MAX_SIZE_BYTES:
        raise ReportingProtocolError(
            ReportingErrorCode.ENVELOPE_TOO_LARGE,
            f"envelope exceeds {ENVELOPE_MAX_SIZE_BYTES} bytes (actual: {len(raw)})",
        )
    try:
        obj = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ReportingProtocolError(
            ReportingErrorCode.MALFORMED_ENVELOPE,
            f"invalid JSON: {e}",
        ) from e
    if not isinstance(obj, dict):
        raise ReportingProtocolError(
            ReportingErrorCode.MALFORMED_ENVELOPE,
            "envelope must be a JSON object",
        )
    _validate_envelope_dict(obj)
    # Decode 阶段也校验 per-kind payload (V1 frozen, 严格 schema 锁定)
    event_kind = ReportingEventKind(obj["event_kind"])
    validate_payload(event_kind, obj["event_payload"])
    return ReportingEnvelope(
        protocol_version=obj["protocol_version"],
        event_kind=ReportingEventKind(obj["event_kind"]),
        event_payload=obj["event_payload"],
        instance_id=obj["instance_id"],
        startup_epoch=obj["startup_epoch"],
        sequence=obj["sequence"],
        captured_at=obj["captured_at"],
        received_at=obj["received_at"],
    )


def validate_payload(event_kind: ReportingEventKind, payload: dict[str, Any]) -> None:
    """Per-kind payload 严格校验 (协议 §4).

    Raises:
        ReportingProtocolError: 字段缺失 / 未知 / 类型错
    """
    if event_kind is ReportingEventKind.RULE_SOURCE_ACTIVATED:
        _validate_payload_rule_source_activated(payload)
    elif event_kind in (
        ReportingEventKind.RULE_SOURCE_STALE,
        ReportingEventKind.RULE_SOURCE_DEGRADED,
    ):
        _validate_payload_rule_source_health(payload)
    elif event_kind in (
        ReportingEventKind.RULE_APPLIED,
        ReportingEventKind.RULE_BLOCKED,
        ReportingEventKind.RULE_FAILED,
    ):
        _validate_payload_rule_exec(payload)
    else:  # pragma: no cover (StrEnum exhaustive)
        raise ReportingProtocolError(
            ReportingErrorCode.UNKNOWN_EVENT_KIND,
            f"unsupported event_kind: {event_kind!r}",
        )


__all__ = [
    "ENVELOPE_MAX_SIZE_BYTES",
    "PROTOCOL_VERSION",
    "ReportingEnvelope",
    "ReportingErrorCode",
    "ReportingEventKind",
    "ReportingProtocolError",
    "decode_envelope",
    "encode_envelope",
    "validate_payload",
]

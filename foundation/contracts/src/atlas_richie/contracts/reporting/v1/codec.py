"""Atlas Richie Agent Reporting Protocol V1 — strict JSON codec (DRAFT).

1:1 镜像 ``docs/protocol/上报协议-01-envelope-v1.md`` + ``上报协议-02-transport-v1.md``.
严格 JSON 序列化 / 反序列化, 拒绝:

- 未知 field (DRAFT 阶段严格, V1 frozen 后仍严格)
- 缺必填字段
- ``protocol_version`` ≠ ``"atlas-richie.reporting/v1"``
- ``event_kind`` 不在 V1 6 个枚举
- ``error_code`` 不在 V1 11 个枚举
- ``health_class`` / ``reason_class`` / ``exec_result`` 不在对应枚举
- ``rule_version_checksum`` 不符合 ``sha256:`` + 64 hex chars
- 时间字段不符合 ISO 8601 UTC microsecond
- UUID 字段不符合 8-4-4-4-12 lowercase hex
- envelope > 16 KiB / batch > 64 KiB / batch > 256 events
- batch 内 events 跟 batch 身份 / generation 不一致
- 错误 batch 原子拒绝 (无 per-event disposition)

V1 协议 BUG 收口 (richie696 2026-09-13) codec 关键变更:
- ingress envelope 7 字段 (无 ``received_at``)
- batch 强制单一 identity/generation
- 错误 batch 原子拒绝 + Ack 用 ``duplicate_count``
- 11 错误码 (新增 ``ENVELOPE_TOO_LARGE`` / ``BATCH_TOO_LARGE``)
- ReasonClass 冻结枚举 (7 值)
- Health "无有效规则快照" 3 rule_version_* 字段成组可选
"""

from __future__ import annotations

import json
import re
from typing import Any

from .batch import (
    BATCH_MAX_EVENTS,
    BATCH_MAX_SIZE_BYTES,
    ERROR_MESSAGE_MAX_LEN,
    AckEnvelope,
    AckSequence,
    ErrorDetails,
    ErrorEnvelope,
    ReportingBatch,
)
from .envelope import (
    ENVELOPE_MAX_SIZE_BYTES,
    INT64_MAX,
    INT64_MIN,
    PROTOCOL_VERSION,
    ISO_8601_UTC_MICRO,
    UUID_V4_REGEX,
    ReportingEnvelope,
)
from .error_codes import ReportingErrorCode
from .event_kind import ExecResult, HealthClass, ReasonClass, ReportingEventKind
from .payloads import (
    REASON_MESSAGE_MAX_LEN,
    RULE_ID_MAX_LEN,
    RULE_VERSION_CHECKSUM_HEX_LEN,
    RULE_VERSION_CHECKSUM_PREFIX,
    SOURCE_ID_MAX_LEN,
    RuleExecPayload,
    RuleSourceActivatedPayload,
    RuleSourceHealthPayload,
)

# 必填 envelope 字段 (协议 §3.2, 7 字段 — BUG 收口后无 received_at)
_REQUIRED_ENVELOPE_FIELDS: frozenset[str] = frozenset({
    "protocol_version",
    "event_kind",
    "event_payload",
    "instance_id",
    "startup_epoch",
    "sequence",
    "captured_at",
})

# 必填 batch 字段 (协议 §7.2, 8 字段)
_REQUIRED_BATCH_FIELDS: frozenset[str] = frozenset({
    "protocol_version",
    "instance_id",
    "startup_epoch",
    "batch_id",
    "sent_at",
    "events",
    "dropped_count",
})

# 必填 ack 字段 (协议 §9.2, 5 字段)
_REQUIRED_ACK_FIELDS: frozenset[str] = frozenset({
    "protocol_version",
    "batch_id",
    "received_at",
    "ack_sequences",
    "duplicate_count",
})

# 必填 error 字段 (协议 transport §6)
_REQUIRED_ERROR_FIELDS: frozenset[str] = frozenset({
    "protocol_version",
    "error_code",
    "message",
    "details",
})

# 编译正则
_UUID_V4_RE = re.compile(UUID_V4_REGEX)
_ISO_8601_UTC_MICRO_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$"
)
_RULE_VERSION_CHECKSUM_RE = re.compile(
    r"^sha256:[0-9a-f]{64}$"
)


# ---------------------------------------------------------------------------
# 错误
# ---------------------------------------------------------------------------


class ReportingProtocolError(ValueError):
    """Reporting Protocol V1 — 严格 codec 抛错 (含错误码)."""

    def __init__(self, code: ReportingErrorCode, message: str) -> None:
        super().__init__(f"[{code.value}] {message}")
        self.code = code
        self.message = message


# ---------------------------------------------------------------------------
# 校验 helper
# ---------------------------------------------------------------------------


def _validate_uuid(field: str, value: Any) -> None:
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


def _validate_int64(field: str, value: Any, allow_none: bool = False) -> None:
    if value is None and allow_none:
        return
    if not isinstance(value, int) or isinstance(value, bool):
        raise ReportingProtocolError(
            ReportingErrorCode.MALFORMED_ENVELOPE,
            f"{field} must be int",
        )
    if not (INT64_MIN <= value <= INT64_MAX):
        raise ReportingProtocolError(
            ReportingErrorCode.MALFORMED_ENVELOPE,
            f"{field} must be int64 in [0, 2^53-1] (got {value})",
        )


def _validate_protocol_version(obj: dict[str, Any]) -> None:
    if obj.get("protocol_version") != PROTOCOL_VERSION:
        raise ReportingProtocolError(
            ReportingErrorCode.PROTOCOL_VERSION_MISMATCH,
            f"expected protocol_version={PROTOCOL_VERSION!r}, "
            f"got {obj.get('protocol_version')!r}",
        )


def _validate_common_rule_version_triplet(
    payload: dict[str, Any], field_prefix: str = "rule_version"
) -> None:
    _validate_int64(f"{field_prefix}_epoch", payload[f"{field_prefix}_epoch"])
    _validate_int64(f"{field_prefix}_revision", payload[f"{field_prefix}_revision"])
    checksum = payload[f"{field_prefix}_checksum"]
    if not isinstance(checksum, str) or not _RULE_VERSION_CHECKSUM_RE.match(checksum):
        raise ReportingProtocolError(
            ReportingErrorCode.PAYLOAD_SCHEMA_MISMATCH,
            f"{field_prefix}_checksum must be 'sha256:' + 64 hex chars",
        )


def _validate_source_id(source_id: Any) -> None:
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


def _validate_rule_version_triplet_all_or_none(
    payload: dict[str, Any], field_prefix: str
) -> None:
    """3 rule_version_* 字段**成组可选**: 同时出现或同时省略 (协议 §5.2)."""
    epoch = payload.get(f"{field_prefix}_epoch")
    revision = payload.get(f"{field_prefix}_revision")
    checksum = payload.get(f"{field_prefix}_checksum")
    present = (epoch is not None, revision is not None, checksum is not None)
    if any(present) and not all(present):
        raise ReportingProtocolError(
            ReportingErrorCode.PAYLOAD_SCHEMA_MISMATCH,
            f"3 {field_prefix}_* fields must be all present or all omitted "
            f"(成组可选, 协议 §5.2)",
        )
    if all(present):
        _validate_common_rule_version_triplet(payload, field_prefix)


# ---------------------------------------------------------------------------
# Per-kind payload 校验 (协议 §5)
# ---------------------------------------------------------------------------


def _validate_payload_rule_source_activated(payload: dict[str, Any]) -> None:
    required = {"source_id", "rule_version_epoch", "rule_version_revision", "rule_version_checksum"}
    if set(payload.keys()) != required:
        raise ReportingProtocolError(
            ReportingErrorCode.PAYLOAD_SCHEMA_MISMATCH,
            f"RuleSourceActivatedPayload must have {sorted(required)}, "
            f"got {sorted(payload.keys())}",
        )
    _validate_source_id(payload["source_id"])
    _validate_common_rule_version_triplet(payload)


def _validate_payload_rule_source_health(payload: dict[str, Any]) -> None:
    required = {"source_id", "health_class", "reason_class"}
    if set(payload.keys()) - required - {
        "rule_version_epoch", "rule_version_revision", "rule_version_checksum",
        "reason_message",
    }:
        raise ReportingProtocolError(
            ReportingErrorCode.PAYLOAD_SCHEMA_MISMATCH,
            f"RuleSourceHealthPayload must have {sorted(required | {'rule_version_*', 'reason_message'})}, "
            f"got {sorted(payload.keys())}",
        )
    _validate_source_id(payload["source_id"])
    # health_class 必填枚举
    try:
        HealthClass(payload["health_class"])
    except ValueError as e:
        raise ReportingProtocolError(
            ReportingErrorCode.PAYLOAD_SCHEMA_MISMATCH,
            f"health_class must be one of {[c.value for c in HealthClass]}, "
            f"got {payload['health_class']!r}",
        ) from e
    # reason_class 必填枚举 (ReasonClass 7 冻结值)
    try:
        ReasonClass(payload["reason_class"])
    except ValueError as e:
        raise ReportingProtocolError(
            ReportingErrorCode.PAYLOAD_SCHEMA_MISMATCH,
            f"reason_class must be one of {[c.value for c in ReasonClass]}, "
            f"got {payload['reason_class']!r}",
        ) from e
    # 3 rule_version_* 字段成组可选
    _validate_rule_version_triplet_all_or_none(payload, "rule_version")
    # reason_message 可选, 脱敏 ≤ 64 字节
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
                f"(脱敏 reason 上限, 协议 §5.2)",
            )


def _validate_payload_rule_exec(payload: dict[str, Any]) -> None:
    required = {
        "source_id", "rule_id",
        "rule_version_epoch", "rule_version_revision", "rule_version_checksum",
        "exec_result", "failure_class",
    }
    if set(payload.keys()) != required:
        raise ReportingProtocolError(
            ReportingErrorCode.PAYLOAD_SCHEMA_MISMATCH,
            f"RuleExecPayload must have {sorted(required)}, "
            f"got {sorted(payload.keys())}",
        )
    _validate_source_id(payload["source_id"])
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
    _validate_common_rule_version_triplet(payload)
    # exec_result 必填枚举
    try:
        ExecResult(payload["exec_result"])
    except ValueError as e:
        raise ReportingProtocolError(
            ReportingErrorCode.PAYLOAD_SCHEMA_MISMATCH,
            f"exec_result must be one of {[c.value for c in ExecResult]}, "
            f"got {payload['exec_result']!r}",
        ) from e
    # failure_class: 当且仅当 exec_result=FAILED 时为 ReasonClass 枚举值;
    # 其余结果必须 None (协议 §5.3)
    failure_class = payload["failure_class"]
    if payload["exec_result"] == "FAILED":
        if failure_class is None:
            raise ReportingProtocolError(
                ReportingErrorCode.PAYLOAD_SCHEMA_MISMATCH,
                "exec_result=FAILED requires failure_class not None (协议 §5.3)",
            )
        if not isinstance(failure_class, str):
            raise ReportingProtocolError(
                ReportingErrorCode.PAYLOAD_SCHEMA_MISMATCH,
                "failure_class must be string when exec_result=FAILED",
            )
        try:
            ReasonClass(failure_class)
        except ValueError as e:
            raise ReportingProtocolError(
                ReportingErrorCode.PAYLOAD_SCHEMA_MISMATCH,
                f"failure_class must be ReasonClass enum, got {failure_class!r}",
            ) from e
    else:  # APPLIED / BLOCKED
        if failure_class is not None:
            raise ReportingProtocolError(
                ReportingErrorCode.PAYLOAD_SCHEMA_MISMATCH,
                f"exec_result={payload['exec_result']} requires failure_class=None "
                f"(协议 §5.3)",
            )


def validate_payload(event_kind: str, payload: dict[str, Any]) -> None:
    """Per-kind payload 严格校验 (协议 §5).

    Raises:
        ReportingProtocolError: 字段缺失 / 未知 / 类型错 / 枚举不合法
    """
    try:
        kind = ReportingEventKind(event_kind)
    except ValueError as e:
        raise ReportingProtocolError(
            ReportingErrorCode.UNKNOWN_EVENT_KIND,
            f"unknown event_kind: {event_kind!r}",
        ) from e
    if kind is ReportingEventKind.RULE_SOURCE_ACTIVATED:
        _validate_payload_rule_source_activated(payload)
    elif kind in (ReportingEventKind.RULE_SOURCE_STALE, ReportingEventKind.RULE_SOURCE_DEGRADED):
        _validate_payload_rule_source_health(payload)
    elif kind in (
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


# ---------------------------------------------------------------------------
# Envelope (7 字段) 校验 + 序列化
# ---------------------------------------------------------------------------


def _validate_envelope_dict(obj: dict[str, Any]) -> None:
    # 1. 必填字段齐全
    missing = _REQUIRED_ENVELOPE_FIELDS - set(obj.keys())
    if missing:
        raise ReportingProtocolError(
            ReportingErrorCode.MALFORMED_ENVELOPE,
            f"missing required fields: {sorted(missing)}",
        )
    # 2. 严格不允许未知字段 (V1 严格, 即使 DRAFT)
    unknown = set(obj.keys()) - _REQUIRED_ENVELOPE_FIELDS
    if unknown:
        raise ReportingProtocolError(
            ReportingErrorCode.MALFORMED_ENVELOPE,
            f"unknown fields not allowed (received_at 不再是 ingress 字段, "
            f"协议 BUG 收口后 7 字段): {sorted(unknown)}",
        )
    # 3. protocol_version 必须常量
    _validate_protocol_version(obj)
    # 4. event_kind 必须在 V1 6 枚举
    try:
        ReportingEventKind(obj["event_kind"])
    except ValueError as e:
        raise ReportingProtocolError(
            ReportingErrorCode.UNKNOWN_EVENT_KIND,
            f"unknown event_kind: {obj['event_kind']!r}",
        ) from e
    # 5. instance_id UUID v4
    _validate_uuid("instance_id", obj["instance_id"])
    # 6. startup_epoch + sequence int64
    _validate_int64("startup_epoch", obj["startup_epoch"])
    _validate_int64("sequence", obj["sequence"])
    # 7. captured_at ISO 8601 UTC microsecond
    _validate_iso_utc_micro("captured_at", obj["captured_at"])
    # 8. event_payload 必须是 object
    if not isinstance(obj["event_payload"], dict):
        raise ReportingProtocolError(
            ReportingErrorCode.MALFORMED_ENVELOPE,
            "event_payload must be a JSON object",
        )


def encode_envelope(envelope: ReportingEnvelope) -> bytes:
    """ReportingEnvelope (7 字段) → 严格 JSON bytes.

    Raises:
        ReportingProtocolError: 字段不合法 / 超出 size / 枚举错
    """
    if envelope.protocol_version != PROTOCOL_VERSION:
        raise ReportingProtocolError(
            ReportingErrorCode.PROTOCOL_VERSION_MISMATCH,
            f"envelope.protocol_version must be {PROTOCOL_VERSION!r}",
        )
    obj = {
        "protocol_version": envelope.protocol_version,
        "event_kind": envelope.event_kind,
        "event_payload": envelope.event_payload,
        "instance_id": envelope.instance_id,
        "startup_epoch": envelope.startup_epoch,
        "sequence": envelope.sequence,
        "captured_at": envelope.captured_at,
    }
    raw = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(raw) > ENVELOPE_MAX_SIZE_BYTES:
        raise ReportingProtocolError(
            ReportingErrorCode.ENVELOPE_TOO_LARGE,
            f"envelope exceeds {ENVELOPE_MAX_SIZE_BYTES} bytes (actual: {len(raw)})",
        )
    return raw


def decode_envelope(raw: bytes) -> ReportingEnvelope:
    """严格 JSON bytes → ReportingEnvelope (7 字段).

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
    # Decode 阶段也校验 per-kind payload (V1 严格 schema 锁定)
    validate_payload(obj["event_kind"], obj["event_payload"])
    return ReportingEnvelope(
        protocol_version=obj["protocol_version"],
        event_kind=obj["event_kind"],
        event_payload=obj["event_payload"],
        instance_id=obj["instance_id"],
        startup_epoch=obj["startup_epoch"],
        sequence=obj["sequence"],
        captured_at=obj["captured_at"],
    )


# ---------------------------------------------------------------------------
# Batch (8 字段) 校验 + 序列化
# ---------------------------------------------------------------------------


def _validate_batch_dict(obj: dict[str, Any]) -> None:
    # 1. 必填字段齐全
    missing = _REQUIRED_BATCH_FIELDS - set(obj.keys())
    if missing:
        raise ReportingProtocolError(
            ReportingErrorCode.MALFORMED_ENVELOPE,
            f"batch missing required fields: {sorted(missing)}",
        )
    # 2. 严格不允许未知字段
    unknown = set(obj.keys()) - _REQUIRED_BATCH_FIELDS
    if unknown:
        raise ReportingProtocolError(
            ReportingErrorCode.MALFORMED_ENVELOPE,
            f"batch unknown fields not allowed: {sorted(unknown)}",
        )
    # 3. protocol_version 必须常量
    _validate_protocol_version(obj)
    # 4. instance_id UUID v4
    _validate_uuid("instance_id", obj["instance_id"])
    # 5. startup_epoch int64
    _validate_int64("startup_epoch", obj["startup_epoch"])
    # 6. batch_id UUID v4
    _validate_uuid("batch_id", obj["batch_id"])
    # 7. sent_at ISO 8601
    _validate_iso_utc_micro("sent_at", obj["sent_at"])
    # 8. events 是 array
    events = obj["events"]
    if not isinstance(events, list):
        raise ReportingProtocolError(
            ReportingErrorCode.MALFORMED_ENVELOPE,
            "events must be a JSON array",
        )
    if not (1 <= len(events) <= BATCH_MAX_EVENTS):
        raise ReportingProtocolError(
            ReportingErrorCode.MALFORMED_ENVELOPE,
            f"events.length must be in [1, {BATCH_MAX_EVENTS}], got {len(events)}",
        )
    # 9. 强制单一 identity/generation (协议 §7.2): 所有 event 身份
    # 必须与 batch 同值
    for i, ev in enumerate(events):
        if not isinstance(ev, dict):
            raise ReportingProtocolError(
                ReportingErrorCode.MALFORMED_ENVELOPE,
                f"events[{i}] must be a JSON object",
            )
        if ev.get("protocol_version") != obj["protocol_version"]:
            raise ReportingProtocolError(
                ReportingErrorCode.MALFORMED_ENVELOPE,
                f"events[{i}].protocol_version != batch.protocol_version "
                f"(禁止混装, 协议 §7.2)",
            )
        if ev.get("instance_id") != obj["instance_id"]:
            raise ReportingProtocolError(
                ReportingErrorCode.MALFORMED_ENVELOPE,
                f"events[{i}].instance_id != batch.instance_id "
                f"(禁止混装, 协议 §7.2)",
            )
        if ev.get("startup_epoch") != obj["startup_epoch"]:
            raise ReportingProtocolError(
                ReportingErrorCode.MALFORMED_ENVELOPE,
                f"events[{i}].startup_epoch != batch.startup_epoch "
                f"(禁止混装, 协议 §7.2)",
            )
        # 单 envelope 大小检查 (V1 BUG 收口后 ENVELOPE_TOO_LARGE)
        ev_raw = json.dumps(ev, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(ev_raw) > ENVELOPE_MAX_SIZE_BYTES:
            raise ReportingProtocolError(
                ReportingErrorCode.ENVELOPE_TOO_LARGE,
                f"events[{i}] exceeds {ENVELOPE_MAX_SIZE_BYTES} bytes "
                f"(actual: {len(ev_raw)})",
            )
    # 10. dropped_count int64, ≥ 0
    _validate_int64("dropped_count", obj["dropped_count"])


def encode_batch(batch: ReportingBatch) -> bytes:
    """ReportingBatch (8 字段) → 严格 JSON bytes.

    Raises:
        ReportingProtocolError: 字段不合法 / 超出 size / 混装
    """
    if batch.protocol_version != PROTOCOL_VERSION:
        raise ReportingProtocolError(
            ReportingErrorCode.PROTOCOL_VERSION_MISMATCH,
            f"batch.protocol_version must be {PROTOCOL_VERSION!r}",
        )
    if not (1 <= len(batch.events) <= BATCH_MAX_EVENTS):
        raise ReportingProtocolError(
            ReportingErrorCode.MALFORMED_ENVELOPE,
            f"events.length must be in [1, {BATCH_MAX_EVENTS}], "
            f"got {len(batch.events)}",
        )
    events_json = []
    for ev in batch.events:
        ev_obj = {
            "protocol_version": ev.protocol_version,
            "event_kind": ev.event_kind,
            "event_payload": ev.event_payload,
            "instance_id": ev.instance_id,
            "startup_epoch": ev.startup_epoch,
            "sequence": ev.sequence,
            "captured_at": ev.captured_at,
        }
        events_json.append(ev_obj)
    obj = {
        "protocol_version": batch.protocol_version,
        "instance_id": batch.instance_id,
        "startup_epoch": batch.startup_epoch,
        "batch_id": batch.batch_id,
        "sent_at": batch.sent_at,
        "events": events_json,
        "dropped_count": batch.dropped_count,
    }
    raw = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(raw) > BATCH_MAX_SIZE_BYTES:
        raise ReportingProtocolError(
            ReportingErrorCode.BATCH_TOO_LARGE,
            f"batch exceeds {BATCH_MAX_SIZE_BYTES} bytes (actual: {len(raw)})",
        )
    return raw


def decode_batch(raw: bytes) -> ReportingBatch:
    """严格 JSON bytes → ReportingBatch (8 字段).

    Raises:
        ReportingProtocolError: 任何字段不满足 V1 冻结 schema
    """
    if len(raw) > BATCH_MAX_SIZE_BYTES:
        raise ReportingProtocolError(
            ReportingErrorCode.BATCH_TOO_LARGE,
            f"batch exceeds {BATCH_MAX_SIZE_BYTES} bytes (actual: {len(raw)})",
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
            "batch must be a JSON object",
        )
    _validate_batch_dict(obj)
    events = [
        ReportingEnvelope(
            protocol_version=ev["protocol_version"],
            event_kind=ev["event_kind"],
            event_payload=ev["event_payload"],
            instance_id=ev["instance_id"],
            startup_epoch=ev["startup_epoch"],
            sequence=ev["sequence"],
            captured_at=ev["captured_at"],
        )
        for ev in obj["events"]
    ]
    return ReportingBatch(
        protocol_version=obj["protocol_version"],
        instance_id=obj["instance_id"],
        startup_epoch=obj["startup_epoch"],
        batch_id=obj["batch_id"],
        sent_at=obj["sent_at"],
        events=events,
        dropped_count=obj["dropped_count"],
    )


# ---------------------------------------------------------------------------
# Ack (5 字段) 校验 + 序列化
# ---------------------------------------------------------------------------


def _validate_ack_dict(obj: dict[str, Any]) -> None:
    missing = _REQUIRED_ACK_FIELDS - set(obj.keys())
    if missing:
        raise ReportingProtocolError(
            ReportingErrorCode.MALFORMED_ENVELOPE,
            f"ack missing required fields: {sorted(missing)}",
        )
    unknown = set(obj.keys()) - _REQUIRED_ACK_FIELDS
    if unknown:
        raise ReportingProtocolError(
            ReportingErrorCode.MALFORMED_ENVELOPE,
            f"ack unknown fields not allowed: {sorted(unknown)}",
        )
    _validate_protocol_version(obj)
    _validate_uuid("batch_id", obj["batch_id"])
    _validate_iso_utc_micro("received_at", obj["received_at"])
    # ack_sequences 必须是 array, length 必须为 1 (协议 §9.2)
    seqs = obj["ack_sequences"]
    if not isinstance(seqs, list) or len(seqs) != 1:
        raise ReportingProtocolError(
            ReportingErrorCode.MALFORMED_ENVELOPE,
            f"ack_sequences must be a JSON array of length 1, got {type(seqs).__name__} "
            f"of length {len(seqs) if isinstance(seqs, list) else 'N/A'}",
        )
    seq = seqs[0]
    if not isinstance(seq, dict):
        raise ReportingProtocolError(
            ReportingErrorCode.MALFORMED_ENVELOPE,
            "ack_sequences[0] must be a JSON object",
        )
    _validate_uuid("ack_sequences[0].instance_id", seq.get("instance_id"))
    _validate_int64("ack_sequences[0].startup_epoch", seq.get("startup_epoch"))
    _validate_int64(
        "ack_sequences[0].max_contiguous_sequence",
        seq.get("max_contiguous_sequence"),
    )
    _validate_int64("duplicate_count", obj["duplicate_count"])


def encode_ack(ack: AckEnvelope) -> bytes:
    """AckEnvelope → 严格 JSON bytes."""
    if ack.protocol_version != PROTOCOL_VERSION:
        raise ReportingProtocolError(
            ReportingErrorCode.PROTOCOL_VERSION_MISMATCH,
            f"ack.protocol_version must be {PROTOCOL_VERSION!r}",
        )
    if len(ack.ack_sequences) != 1:
        raise ReportingProtocolError(
            ReportingErrorCode.MALFORMED_ENVELOPE,
            f"ack_sequences must be length 1, got {len(ack.ack_sequences)}",
        )
    obj = {
        "protocol_version": ack.protocol_version,
        "batch_id": ack.batch_id,
        "received_at": ack.received_at,
        "ack_sequences": [
            {
                "instance_id": seq.instance_id,
                "startup_epoch": seq.startup_epoch,
                "max_contiguous_sequence": seq.max_contiguous_sequence,
            }
            for seq in ack.ack_sequences
        ],
        "duplicate_count": ack.duplicate_count,
    }
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def decode_ack(raw: bytes) -> AckEnvelope:
    """严格 JSON bytes → AckEnvelope."""
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
            "ack must be a JSON object",
        )
    _validate_ack_dict(obj)
    return AckEnvelope(
        protocol_version=obj["protocol_version"],
        batch_id=obj["batch_id"],
        received_at=obj["received_at"],
        ack_sequences=[
            AckSequence(
                instance_id=obj["ack_sequences"][0]["instance_id"],
                startup_epoch=obj["ack_sequences"][0]["startup_epoch"],
                max_contiguous_sequence=obj["ack_sequences"][0]["max_contiguous_sequence"],
            )
        ],
        duplicate_count=obj["duplicate_count"],
    )


# ---------------------------------------------------------------------------
# Error envelope (协议 transport §6) 校验 + 序列化
# ---------------------------------------------------------------------------


def _validate_error_dict(obj: dict[str, Any]) -> None:
    missing = _REQUIRED_ERROR_FIELDS - set(obj.keys())
    if missing:
        raise ReportingProtocolError(
            ReportingErrorCode.MALFORMED_ENVELOPE,
            f"error missing required fields: {sorted(missing)}",
        )
    unknown = set(obj.keys()) - _REQUIRED_ERROR_FIELDS
    if unknown:
        raise ReportingProtocolError(
            ReportingErrorCode.MALFORMED_ENVELOPE,
            f"error unknown fields not allowed: {sorted(unknown)}",
        )
    _validate_protocol_version(obj)
    try:
        ReportingErrorCode(obj["error_code"])
    except ValueError as e:
        raise ReportingProtocolError(
            ReportingErrorCode.MALFORMED_ENVELOPE,
            f"unknown error_code: {obj['error_code']!r}",
        ) from e
    if not isinstance(obj["message"], str):
        raise ReportingProtocolError(
            ReportingErrorCode.MALFORMED_ENVELOPE,
            "message must be string",
        )
    if len(obj["message"].encode("utf-8")) > ERROR_MESSAGE_MAX_LEN:
        raise ReportingProtocolError(
            ReportingErrorCode.MALFORMED_ENVELOPE,
            f"message exceeds {ERROR_MESSAGE_MAX_LEN} bytes",
        )
    if obj["details"] is not None and not isinstance(obj["details"], dict):
        raise ReportingProtocolError(
            ReportingErrorCode.MALFORMED_ENVELOPE,
            "details must be a JSON object or null",
        )


def encode_error_envelope(error: ErrorEnvelope) -> bytes:
    """ErrorEnvelope → 严格 JSON bytes."""
    if error.protocol_version != PROTOCOL_VERSION:
        raise ReportingProtocolError(
            ReportingErrorCode.PROTOCOL_VERSION_MISMATCH,
            f"error.protocol_version must be {PROTOCOL_VERSION!r}",
        )
    obj = {
        "protocol_version": error.protocol_version,
        "error_code": error.error_code,
        "message": error.message,
        "details": (
            None if error.details is None
            else {
                k: v for k, v in {
                    "field": error.details.field,
                    "got_type": error.details.got_type,
                }.items() if v is not None
            }
        ),
    }
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def decode_error_envelope(raw: bytes) -> ErrorEnvelope:
    """严格 JSON bytes → ErrorEnvelope."""
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
            "error must be a JSON object",
        )
    _validate_error_dict(obj)
    details = None
    if obj["details"] is not None:
        details = ErrorDetails(
            field=obj["details"].get("field"),
            got_type=obj["details"].get("got_type"),
        )
    return ErrorEnvelope(
        protocol_version=obj["protocol_version"],
        error_code=obj["error_code"],
        message=obj["message"],
        details=details,
    )


__all__ = [
    "BATCH_MAX_EVENTS",
    "BATCH_MAX_SIZE_BYTES",
    "ENVELOPE_MAX_SIZE_BYTES",
    "PROTOCOL_VERSION",
    "ReportingEnvelope",
    "ReportingProtocolError",
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

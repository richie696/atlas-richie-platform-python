"""Atlas Richie Agent Reporting Protocol V1 — codec 单测 (DRAFT, 1:1 镜像).

1:1 镜像 ``docs/protocol/上报协议-01-envelope-v1.md`` + ``-02-transport-v1.md``.

V1 协议 BUG 收口 (richie696 2026-09-13) codec 行为锁定. 任何 V1.x spec
revision 必须同步更新本测试.
"""

from __future__ import annotations

import json
import uuid

import pytest

from atlas_richie.contracts.reporting.v1 import (
    AUTH_TOKEN_MIN_LEN,
    AckEnvelope,
    AckSequence,
    BATCH_MAX_EVENTS,
    BATCH_MAX_SIZE_BYTES,
    ENVELOPE_MAX_SIZE_BYTES,
    ErrorDetails,
    ErrorEnvelope,
    ExecResult,
    HealthClass,
    PROTOCOL_VERSION,
    ReasonClass,
    ReportingBatch,
    ReportingEnvelope,
    ReportingErrorCode,
    ReportingEventKind,
    ReportingProtocolError,
    X_ATLAS_REPORTING_TOKEN_HEADER,
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

# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


def _valid_envelope(**overrides) -> dict:
    obj = {
        "protocol_version": PROTOCOL_VERSION,
        "event_kind": "RULE_SOURCE_ACTIVATED",
        "event_payload": {
            "source_id": "nacos-prod",
            "rule_version_epoch": 1,
            "rule_version_revision": 0,
            "rule_version_checksum": "sha256:" + "a" * 64,
        },
        "instance_id": str(uuid.uuid4()),
        "startup_epoch": 0,
        "sequence": 1,
        "captured_at": "2026-09-13T10:00:00.123456Z",
    }
    obj.update(overrides)
    return obj


def _valid_envelope_obj(**overrides) -> ReportingEnvelope:
    d = _valid_envelope(**overrides)
    return ReportingEnvelope(
        protocol_version=d["protocol_version"],
        event_kind=d["event_kind"],
        event_payload=d["event_payload"],
        instance_id=d["instance_id"],
        startup_epoch=d["startup_epoch"],
        sequence=d["sequence"],
        captured_at=d["captured_at"],
    )


def _valid_batch(**overrides) -> dict:
    ev = _valid_envelope()
    obj = {
        "protocol_version": PROTOCOL_VERSION,
        "instance_id": ev["instance_id"],
        "startup_epoch": ev["startup_epoch"],
        "batch_id": str(uuid.uuid4()),
        "sent_at": "2026-09-13T10:00:00.123456Z",
        "events": [ev],
        "dropped_count": 0,
    }
    obj.update(overrides)
    return obj


def _valid_batch_obj(**overrides) -> ReportingBatch:
    d = _valid_batch(**overrides)
    return ReportingBatch(
        protocol_version=d["protocol_version"],
        instance_id=d["instance_id"],
        startup_epoch=d["startup_epoch"],
        batch_id=d["batch_id"],
        sent_at=d["sent_at"],
        events=[_valid_envelope_obj(
            instance_id=d["instance_id"],
            startup_epoch=d["startup_epoch"],
        )],
        dropped_count=d["dropped_count"],
    )


# ---------------------------------------------------------------------------
# 1. 常量 + 枚举冻结 (V1 DRAFT, 7 字段 / 6 event_kind / 11 错误码 /
#    7 ReasonClass / 3 HealthClass / 3 ExecResult)
# ---------------------------------------------------------------------------


def test_protocol_version_constant():
    assert PROTOCOL_VERSION == "atlas-richie.reporting/v1"


def test_envelope_max_size_is_16kib():
    assert ENVELOPE_MAX_SIZE_BYTES == 16 * 1024


def test_batch_max_size_is_64kib():
    assert BATCH_MAX_SIZE_BYTES == 64 * 1024


def test_batch_max_events_is_256():
    assert BATCH_MAX_EVENTS == 256


def test_event_kind_has_6_values():
    assert len(ReportingEventKind) == 6
    assert {k.value for k in ReportingEventKind} == {
        "RULE_SOURCE_ACTIVATED",
        "RULE_SOURCE_STALE",
        "RULE_SOURCE_DEGRADED",
        "RULE_APPLIED",
        "RULE_BLOCKED",
        "RULE_FAILED",
    }


def test_health_class_has_3_values():
    assert len(HealthClass) == 3
    assert {c.value for c in HealthClass} == {"STALE", "DEGRADED", "DISCONNECTED"}


def test_reason_class_has_7_frozen_values():
    # V1 ReasonClass 7 冻结值 (协议 BUG 收口: 冻结枚举, 不再字符串)
    assert len(ReasonClass) == 7
    assert {c.value for c in ReasonClass} == {
        "EMPTY_DATA_ID",
        "NETWORK_TIMEOUT",
        "NETWORK_UNAVAILABLE",
        "AUTH_FAILED",
        "DECODE_FAILED",
        "STATE_INVALID",
        "UNKNOWN",
    }


def test_exec_result_has_3_values():
    assert len(ExecResult) == 3
    assert {c.value for c in ExecResult} == {"APPLIED", "BLOCKED", "FAILED"}


def test_error_code_has_11_values():
    # V1 11 错误码 (协议 BUG 收口新增 ENVELOPE_TOO_LARGE + BATCH_TOO_LARGE)
    assert len(ReportingErrorCode) == 11
    assert ReportingErrorCode.ENVELOPE_TOO_LARGE in ReportingErrorCode
    assert ReportingErrorCode.BATCH_TOO_LARGE in ReportingErrorCode


def test_x_atlas_reporting_token_header_constant():
    assert X_ATLAS_REPORTING_TOKEN_HEADER == "X-Atlas-Reporting-Token"


def test_auth_token_min_len():
    assert AUTH_TOKEN_MIN_LEN == 16


# ---------------------------------------------------------------------------
# 2. Envelope (7 字段) round-trip
# ---------------------------------------------------------------------------


def test_envelope_roundtrip():
    env = _valid_envelope_obj()
    raw = encode_envelope(env)
    decoded = decode_envelope(raw)
    assert decoded == env


def test_envelope_has_7_fields():
    # V1 协议 BUG 收口: 7 字段 (无 received_at)
    env = _valid_envelope_obj()
    raw = encode_envelope(env)
    obj = json.loads(raw)
    assert len(obj) == 7
    assert "received_at" not in obj  # 关键: received_at 不是 ingress 字段
    assert set(obj.keys()) == {
        "protocol_version", "event_kind", "event_payload",
        "instance_id", "startup_epoch", "sequence", "captured_at",
    }


def test_envelope_produces_strict_json_no_whitespace():
    raw = encode_envelope(_valid_envelope_obj())
    assert b" " not in raw


def test_decode_rejects_invalid_json():
    with pytest.raises(ReportingProtocolError) as e:
        decode_envelope(b"not-json")
    assert e.value.code is ReportingErrorCode.MALFORMED_ENVELOPE


def test_decode_rejects_non_object_json():
    with pytest.raises(ReportingProtocolError) as e:
        decode_envelope(b'"a string"')
    assert e.value.code is ReportingErrorCode.MALFORMED_ENVELOPE


# ---------------------------------------------------------------------------
# 3. protocol_version 校验
# ---------------------------------------------------------------------------


def test_decode_rejects_wrong_protocol_version():
    obj = _valid_envelope(protocol_version="atlas-richie.reporting/v0")
    with pytest.raises(ReportingProtocolError) as e:
        decode_envelope(json.dumps(obj).encode("utf-8"))
    assert e.value.code is ReportingErrorCode.PROTOCOL_VERSION_MISMATCH


def test_encode_rejects_wrong_protocol_version():
    env = _valid_envelope_obj(protocol_version="wrong/v1")
    with pytest.raises(ReportingProtocolError) as e:
        encode_envelope(env)
    assert e.value.code is ReportingErrorCode.PROTOCOL_VERSION_MISMATCH


# ---------------------------------------------------------------------------
# 4. 必填字段缺失 (7 字段)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("missing_field", [
    "protocol_version", "event_kind", "event_payload", "instance_id",
    "startup_epoch", "sequence", "captured_at",
])
def test_decode_rejects_missing_required_field(missing_field):
    obj = _valid_envelope()
    del obj[missing_field]
    with pytest.raises(ReportingProtocolError) as e:
        decode_envelope(json.dumps(obj).encode("utf-8"))
    assert e.value.code is ReportingErrorCode.MALFORMED_ENVELOPE


def test_decode_rejects_received_at_in_ingress_envelope():
    # V1 协议 BUG 收口: received_at 不是 ingress 字段, 拒绝
    obj = _valid_envelope(received_at="2026-09-13T10:00:00.456789Z")
    with pytest.raises(ReportingProtocolError) as e:
        decode_envelope(json.dumps(obj).encode("utf-8"))
    assert e.value.code is ReportingErrorCode.MALFORMED_ENVELOPE
    assert "received_at" in e.value.message


# ---------------------------------------------------------------------------
# 5. 未知字段拒绝 (V1 严格)
# ---------------------------------------------------------------------------


def test_decode_rejects_unknown_field():
    obj = _valid_envelope(unknown_field="x")
    with pytest.raises(ReportingProtocolError) as e:
        decode_envelope(json.dumps(obj).encode("utf-8"))
    assert e.value.code is ReportingErrorCode.MALFORMED_ENVELOPE


# ---------------------------------------------------------------------------
# 6. event_kind 枚举校验
# ---------------------------------------------------------------------------


def test_decode_rejects_unknown_event_kind():
    obj = _valid_envelope(event_kind="MAGIC_EVENT")
    with pytest.raises(ReportingProtocolError) as e:
        decode_envelope(json.dumps(obj).encode("utf-8"))
    assert e.value.code is ReportingErrorCode.UNKNOWN_EVENT_KIND


# ---------------------------------------------------------------------------
# 7. UUID / 时间 / checksum / int64 校验
# ---------------------------------------------------------------------------


def test_decode_rejects_non_uuid_v4_instance_id():
    obj = _valid_envelope(instance_id="not-a-uuid")
    with pytest.raises(ReportingProtocolError) as e:
        decode_envelope(json.dumps(obj).encode("utf-8"))
    assert e.value.code is ReportingErrorCode.MALFORMED_ENVELOPE


@pytest.mark.parametrize("bad_time_field", ["captured_at"])
def test_decode_rejects_non_iso8601_utc_micro(bad_time_field):
    obj = _valid_envelope(**{bad_time_field: "2026-09-13 10:00:00"})
    with pytest.raises(ReportingProtocolError) as e:
        decode_envelope(json.dumps(obj).encode("utf-8"))
    assert e.value.code is ReportingErrorCode.MALFORMED_ENVELOPE


def test_decode_rejects_int64_out_of_range():
    # 2^53 + 1 (超 JavaScript 安全整数)
    obj = _valid_envelope(startup_epoch=2**53 + 1)
    with pytest.raises(ReportingProtocolError) as e:
        decode_envelope(json.dumps(obj).encode("utf-8"))
    assert e.value.code is ReportingErrorCode.MALFORMED_ENVELOPE


def test_decode_rejects_non_int_startup_epoch():
    obj = _valid_envelope(startup_epoch="not-int")
    with pytest.raises(ReportingProtocolError) as e:
        decode_envelope(json.dumps(obj).encode("utf-8"))
    assert e.value.code is ReportingErrorCode.MALFORMED_ENVELOPE


def test_decode_rejects_checksum_without_sha256_prefix():
    obj = _valid_envelope()
    obj["event_payload"]["rule_version_checksum"] = "md5:" + "a" * 64
    with pytest.raises(ReportingProtocolError) as e:
        decode_envelope(json.dumps(obj).encode("utf-8"))
    assert e.value.code is ReportingErrorCode.PAYLOAD_SCHEMA_MISMATCH


# ---------------------------------------------------------------------------
# 8. size 上限 (新增 ENVELOPE_TOO_LARGE)
# ---------------------------------------------------------------------------


def test_decode_rejects_oversized_envelope():
    raw = b'{"x": "' + b'a' * (ENVELOPE_MAX_SIZE_BYTES + 100) + b'"}'
    with pytest.raises(ReportingProtocolError) as e:
        decode_envelope(raw)
    assert e.value.code is ReportingErrorCode.ENVELOPE_TOO_LARGE


# ---------------------------------------------------------------------------
# 9. Per-kind payload 校验
# ---------------------------------------------------------------------------


def test_validate_payload_rule_source_activated_success():
    payload = {
        "source_id": "nacos-prod",
        "rule_version_epoch": 1,
        "rule_version_revision": 0,
        "rule_version_checksum": "sha256:" + "a" * 64,
    }
    validate_payload("RULE_SOURCE_ACTIVATED", payload)


def test_validate_payload_rule_source_activated_rejects_unknown_field():
    payload = {
        "source_id": "nacos-prod",
        "rule_version_epoch": 1,
        "rule_version_revision": 0,
        "rule_version_checksum": "sha256:" + "a" * 64,
        "extra": "x",
    }
    with pytest.raises(ReportingProtocolError) as e:
        validate_payload("RULE_SOURCE_ACTIVATED", payload)
    assert e.value.code is ReportingErrorCode.PAYLOAD_SCHEMA_MISMATCH


def test_validate_payload_rule_source_health_success():
    payload = {
        "source_id": "nacos-prod",
        "health_class": "STALE",
        "reason_class": "EMPTY_DATA_ID",
        "reason_message": "nacos data_id returns empty",
        "rule_version_epoch": 1,
        "rule_version_revision": 0,
        "rule_version_checksum": "sha256:" + "a" * 64,
    }
    validate_payload("RULE_SOURCE_STALE", payload)


def test_validate_payload_rule_source_health_no_snapshot_success():
    # V1 协议 BUG 收口: Health 支持"无有效规则快照" 3 rule_version_*
    # 字段成组可选, 全部省略
    payload = {
        "source_id": "nacos-prod",
        "health_class": "DISCONNECTED",
        "reason_class": "NETWORK_UNAVAILABLE",
    }
    validate_payload("RULE_SOURCE_DEGRADED", payload)


def test_validate_payload_rule_source_health_partial_version_rejected():
    # 3 rule_version_* 字段成组可选: 同时出现或同时省略
    payload = {
        "source_id": "nacos-prod",
        "health_class": "STALE",
        "reason_class": "EMPTY_DATA_ID",
        "rule_version_epoch": 1,  # 只给 1 个, 其它 2 个缺
    }
    with pytest.raises(ReportingProtocolError) as e:
        validate_payload("RULE_SOURCE_STALE", payload)
    assert e.value.code is ReportingErrorCode.PAYLOAD_SCHEMA_MISMATCH


@pytest.mark.parametrize("bad_health", ["stale", "MAGIC"])
def test_validate_payload_rule_source_health_rejects_bad_health_class(bad_health):
    payload = {
        "source_id": "nacos-prod",
        "health_class": bad_health,
        "reason_class": "EMPTY_DATA_ID",
    }
    with pytest.raises(ReportingProtocolError) as e:
        validate_payload("RULE_SOURCE_STALE", payload)
    assert e.value.code is ReportingErrorCode.PAYLOAD_SCHEMA_MISMATCH


@pytest.mark.parametrize("bad_reason", ["BAD_CLASS", "EXCEPTION_TYPE", "magic"])
def test_validate_payload_rule_source_health_rejects_bad_reason_class(bad_reason):
    # V1 协议 BUG 收口: ReasonClass 冻结枚举, 拒绝任意字符串
    payload = {
        "source_id": "nacos-prod",
        "health_class": "STALE",
        "reason_class": bad_reason,
    }
    with pytest.raises(ReportingProtocolError) as e:
        validate_payload("RULE_SOURCE_STALE", payload)
    assert e.value.code is ReportingErrorCode.PAYLOAD_SCHEMA_MISMATCH


def test_validate_payload_rule_source_health_reason_message_too_long():
    payload = {
        "source_id": "nacos-prod",
        "health_class": "STALE",
        "reason_class": "EMPTY_DATA_ID",
        "reason_message": "x" * 65,
    }
    with pytest.raises(ReportingProtocolError) as e:
        validate_payload("RULE_SOURCE_STALE", payload)
    assert e.value.code is ReportingErrorCode.PAYLOAD_SCHEMA_MISMATCH


def test_validate_payload_rule_exec_applied_success():
    payload = {
        "source_id": "nacos-prod",
        "rule_id": "flow:/api/v1/users",
        "rule_version_epoch": 1,
        "rule_version_revision": 0,
        "rule_version_checksum": "sha256:" + "a" * 64,
        "exec_result": "APPLIED",
        "failure_class": None,
    }
    validate_payload("RULE_APPLIED", payload)


def test_validate_payload_rule_exec_failed_requires_failure_class():
    payload = {
        "source_id": "nacos-prod",
        "rule_id": "flow:/api/v1/users",
        "rule_version_epoch": 1,
        "rule_version_revision": 0,
        "rule_version_checksum": "sha256:" + "a" * 64,
        "exec_result": "FAILED",
        "failure_class": None,
    }
    with pytest.raises(ReportingProtocolError) as e:
        validate_payload("RULE_FAILED", payload)
    assert e.value.code is ReportingErrorCode.PAYLOAD_SCHEMA_MISMATCH


def test_validate_payload_rule_exec_failed_with_reason_class():
    payload = {
        "source_id": "nacos-prod",
        "rule_id": "flow:/api/v1/users",
        "rule_version_epoch": 1,
        "rule_version_revision": 0,
        "rule_version_checksum": "sha256:" + "a" * 64,
        "exec_result": "FAILED",
        "failure_class": "DECODE_FAILED",
    }
    validate_payload("RULE_FAILED", payload)


@pytest.mark.parametrize("bad_result", ["applied", "MAGIC"])
def test_validate_payload_rule_exec_rejects_bad_exec_result(bad_result):
    payload = {
        "source_id": "nacos-prod",
        "rule_id": "flow:/api/v1/users",
        "rule_version_epoch": 1,
        "rule_version_revision": 0,
        "rule_version_checksum": "sha256:" + "a" * 64,
        "exec_result": bad_result,
        "failure_class": None,
    }
    with pytest.raises(ReportingProtocolError) as e:
        validate_payload("RULE_APPLIED", payload)
    assert e.value.code is ReportingErrorCode.PAYLOAD_SCHEMA_MISMATCH


def test_validate_payload_rule_exec_applied_rejects_non_null_failure_class():
    payload = {
        "source_id": "nacos-prod",
        "rule_id": "flow:/api/v1/users",
        "rule_version_epoch": 1,
        "rule_version_revision": 0,
        "rule_version_checksum": "sha256:" + "a" * 64,
        "exec_result": "APPLIED",
        "failure_class": "DECODE_FAILED",  # 错: APPLIED 必须 None
    }
    with pytest.raises(ReportingProtocolError) as e:
        validate_payload("RULE_APPLIED", payload)
    assert e.value.code is ReportingErrorCode.PAYLOAD_SCHEMA_MISMATCH


# ---------------------------------------------------------------------------
# 10. Batch (7 字段) round-trip + 强制单一 identity
# ---------------------------------------------------------------------------


def test_batch_roundtrip():
    batch = _valid_batch_obj()
    raw = encode_batch(batch)
    decoded = decode_batch(raw)
    assert decoded == batch


def test_batch_has_7_fields():
    batch = _valid_batch_obj()
    raw = encode_batch(batch)
    obj = json.loads(raw)
    assert len(obj) == 7
    assert set(obj.keys()) == {
        "protocol_version", "instance_id", "startup_epoch", "batch_id",
        "sent_at", "events", "dropped_count",
    }


def test_batch_rejects_events_count_zero():
    batch = _valid_batch_obj()
    # 强制 length ≥ 1
    batch_empty = ReportingBatch(
        protocol_version=batch.protocol_version,
        instance_id=batch.instance_id,
        startup_epoch=batch.startup_epoch,
        batch_id=batch.batch_id,
        sent_at=batch.sent_at,
        events=[],
        dropped_count=0,
    )
    with pytest.raises(ReportingProtocolError) as e:
        encode_batch(batch_empty)
    assert e.value.code is ReportingErrorCode.MALFORMED_ENVELOPE


def test_batch_rejects_events_count_too_many():
    # 构造 257 个 events, 应拒绝
    events = [_valid_envelope_obj() for _ in range(BATCH_MAX_EVENTS + 1)]
    batch = ReportingBatch(
        protocol_version=PROTOCOL_VERSION,
        instance_id=str(uuid.uuid4()),
        startup_epoch=0,
        batch_id=str(uuid.uuid4()),
        sent_at="2026-09-13T10:00:00.123456Z",
        events=events,
        dropped_count=0,
    )
    with pytest.raises(ReportingProtocolError) as e:
        encode_batch(batch)
    assert e.value.code is ReportingErrorCode.MALFORMED_ENVELOPE


def test_batch_rejects_mixed_instance_id():
    # 强制单一 identity: events[0].instance_id 跟 batch.instance_id 不同 → 拒绝
    obj = _valid_batch()
    obj["events"][0]["instance_id"] = str(uuid.uuid4())  # 改成不同
    with pytest.raises(ReportingProtocolError) as e:
        decode_batch(json.dumps(obj).encode("utf-8"))
    assert e.value.code is ReportingErrorCode.MALFORMED_ENVELOPE
    assert "instance_id" in e.value.message


def test_batch_rejects_mixed_startup_epoch():
    obj = _valid_batch()
    obj["events"][0]["startup_epoch"] = 999  # 跟 batch 不同
    with pytest.raises(ReportingProtocolError) as e:
        decode_batch(json.dumps(obj).encode("utf-8"))
    assert e.value.code is ReportingErrorCode.MALFORMED_ENVELOPE
    assert "startup_epoch" in e.value.message


def test_batch_rejects_mixed_protocol_version():
    obj = _valid_batch()
    obj["events"][0]["protocol_version"] = "atlas-richie.reporting/v0"
    with pytest.raises(ReportingProtocolError) as e:
        decode_batch(json.dumps(obj).encode("utf-8"))
    assert e.value.code is ReportingErrorCode.MALFORMED_ENVELOPE


def test_batch_decode_rejects_oversized_batch():
    raw = b'{"x": "' + b'a' * (BATCH_MAX_SIZE_BYTES + 100) + b'"}'
    with pytest.raises(ReportingProtocolError) as e:
        decode_batch(raw)
    assert e.value.code is ReportingErrorCode.BATCH_TOO_LARGE


def test_batch_decode_rejects_event_too_large():
    # 构造一个 batch, 单 event 超过 16 KiB
    obj = _valid_batch()
    obj["events"][0]["captured_at"] = "x" * 17000  # 超出 16 KiB 单 envelope
    raw = json.dumps(obj).encode("utf-8")
    with pytest.raises(ReportingProtocolError) as e:
        decode_batch(raw)
    # 单 envelope 超 16 KiB 触发 ENVELOPE_TOO_LARGE
    assert e.value.code is ReportingErrorCode.ENVELOPE_TOO_LARGE


# ---------------------------------------------------------------------------
# 11. Ack (5 字段) round-trip
# ---------------------------------------------------------------------------


def test_ack_roundtrip():
    ack = AckEnvelope(
        protocol_version=PROTOCOL_VERSION,
        batch_id=str(uuid.uuid4()),
        received_at="2026-09-13T10:00:00.456789Z",
        ack_sequences=[
            AckSequence(
                instance_id=str(uuid.uuid4()),
                startup_epoch=0,
                max_contiguous_sequence=100,
            )
        ],
        duplicate_count=0,
    )
    raw = encode_ack(ack)
    decoded = decode_ack(raw)
    assert decoded == ack


def test_ack_has_5_fields():
    ack = AckEnvelope(
        protocol_version=PROTOCOL_VERSION,
        batch_id=str(uuid.uuid4()),
        received_at="2026-09-13T10:00:00.456789Z",
        ack_sequences=[
            AckSequence(instance_id=str(uuid.uuid4()), startup_epoch=0, max_contiguous_sequence=1)
        ],
        duplicate_count=0,
    )
    raw = encode_ack(ack)
    obj = json.loads(raw)
    assert len(obj) == 5
    # received_at 必须在 ack 中 (Collector 写入)
    assert "received_at" in obj


def test_ack_decode_rejects_ack_sequences_not_length_1():
    obj = {
        "protocol_version": PROTOCOL_VERSION,
        "batch_id": str(uuid.uuid4()),
        "received_at": "2026-09-13T10:00:00.456789Z",
        "ack_sequences": [],  # length 0
        "duplicate_count": 0,
    }
    with pytest.raises(ReportingProtocolError) as e:
        decode_ack(json.dumps(obj).encode("utf-8"))
    assert e.value.code is ReportingErrorCode.MALFORMED_ENVELOPE


# ---------------------------------------------------------------------------
# 12. Error envelope
# ---------------------------------------------------------------------------


def test_error_envelope_roundtrip():
    err = ErrorEnvelope(
        protocol_version=PROTOCOL_VERSION,
        error_code="MALFORMED_ENVELOPE",
        message="test",
        details=ErrorDetails(field="sequence", got_type="string"),
    )
    raw = encode_error_envelope(err)
    decoded = decode_error_envelope(raw)
    assert decoded == err


def test_error_envelope_decode_rejects_unknown_error_code():
    obj = {
        "protocol_version": PROTOCOL_VERSION,
        "error_code": "MAGIC",
        "message": "test",
        "details": None,
    }
    with pytest.raises(ReportingProtocolError) as e:
        decode_error_envelope(json.dumps(obj).encode("utf-8"))
    assert e.value.code is ReportingErrorCode.MALFORMED_ENVELOPE


# ---------------------------------------------------------------------------
# 13. payload dataclass 1:1 镜像验证
# ---------------------------------------------------------------------------


def test_payload_dataclasses_are_frozen_and_slots():
    from atlas_richie.contracts.reporting.v1.payloads import (
        RuleExecPayload,
        RuleSourceActivatedPayload,
        RuleSourceHealthPayload,
    )
    for cls in (RuleSourceActivatedPayload, RuleSourceHealthPayload, RuleExecPayload):
        assert cls.__dataclass_params__.frozen is True
        assert cls.__dataclass_params__.slots is True


def test_envelope_dataclass_is_frozen_and_slots():
    assert ReportingEnvelope.__dataclass_params__.frozen is True
    assert ReportingEnvelope.__dataclass_params__.slots is True


def test_batch_dataclass_is_frozen_and_slots():
    assert ReportingBatch.__dataclass_params__.frozen is True
    assert ReportingBatch.__dataclass_params__.slots is True


def test_ack_dataclass_is_frozen_and_slots():
    assert AckEnvelope.__dataclass_params__.frozen is True
    assert AckEnvelope.__dataclass_params__.slots is True


def test_error_dataclass_is_frozen_and_slots():
    assert ErrorEnvelope.__dataclass_params__.frozen is True
    assert ErrorEnvelope.__dataclass_params__.slots is True
    assert ErrorDetails.__dataclass_params__.frozen is True
    assert ErrorDetails.__dataclass_params__.slots is True

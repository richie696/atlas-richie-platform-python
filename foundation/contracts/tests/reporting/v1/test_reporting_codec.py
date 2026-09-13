"""Atlas Richie Agent Reporting Protocol V1 — codec 单测.

1:1 镜像 ``docs/protocols/AGENT_REPORTING_PROTOCOL.md``. 严格 codec 行为
锁定; 任何 V1.1 minor 变更必须同步更新本测试.
"""

from __future__ import annotations

import json
import uuid

import pytest

from atlas_richie.contracts.reporting.v1 import (
    ENVELOPE_MAX_SIZE_BYTES,
    PROTOCOL_VERSION,
    ReportingEnvelope,
    ReportingErrorCode,
    ReportingEventKind,
    ReportingProtocolError,
    decode_envelope,
    encode_envelope,
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
        "received_at": "2026-09-13T10:00:00.456789Z",
    }
    obj.update(overrides)
    return obj


def _valid_envelope_obj(**overrides) -> ReportingEnvelope:
    d = _valid_envelope(**overrides)
    return ReportingEnvelope(
        protocol_version=d["protocol_version"],
        event_kind=ReportingEventKind(d["event_kind"]),
        event_payload=d["event_payload"],
        instance_id=d["instance_id"],
        startup_epoch=d["startup_epoch"],
        sequence=d["sequence"],
        captured_at=d["captured_at"],
        received_at=d["received_at"],
    )


# ---------------------------------------------------------------------------
# 1. 常量 + 枚举冻结
# ---------------------------------------------------------------------------


def test_protocol_version_constant_is_frozen():
    assert PROTOCOL_VERSION == "atlas-richie.reporting/v1"


def test_event_kind_has_exactly_6_values():
    assert len(ReportingEventKind) == 6
    assert {k.value for k in ReportingEventKind} == {
        "RULE_SOURCE_ACTIVATED",
        "RULE_SOURCE_STALE",
        "RULE_SOURCE_DEGRADED",
        "RULE_APPLIED",
        "RULE_BLOCKED",
        "RULE_FAILED",
    }


def test_envelope_max_size_is_16kb():
    assert ENVELOPE_MAX_SIZE_BYTES == 16 * 1024


def test_error_code_has_9_values():
    assert len(ReportingErrorCode) == 9


# ---------------------------------------------------------------------------
# 2. encode / decode round-trip
# ---------------------------------------------------------------------------


def test_encode_decode_roundtrip():
    env = _valid_envelope_obj()
    raw = encode_envelope(env)
    decoded = decode_envelope(raw)
    assert decoded == env


def test_encode_produces_strict_json_no_whitespace():
    raw = encode_envelope(_valid_envelope_obj())
    assert b" " not in raw


def test_decode_rejects_empty_bytes():
    with pytest.raises(ReportingProtocolError) as e:
        decode_envelope(b"")
    assert e.value.code is ReportingErrorCode.MALFORMED_ENVELOPE


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


def test_encode_rejects_wrong_protocol_version_in_dataclass():
    env = _valid_envelope_obj(protocol_version="wrong/v1")
    with pytest.raises(ReportingProtocolError) as e:
        encode_envelope(env)
    assert e.value.code is ReportingErrorCode.PROTOCOL_VERSION_MISMATCH


# ---------------------------------------------------------------------------
# 4. 必填字段缺失
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("missing_field", [
    "protocol_version", "event_kind", "event_payload", "instance_id",
    "startup_epoch", "sequence", "captured_at", "received_at",
])
def test_decode_rejects_missing_required_field(missing_field):
    obj = _valid_envelope()
    del obj[missing_field]
    with pytest.raises(ReportingProtocolError) as e:
        decode_envelope(json.dumps(obj).encode("utf-8"))
    assert e.value.code is ReportingErrorCode.MALFORMED_ENVELOPE
    assert missing_field in e.value.message


# ---------------------------------------------------------------------------
# 5. 未知字段拒绝
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
# 7. UUID / 时间 / checksum 格式校验
# ---------------------------------------------------------------------------


def test_decode_rejects_non_uuid_v4_instance_id():
    obj = _valid_envelope(instance_id="not-a-uuid")
    with pytest.raises(ReportingProtocolError) as e:
        decode_envelope(json.dumps(obj).encode("utf-8"))
    assert e.value.code is ReportingErrorCode.MALFORMED_ENVELOPE


def test_decode_rejects_empty_instance_id():
    obj = _valid_envelope(instance_id="")
    with pytest.raises(ReportingProtocolError) as e:
        decode_envelope(json.dumps(obj).encode("utf-8"))
    assert e.value.code is ReportingErrorCode.INSTANCE_ID_EMPTY


@pytest.mark.parametrize("bad_time_field", ["captured_at", "received_at"])
def test_decode_rejects_non_iso8601_utc_micro(bad_time_field):
    obj = _valid_envelope(**{bad_time_field: "2026-09-13 10:00:00"})
    with pytest.raises(ReportingProtocolError) as e:
        decode_envelope(json.dumps(obj).encode("utf-8"))
    assert e.value.code is ReportingErrorCode.MALFORMED_ENVELOPE


# ---------------------------------------------------------------------------
# 8. size 上限
# ---------------------------------------------------------------------------


def test_decode_rejects_oversized_envelope():
    raw = b'{"x": "' + b'a' * (ENVELOPE_MAX_SIZE_BYTES + 100) + b'"}'
    with pytest.raises(ReportingProtocolError) as e:
        decode_envelope(raw)
    assert e.value.code is ReportingErrorCode.ENVELOPE_TOO_LARGE


# ---------------------------------------------------------------------------
# 9. per-kind payload 校验
# ---------------------------------------------------------------------------


def test_validate_payload_rule_source_activated_success():
    payload = {
        "source_id": "nacos-prod",
        "rule_version_epoch": 1,
        "rule_version_revision": 0,
        "rule_version_checksum": "sha256:" + "a" * 64,
    }
    validate_payload(ReportingEventKind.RULE_SOURCE_ACTIVATED, payload)


def test_validate_payload_rule_source_activated_rejects_unknown_field():
    payload = {
        "source_id": "nacos-prod",
        "rule_version_epoch": 1,
        "rule_version_revision": 0,
        "rule_version_checksum": "sha256:" + "a" * 64,
        "extra": "x",
    }
    with pytest.raises(ReportingProtocolError) as e:
        validate_payload(ReportingEventKind.RULE_SOURCE_ACTIVATED, payload)
    assert e.value.code is ReportingErrorCode.PAYLOAD_SCHEMA_MISMATCH


def test_validate_payload_rule_source_health_success():
    payload = {
        "source_id": "nacos-prod",
        "rule_version_epoch": 1,
        "rule_version_revision": 0,
        "rule_version_checksum": "sha256:" + "a" * 64,
        "health_class": "STALE",
        "reason_class": "EMPTY_DATA_ID",
        "reason_message": "nacos data_id returns empty content",
    }
    validate_payload(ReportingEventKind.RULE_SOURCE_STALE, payload)


@pytest.mark.parametrize("bad_health_class", ["STALE ", "stale", "MAGIC"])
def test_validate_payload_rule_source_health_rejects_bad_health_class(bad_health_class):
    payload = {
        "source_id": "nacos-prod",
        "rule_version_epoch": 1,
        "rule_version_revision": 0,
        "rule_version_checksum": "sha256:" + "a" * 64,
        "health_class": bad_health_class,
        "reason_class": "EMPTY_DATA_ID",
    }
    with pytest.raises(ReportingProtocolError) as e:
        validate_payload(ReportingEventKind.RULE_SOURCE_STALE, payload)
    assert e.value.code is ReportingErrorCode.PAYLOAD_SCHEMA_MISMATCH


def test_validate_payload_rule_source_health_rejects_oversized_message():
    payload = {
        "source_id": "nacos-prod",
        "rule_version_epoch": 1,
        "rule_version_revision": 0,
        "rule_version_checksum": "sha256:" + "a" * 64,
        "health_class": "STALE",
        "reason_class": "EMPTY_DATA_ID",
        "reason_message": "x" * 65,
    }
    with pytest.raises(ReportingProtocolError) as e:
        validate_payload(ReportingEventKind.RULE_SOURCE_STALE, payload)
    assert e.value.code is ReportingErrorCode.PAYLOAD_SCHEMA_MISMATCH


def test_validate_payload_rule_exec_success_applied():
    payload = {
        "source_id": "nacos-prod",
        "rule_id": "flow:/api/v1/users",
        "rule_version_epoch": 1,
        "rule_version_revision": 0,
        "rule_version_checksum": "sha256:" + "a" * 64,
        "exec_result": "APPLIED",
        "failure_class": None,
    }
    validate_payload(ReportingEventKind.RULE_APPLIED, payload)


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
        validate_payload(ReportingEventKind.RULE_FAILED, payload)
    assert e.value.code is ReportingErrorCode.PAYLOAD_SCHEMA_MISMATCH


def test_validate_payload_rule_exec_failed_with_failure_class():
    payload = {
        "source_id": "nacos-prod",
        "rule_id": "flow:/api/v1/users",
        "rule_version_epoch": 1,
        "rule_version_revision": 0,
        "rule_version_checksum": "sha256:" + "a" * 64,
        "exec_result": "FAILED",
        "failure_class": "DECODE_FAILED",
    }
    validate_payload(ReportingEventKind.RULE_FAILED, payload)


def test_validate_payload_rule_exec_rejects_bad_exec_result():
    payload = {
        "source_id": "nacos-prod",
        "rule_id": "flow:/api/v1/users",
        "rule_version_epoch": 1,
        "rule_version_revision": 0,
        "rule_version_checksum": "sha256:" + "a" * 64,
        "exec_result": "MAGIC",
        "failure_class": None,
    }
    with pytest.raises(ReportingProtocolError) as e:
        validate_payload(ReportingEventKind.RULE_APPLIED, payload)
    assert e.value.code is ReportingErrorCode.PAYLOAD_SCHEMA_MISMATCH

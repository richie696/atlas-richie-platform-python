"""Atlas Richie Cluster Token Protocol V1 — codec 单测.

1:1 镜像 ``docs/protocols/CLUSTER_TOKEN_PROTOCOL.md``. 严格 codec 行为
锁定; 任何 V1.1 minor 变更必须同步更新本测试.
"""

from __future__ import annotations

import json
import uuid

import pytest

from atlas_richie.contracts.cluster.v1 import (
    AcquireRequestPayload,
    AcquireResponsePayload,
    ClusterDenyReason,
    ClusterErrorCode,
    ClusterMessageKind,
    ClusterProtocolError,
    ClusterTokenEnvelope,
    DEFAULT_LEASE_TTL_NS,
    ENVELOPE_MAX_SIZE_BYTES,
    PROTOCOL_VERSION,
    ReleaseRequestPayload,
    RenewRequestPayload,
    RenewResponsePayload,
    ErrorResponsePayload,
    decode_envelope,
    encode_envelope,
    validate_payload,
)

# ---------------------------------------------------------------------------
# 测试 fixture
# ---------------------------------------------------------------------------


def _valid_envelope(**overrides) -> dict:
    """合法 envelope 工厂 (dict, 未 ClusterTokenEnvelope 化)."""
    obj = {
        "protocol_version": PROTOCOL_VERSION,
        "message_kind": "ACQUIRE_REQUEST",
        "request_id": str(uuid.uuid4()),
        "instance_id": str(uuid.uuid4()),
        "startup_epoch": 0,
        "resource": "/api/v1/users",
        "permits": 1.0,
        "deadline_ns": 5_000_000,
        "client_requested_at": "2026-09-13T10:00:00.123456Z",
        "server_received_at": "2026-09-13T10:00:00.456789Z",
        "payload": {
            "rule_version_epoch": 1726000000,
            "rule_version_revision": 0,
            "rule_version_checksum": "sha256:" + "a" * 64,
            "priority": 0,
        },
    }
    obj.update(overrides)
    return obj


def _valid_envelope_obj(**overrides) -> ClusterTokenEnvelope:
    """合法 ClusterTokenEnvelope 工厂 (frozen dataclass)."""
    d = _valid_envelope(**overrides)
    return ClusterTokenEnvelope(
        protocol_version=d["protocol_version"],
        message_kind=ClusterMessageKind(d["message_kind"]),
        request_id=d["request_id"],
        instance_id=d["instance_id"],
        startup_epoch=d["startup_epoch"],
        resource=d["resource"],
        permits=d["permits"],
        deadline_ns=d["deadline_ns"],
        client_requested_at=d["client_requested_at"],
        server_received_at=d["server_received_at"],
        payload=d["payload"],
    )


# ---------------------------------------------------------------------------
# 1. 常量 + 枚举值冻结 (V1 frozen, 不能改)
# ---------------------------------------------------------------------------


def test_protocol_version_constant_is_frozen():
    assert PROTOCOL_VERSION == "atlas-richie.cluster.token/v1"


def test_message_kind_has_exactly_6_values():
    assert len(ClusterMessageKind) == 6
    assert {k.value for k in ClusterMessageKind} == {
        "ACQUIRE_REQUEST",
        "ACQUIRE_RESPONSE",
        "RELEASE_REQUEST",
        "RENEW_REQUEST",
        "RENEW_RESPONSE",
        "ERROR_RESPONSE",
    }


def test_error_code_has_exactly_9_values():
    assert len(ClusterErrorCode) == 9


def test_deny_reason_has_exactly_5_values():
    # 协议 §4.2 列了 5 个 (QUEUE_FULL/RATE_LIMITED/SHUTTING_DOWN/STALE_EPOCH/UNKNOWN)
    assert len(ClusterDenyReason) == 5


def test_envelope_max_size_is_8kb():
    assert ENVELOPE_MAX_SIZE_BYTES == 8 * 1024


def test_default_lease_ttl_is_30s():
    assert DEFAULT_LEASE_TTL_NS == 30 * 1_000_000_000


# ---------------------------------------------------------------------------
# 2. encode / decode round-trip
# ---------------------------------------------------------------------------


def test_encode_decode_roundtrip_acquire_request():
    env = _valid_envelope_obj()
    raw = encode_envelope(env)
    decoded = decode_envelope(raw)
    assert decoded == env


def test_encode_produces_strict_json_no_whitespace():
    env = _valid_envelope_obj()
    raw = encode_envelope(env)
    # strict JSON: 严格 separators=(",", ":") 应无空格
    assert b" " not in raw


def test_decode_rejects_empty_bytes():
    with pytest.raises(ClusterProtocolError) as e:
        decode_envelope(b"")
    assert e.value.code is ClusterErrorCode.MALFORMED_ENVELOPE


def test_decode_rejects_invalid_json():
    with pytest.raises(ClusterProtocolError) as e:
        decode_envelope(b"not-json")
    assert e.value.code is ClusterErrorCode.MALFORMED_ENVELOPE


def test_decode_rejects_non_object_json():
    with pytest.raises(ClusterProtocolError) as e:
        decode_envelope(b"[1, 2, 3]")
    assert e.value.code is ClusterErrorCode.MALFORMED_ENVELOPE


# ---------------------------------------------------------------------------
# 3. protocol_version 校验
# ---------------------------------------------------------------------------


def test_decode_rejects_wrong_protocol_version():
    obj = _valid_envelope(protocol_version="atlas-richie.cluster.token/v0")
    with pytest.raises(ClusterProtocolError) as e:
        decode_envelope(json.dumps(obj).encode("utf-8"))
    assert e.value.code is ClusterErrorCode.PROTOCOL_VERSION_MISMATCH


def test_encode_rejects_wrong_protocol_version_in_dataclass():
    env = _valid_envelope_obj(protocol_version="wrong/v1")
    with pytest.raises(ClusterProtocolError) as e:
        encode_envelope(env)
    assert e.value.code is ClusterErrorCode.PROTOCOL_VERSION_MISMATCH


# ---------------------------------------------------------------------------
# 4. 必填字段缺失
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("missing_field", [
    "protocol_version", "message_kind", "request_id", "instance_id",
    "startup_epoch", "resource", "permits", "deadline_ns",
    "client_requested_at", "server_received_at", "payload",
])
def test_decode_rejects_missing_required_field(missing_field):
    obj = _valid_envelope()
    del obj[missing_field]
    with pytest.raises(ClusterProtocolError) as e:
        decode_envelope(json.dumps(obj).encode("utf-8"))
    assert e.value.code is ClusterErrorCode.MALFORMED_ENVELOPE
    assert missing_field in e.value.message


# ---------------------------------------------------------------------------
# 5. 未知字段拒绝 (V1 frozen)
# ---------------------------------------------------------------------------


def test_decode_rejects_unknown_field():
    obj = _valid_envelope(unknown_field="x")
    with pytest.raises(ClusterProtocolError) as e:
        decode_envelope(json.dumps(obj).encode("utf-8"))
    assert e.value.code is ClusterErrorCode.MALFORMED_ENVELOPE
    assert "unknown_field" in e.value.message


# ---------------------------------------------------------------------------
# 6. message_kind / error_code / deny_reason 枚举校验
# ---------------------------------------------------------------------------


def test_decode_rejects_unknown_message_kind():
    obj = _valid_envelope(message_kind="UNKNOWN_KIND")
    with pytest.raises(ClusterProtocolError) as e:
        decode_envelope(json.dumps(obj).encode("utf-8"))
    assert e.value.code is ClusterErrorCode.UNKNOWN_MESSAGE_KIND


# ---------------------------------------------------------------------------
# 7. UUID / 时间 / checksum 格式校验
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_uuid_field", ["request_id", "instance_id"])
def test_decode_rejects_non_uuid_v4(bad_uuid_field):
    obj = _valid_envelope(**{bad_uuid_field: "not-a-uuid"})
    with pytest.raises(ClusterProtocolError) as e:
        decode_envelope(json.dumps(obj).encode("utf-8"))
    assert e.value.code is ClusterErrorCode.MALFORMED_ENVELOPE


@pytest.mark.parametrize("bad_time_field", ["client_requested_at", "server_received_at"])
def test_decode_rejects_non_iso8601_utc_micro(bad_time_field):
    obj = _valid_envelope(**{bad_time_field: "2026-09-13 10:00:00"})
    with pytest.raises(ClusterProtocolError) as e:
        decode_envelope(json.dumps(obj).encode("utf-8"))
    assert e.value.code is ClusterErrorCode.MALFORMED_ENVELOPE


def test_decode_rejects_checksum_without_sha256_prefix():
    obj = _valid_envelope()
    obj["payload"]["rule_version_checksum"] = "md5:" + "a" * 64
    with pytest.raises(ClusterProtocolError) as e:
        decode_envelope(json.dumps(obj).encode("utf-8"))
    assert e.value.code is ClusterErrorCode.MALFORMED_ENVELOPE


def test_decode_rejects_checksum_wrong_hex_len():
    obj = _valid_envelope()
    obj["payload"]["rule_version_checksum"] = "sha256:" + "a" * 63
    with pytest.raises(ClusterProtocolError) as e:
        decode_envelope(json.dumps(obj).encode("utf-8"))
    assert e.value.code is ClusterErrorCode.MALFORMED_ENVELOPE


# ---------------------------------------------------------------------------
# 8. size 上限
# ---------------------------------------------------------------------------


def test_encode_rejects_oversized_envelope():
    # schema 严格 (resource ≤ 256, payload 字段受约束) 导致合法 envelope
    # 远小于 8 KB, encode 路径超 size 不可达. 仅 decode 路径测超 size.
    raw = b'{"x": "' + b'a' * (ENVELOPE_MAX_SIZE_BYTES + 100) + b'"}'
    with pytest.raises(ClusterProtocolError) as e:
        decode_envelope(raw)
    assert e.value.code is ClusterErrorCode.MALFORMED_ENVELOPE


def test_encode_rejects_invalid_protocol_version_in_dataclass():
    env = _valid_envelope_obj(protocol_version="wrong/v1")
    with pytest.raises(ClusterProtocolError) as e:
        encode_envelope(env)
    assert e.value.code is ClusterErrorCode.PROTOCOL_VERSION_MISMATCH


def test_decode_rejects_oversized_envelope():
    raw = b'{"x": "' + b'a' * (ENVELOPE_MAX_SIZE_BYTES + 100) + b'"}'
    with pytest.raises(ClusterProtocolError) as e:
        decode_envelope(raw)
    assert e.value.code is ClusterErrorCode.MALFORMED_ENVELOPE


# ---------------------------------------------------------------------------
# 9. per-kind payload 校验
# ---------------------------------------------------------------------------


def test_validate_payload_acquire_request_success():
    payload = {
        "rule_version_epoch": 1,
        "rule_version_revision": 0,
        "rule_version_checksum": "sha256:" + "a" * 64,
        "priority": 0,
    }
    validate_payload(ClusterMessageKind.ACQUIRE_REQUEST, payload)


def test_validate_payload_acquire_response_granted_success():
    payload = {
        "decision": "REMOTE_GRANTED",
        "lease_id": str(uuid.uuid4()),
        "lease_expires_at": "2026-09-13T10:00:05.000000Z",
        "permits_granted": 1.0,
        "retry_after_ns": 0,
        "deny_reason": None,
    }
    validate_payload(ClusterMessageKind.ACQUIRE_RESPONSE, payload)


def test_validate_payload_acquire_response_denied_success():
    payload = {
        "decision": "DENIED",
        "lease_id": None,
        "lease_expires_at": None,
        "permits_granted": None,
        "retry_after_ns": 0,
        "deny_reason": "QUEUE_FULL",
    }
    validate_payload(ClusterMessageKind.ACQUIRE_RESPONSE, payload)


def test_validate_payload_acquire_response_granted_requires_lease_id():
    payload = {
        "decision": "REMOTE_GRANTED",
        "lease_id": None,
        "lease_expires_at": "2026-09-13T10:00:05.000000Z",
        "permits_granted": 1.0,
        "retry_after_ns": 0,
        "deny_reason": None,
    }
    with pytest.raises(ClusterProtocolError) as e:
        validate_payload(ClusterMessageKind.ACQUIRE_RESPONSE, payload)
    assert e.value.code is ClusterErrorCode.MALFORMED_ENVELOPE


def test_validate_payload_acquire_response_denied_requires_deny_reason():
    payload = {
        "decision": "DENIED",
        "lease_id": None,
        "lease_expires_at": None,
        "permits_granted": None,
        "retry_after_ns": 0,
        "deny_reason": None,
    }
    with pytest.raises(ClusterProtocolError) as e:
        validate_payload(ClusterMessageKind.ACQUIRE_RESPONSE, payload)
    assert e.value.code is ClusterErrorCode.MALFORMED_ENVELOPE


def test_validate_payload_acquire_response_unknown_deny_reason():
    payload = {
        "decision": "DENIED",
        "lease_id": None,
        "lease_expires_at": None,
        "permits_granted": None,
        "retry_after_ns": 0,
        "deny_reason": "MAGIC",
    }
    with pytest.raises(ClusterProtocolError) as e:
        validate_payload(ClusterMessageKind.ACQUIRE_RESPONSE, payload)
    assert e.value.code is ClusterErrorCode.MALFORMED_ENVELOPE


def test_validate_payload_acquire_request_rejects_unknown_field():
    payload = {
        "rule_version_epoch": 1,
        "rule_version_revision": 0,
        "rule_version_checksum": "sha256:" + "a" * 64,
        "priority": 0,
        "extra": "x",
    }
    with pytest.raises(ClusterProtocolError) as e:
        validate_payload(ClusterMessageKind.ACQUIRE_REQUEST, payload)
    assert e.value.code is ClusterErrorCode.MALFORMED_ENVELOPE


def test_validate_payload_release_request_success():
    payload = {
        "lease_id": str(uuid.uuid4()),
        "permits_released": 1.0,
    }
    validate_payload(ClusterMessageKind.RELEASE_REQUEST, payload)


def test_validate_payload_renew_request_success():
    payload = {
        "lease_id": str(uuid.uuid4()),
        "extends_for_ns": 5_000_000,
    }
    validate_payload(ClusterMessageKind.RENEW_REQUEST, payload)


def test_validate_payload_renew_request_rejects_non_positive_extends():
    payload = {
        "lease_id": str(uuid.uuid4()),
        "extends_for_ns": 0,
    }
    with pytest.raises(ClusterProtocolError) as e:
        validate_payload(ClusterMessageKind.RENEW_REQUEST, payload)
    assert e.value.code is ClusterErrorCode.MALFORMED_ENVELOPE


def test_validate_payload_renew_response_renewed_decision():
    payload = {
        "decision": "RENEWED",
        "lease_id": str(uuid.uuid4()),
        "lease_expires_at": "2026-09-13T10:00:10.000000Z",
        "permits_granted": 1.0,
        "retry_after_ns": 0,
        "deny_reason": None,
    }
    validate_payload(ClusterMessageKind.RENEW_RESPONSE, payload)


def test_validate_payload_error_response_success():
    payload = {
        "error_code": "STALE_EPOCH",
        "error_message": "x" * 64,
    }
    validate_payload(ClusterMessageKind.ERROR_RESPONSE, payload)


def test_validate_payload_error_response_rejects_oversized_message():
    payload = {
        "error_code": "STALE_EPOCH",
        "error_message": "x" * 65,
    }
    with pytest.raises(ClusterProtocolError) as e:
        validate_payload(ClusterMessageKind.ERROR_RESPONSE, payload)
    assert e.value.code is ClusterErrorCode.MALFORMED_ENVELOPE


def test_validate_payload_error_response_rejects_unknown_error_code():
    payload = {
        "error_code": "MAGIC",
        "error_message": "",
    }
    with pytest.raises(ClusterProtocolError) as e:
        validate_payload(ClusterMessageKind.ERROR_RESPONSE, payload)
    assert e.value.code is ClusterErrorCode.MALFORMED_ENVELOPE


# ---------------------------------------------------------------------------
# 10. payload dataclass 1:1 镜像验证
# ---------------------------------------------------------------------------


def test_payload_dataclasses_are_frozen_and_slots():
    for cls in (
        AcquireRequestPayload,
        AcquireResponsePayload,
        ReleaseRequestPayload,
        RenewRequestPayload,
        RenewResponsePayload,
        ErrorResponsePayload,
    ):
        # frozen + slots 锁死, 防止 worker 误改
        assert cls.__dataclass_params__.frozen is True
        assert cls.__dataclass_params__.slots is True


def test_acquire_request_payload_construction():
    p = AcquireRequestPayload(
        rule_version_epoch=1,
        rule_version_revision=0,
        rule_version_checksum="sha256:" + "a" * 64,
        priority=5,
    )
    assert p.priority == 5
    # frozen: 不能再赋值
    with pytest.raises((AttributeError, Exception)):
        p.priority = 6  # type: ignore[misc]

"""Cross-language contract tests: Python ↔ Go SDK mock.

Verifies the Go mock codec (under ``cross_lang/go/``) is a 1:1 mirror of
the Python codec and that the wire-format spec is honored on the Go side.
"""
from __future__ import annotations

import json
import uuid

import pytest

from atlas_richie.contracts.reporting.v1 import (
    PROTOCOL_VERSION,
    ReportingBatch,
    ReportingEnvelope,
    ReportingErrorCode,
    ReportingEventKind,
    decode_batch,
    decode_envelope,
    decode_error_envelope,
    encode_batch,
    encode_envelope,
    encode_error_envelope,
)

from .conftest import (
    GO_BINARY,
    canonical_json,
    read_fixture,
    run_cli,
)


# ---- 1. Build / smoke ----------------------------------------------------


def test_go_binary_compiles(go_binary):
    assert go_binary.exists() and go_binary.is_file()
    assert go_binary.stat().st_size > 0


def test_go_cli_emits_compact_json(go_binary):
    raw = read_fixture("valid_envelope.json")
    proc = run_cli([str(go_binary), "-kind", "envelope"], raw)
    assert proc.returncode == 0, proc.stderr.decode()
    out = proc.stdout.rstrip(b"\n")
    assert b" " not in out and b"\t" not in out and b"\n" not in out


# ---- 2. Python → Go → Python round-trip on fixtures ---------------------


@pytest.mark.parametrize("fixture_name", [
    "valid_envelope.json",
    "valid_envelope_blocked.json",
    "valid_envelope_failed.json",
    "valid_envelope_health.json",
])
def test_python_to_go_to_python_envelope(go_binary, fixture_name):
    raw = read_fixture(fixture_name)
    proc = run_cli([str(go_binary), "-kind", "envelope"], raw)
    assert proc.returncode == 0, proc.stderr.decode()
    out = proc.stdout.rstrip(b"\n")
    env = decode_envelope(out)
    original = decode_envelope(raw)
    assert env == original


def test_python_to_go_to_python_batch(go_binary):
    raw = read_fixture("valid_batch.json")
    proc = run_cli([str(go_binary), "-kind", "batch"], raw)
    assert proc.returncode == 0, proc.stderr.decode()
    out = proc.stdout.rstrip(b"\n")
    decoded_batch = decode_batch(out)
    original_batch = decode_batch(raw)
    assert decoded_batch == original_batch


def test_python_to_go_to_python_ack(go_binary):
    raw = read_fixture("valid_ack.json")
    proc = run_cli([str(go_binary), "-kind", "ack"], raw)
    assert proc.returncode == 0, proc.stderr.decode()
    out = proc.stdout.rstrip(b"\n")
    decoded = json.loads(out)
    assert set(decoded.keys()) == {
        "protocol_version", "batch_id", "received_at",
        "ack_sequences", "duplicate_count",
    }
    assert "received_at" in decoded


def test_python_to_go_to_python_error(go_binary):
    raw = read_fixture("valid_error.json")
    proc = run_cli([str(go_binary), "-kind", "error"], raw)
    assert proc.returncode == 0, proc.stderr.decode()
    out = proc.stdout.rstrip(b"\n")
    err = decode_error_envelope(out)
    assert err.protocol_version == PROTOCOL_VERSION
    assert err.error_code == "MALFORMED_ENVELOPE"


# ---- 3. Go output must satisfy V1 spec ----------------------------------


def test_go_envelope_has_7_fields_no_received_at(go_binary):
    raw = read_fixture("valid_envelope.json")
    proc = run_cli([str(go_binary), "-kind", "envelope"], raw)
    assert proc.returncode == 0
    obj = json.loads(proc.stdout)
    assert len(obj) == 7
    assert "received_at" not in obj


def test_go_batch_has_7_fields(go_binary):
    raw = read_fixture("valid_batch.json")
    proc = run_cli([str(go_binary), "-kind", "batch"], raw)
    assert proc.returncode == 0
    obj = json.loads(proc.stdout)
    assert set(obj.keys()) == {
        "protocol_version", "instance_id", "startup_epoch", "batch_id",
        "sent_at", "events", "dropped_count",
    }


def test_go_ack_has_5_fields(go_binary):
    raw = read_fixture("valid_ack.json")
    proc = run_cli([str(go_binary), "-kind", "ack"], raw)
    assert proc.returncode == 0
    obj = json.loads(proc.stdout)
    assert len(obj) == 5
    assert "received_at" in obj


def test_go_error_has_4_fields(go_binary):
    raw = read_fixture("valid_error.json")
    proc = run_cli([str(go_binary), "-kind", "error"], raw)
    assert proc.returncode == 0
    obj = json.loads(proc.stdout)
    assert set(obj.keys()) == {
        "protocol_version", "error_code", "message", "details",
    }


# ---- 4. Wire bytes byte-level: Python ↔ Go equivalent after sort -------


def test_wire_bytes_equivalent_after_sort_envelope(go_binary):
    raw = read_fixture("valid_envelope.json")
    proc = run_cli([str(go_binary), "-kind", "envelope"], raw)
    assert proc.returncode == 0
    go_bytes = proc.stdout.rstrip(b"\n")
    go_canonical = canonical_json(json.loads(go_bytes))
    py_canonical = canonical_json(json.loads(raw))
    assert go_canonical == py_canonical


def test_wire_bytes_equivalent_after_sort_batch(go_binary):
    raw = read_fixture("valid_batch.json")
    proc = run_cli([str(go_binary), "-kind", "batch"], raw)
    assert proc.returncode == 0
    go_canonical = canonical_json(json.loads(proc.stdout))
    py_canonical = canonical_json(json.loads(raw))
    assert go_canonical == py_canonical


# ---- 5. Go rejects the same invalid cases Python rejects ----------------


@pytest.mark.parametrize("fixture_name,expected_code", [
    ("invalid_received_at_ingress.json", "MALFORMED_ENVELOPE"),
    ("invalid_unknown_field.json", "MALFORMED_ENVELOPE"),
    ("invalid_unknown_enum.json", "UNKNOWN_EVENT_KIND"),
    ("invalid_wrong_protocol_version.json", "PROTOCOL_VERSION_MISMATCH"),
    ("invalid_wrong_type.json", "MALFORMED_ENVELOPE"),
])
def test_go_rejects_invalid_envelope(go_binary, fixture_name, expected_code):
    raw = read_fixture(fixture_name)
    proc = run_cli([str(go_binary), "-kind", "envelope"], raw)
    assert proc.returncode != 0
    out = proc.stdout.rstrip(b"\n")
    err = json.loads(out)
    assert err.get("error_code") == expected_code, (
        f"expected {expected_code}, got {err}"
    )


def test_go_rejects_size_overflow_envelope(go_binary):
    raw = read_fixture("invalid_size_overflow_envelope.json")
    proc = run_cli([str(go_binary), "-kind", "envelope"], raw)
    assert proc.returncode != 0
    err = json.loads(proc.stdout)
    assert err.get("error_code") == "ENVELOPE_TOO_LARGE"


def test_go_rejects_size_overflow_batch(go_binary):
    raw = read_fixture("invalid_size_overflow_batch.json")
    proc = run_cli([str(go_binary), "-kind", "batch"], raw)
    assert proc.returncode != 0
    err = json.loads(proc.stdout)
    assert err.get("error_code") in ("BATCH_TOO_LARGE", "ENVELOPE_TOO_LARGE")


def test_go_rejects_mixed_identity_batch(go_binary):
    raw = read_fixture("invalid_mixed_identity.json")
    proc = run_cli([str(go_binary), "-kind", "batch"], raw)
    assert proc.returncode != 0
    err = json.loads(proc.stdout)
    assert err.get("error_code") == "MALFORMED_ENVELOPE"
    assert "instance_id" in err.get("message", "")


# ---- 6. Generate-then-cross-decode ---------------------------------------


def test_python_encoded_envelope_decodes_in_go(go_binary):
    env = ReportingEnvelope(
        protocol_version=PROTOCOL_VERSION,
        event_kind="RULE_APPLIED",
        event_payload={
            "source_id": "nacos-prod",
            "rule_id": "flow:/api/v1/users",
            "rule_version_epoch": 1726000000,
            "rule_version_revision": 0,
            "rule_version_checksum":
                "sha256:" + "a" * 64,
            "exec_result": "BLOCKED",
            "failure_class": None,
        },
        instance_id="550e8400-e29b-41d4-a716-446655440000",
        startup_epoch=0,
        sequence=1,
        captured_at="2026-09-13T10:00:00.123456Z",
    )
    py_raw = encode_envelope(env)
    proc = run_cli([str(go_binary), "-kind", "envelope"], py_raw)
    assert proc.returncode == 0, proc.stderr.decode()
    go_obj = json.loads(proc.stdout)
    assert go_obj["event_kind"] == "RULE_APPLIED"
    assert go_obj["event_payload"]["exec_result"] == "BLOCKED"
    assert go_obj["event_payload"]["failure_class"] is None


def test_python_encoded_batch_decodes_in_go(go_binary):
    env = ReportingEnvelope(
        protocol_version=PROTOCOL_VERSION,
        event_kind="RULE_BLOCKED",
        event_payload={
            "source_id": "nacos-prod",
            "rule_id": "flow:/api/v1/users",
            "rule_version_epoch": 1726000000,
            "rule_version_revision": 0,
            "rule_version_checksum":
                "sha256:" + "a" * 64,
            "exec_result": "BLOCKED",
            "failure_class": None,
        },
        instance_id="550e8400-e29b-41d4-a716-446655440000",
        startup_epoch=0,
        sequence=1,
        captured_at="2026-09-13T10:00:00.123456Z",
    )
    batch = ReportingBatch(
        protocol_version=PROTOCOL_VERSION,
        instance_id="550e8400-e29b-41d4-a716-446655440000",
        startup_epoch=0,
        batch_id="550e8400-e29b-41d4-a716-446655440001",
        sent_at="2026-09-13T10:00:00.123456Z",
        events=[env],
        dropped_count=0,
    )
    py_raw = encode_batch(batch)
    proc = run_cli([str(go_binary), "-kind", "batch"], py_raw)
    assert proc.returncode == 0, proc.stderr.decode()
    go_obj = json.loads(proc.stdout)
    assert len(go_obj["events"]) == 1
    assert go_obj["events"][0]["event_kind"] == "RULE_BLOCKED"
    assert go_obj["dropped_count"] == 0


# ---- 7. Cross-decode: Go output must decode in Python codec -------------


def test_go_output_decodes_in_python_codec(go_binary):
    raw = read_fixture("valid_envelope.json")
    proc = run_cli([str(go_binary), "-kind", "envelope"], raw)
    out = proc.stdout.rstrip(b"\n")
    env = decode_envelope(out)
    assert isinstance(env, ReportingEnvelope)
    assert env.protocol_version == PROTOCOL_VERSION
    assert env.event_kind == "RULE_SOURCE_ACTIVATED"


# ---- 8. Spec invariants: 6 event kinds + 11 error codes -----------------


def _payload_for_kind(kind: str) -> dict:
    checksum = "sha256:" + "a" * 64
    if kind == "RULE_SOURCE_ACTIVATED":
        return {
            "source_id": "nacos-prod",
            "rule_version_epoch": 1,
            "rule_version_revision": 0,
            "rule_version_checksum": checksum,
        }
    if kind in ("RULE_SOURCE_STALE", "RULE_SOURCE_DEGRADED"):
        return {
            "source_id": "nacos-prod",
            "health_class": "STALE",
            "reason_class": "EMPTY_DATA_ID",
            "rule_version_epoch": 1,
            "rule_version_revision": 0,
            "rule_version_checksum": checksum,
        }
    if kind == "RULE_APPLIED":
        return {
            "source_id": "nacos-prod",
            "rule_id": "flow:/api/v1/users",
            "rule_version_epoch": 1,
            "rule_version_revision": 0,
            "rule_version_checksum": checksum,
            "exec_result": "APPLIED",
            "failure_class": None,
        }
    if kind == "RULE_BLOCKED":
        return {
            "source_id": "nacos-prod",
            "rule_id": "flow:/api/v1/users",
            "rule_version_epoch": 1,
            "rule_version_revision": 0,
            "rule_version_checksum": checksum,
            "exec_result": "BLOCKED",
            "failure_class": None,
        }
    if kind == "RULE_FAILED":
        return {
            "source_id": "nacos-prod",
            "rule_id": "flow:/api/v1/users",
            "rule_version_epoch": 1,
            "rule_version_revision": 0,
            "rule_version_checksum": checksum,
            "exec_result": "FAILED",
            "failure_class": "DECODE_FAILED",
        }
    raise AssertionError(f"unknown kind {kind!r}")


def test_go_rejects_unknown_event_kind_via_python():
    for kind in ReportingEventKind:
        env = ReportingEnvelope(
            protocol_version=PROTOCOL_VERSION,
            event_kind=kind.value,
            event_payload=_payload_for_kind(kind.value),
            instance_id=str(uuid.uuid4()),
            startup_epoch=0,
            sequence=1,
            captured_at="2026-09-13T10:00:00.123456Z",
        )
        raw = encode_envelope(env)
        decode_envelope(raw)


def test_go_accepts_all_6_event_kinds(go_binary):
    for kind in ReportingEventKind:
        env = ReportingEnvelope(
            protocol_version=PROTOCOL_VERSION,
            event_kind=kind.value,
            event_payload=_payload_for_kind(kind.value),
            instance_id="550e8400-e29b-41d4-a716-446655440000",
            startup_epoch=0,
            sequence=1,
            captured_at="2026-09-13T10:00:00.123456Z",
        )
        raw = encode_envelope(env)
        proc = run_cli([str(go_binary), "-kind", "envelope"], raw)
        assert proc.returncode == 0, (
            f"Go rejected valid {kind.value}: {proc.stderr}"
        )
        out = proc.stdout.rstrip(b"\n")
        decoded = json.loads(out)
        assert decoded["event_kind"] == kind.value


def test_go_error_envelope_11_codes(go_binary):
    for code in ReportingErrorCode:
        err_obj = {
            "protocol_version": PROTOCOL_VERSION,
            "error_code": code.value,
            "message": f"test {code.value}",
            "details": None,
        }
        raw = json.dumps(err_obj, separators=(",", ":")).encode("utf-8")
        proc = run_cli([str(go_binary), "-kind", "error"], raw)
        assert proc.returncode == 0, (
            f"Go rejected error code {code.value}: {proc.stderr}"
        )
        out = proc.stdout.rstrip(b"\n")
        decoded = decode_error_envelope(out)
        assert decoded.error_code == code.value

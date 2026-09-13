"""Cross-language hello world contract tests: Python ↔ Go.

Verifies that the strict JSON bytes produced by the Python reporting
codec at
``foundation/contracts/src/atlas_richie/contracts/reporting/v1/codec.py``
can be POSTed to the Go hello world web service at
``cross_lang/go/main.go``, and that the service correctly accepts /
rejects the same wire-format inputs the Python codec would (at the
level of the two marker fields ``protocol_version`` and
``event_kind`` — full wire semantics are out of scope for hello
world).
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid

import pytest

from atlas_richie.contracts.reporting.v1 import (
    PROTOCOL_VERSION,
    ReportingBatch,
    ReportingEnvelope,
    ReportingEventKind,
    encode_batch,
    encode_envelope,
)

from .conftest import HelloClient


WIRE_KEYS = {
    "protocol_version", "event_kind", "event_payload",
    "instance_id", "startup_epoch", "sequence", "captured_at",
}


def test_go_healthz_ok(go_hello: HelloClient) -> None:
    assert go_hello.healthz() == 200


@pytest.mark.parametrize("fixture_name,expected_kind", [
    ("valid_envelope.json", "RULE_SOURCE_ACTIVATED"),
    ("valid_envelope_blocked.json", "RULE_BLOCKED"),
    ("valid_envelope_failed.json", "RULE_FAILED"),
    ("valid_envelope_health.json", "RULE_SOURCE_STALE"),
])
def test_go_accepts_per_kind_envelope_fixture(
    go_hello: HelloClient, fixture_name: str, expected_kind: str,
) -> None:
    from pathlib import Path
    raw = (Path(__file__).resolve().parent / "fixtures" / fixture_name).read_bytes()
    status, out = go_hello.report(raw)
    assert status == 200, f"unexpected status {status}: {out}"
    assert out["status"] == "ok"
    assert out["fields_count"] == 7
    assert out["event_kind"] == expected_kind
    assert out["protocol_version"] == PROTOCOL_VERSION
    assert set(out["key_order"]) == WIRE_KEYS


def _rule_exec_payload(rule_id, exec_result="APPLIED", failure_class=None):
    return {
        "source_id": "nacos-prod",
        "rule_id": rule_id,
        "rule_version_epoch": 1726000000,
        "rule_version_revision": 0,
        "rule_version_checksum": "sha256:" + "abcdef" * 10 + "abcdef0123",
        "exec_result": exec_result,
        "failure_class": failure_class,
    }


def test_go_decodes_python_encoded_envelope(go_hello):
    env = ReportingEnvelope(
        protocol_version=PROTOCOL_VERSION,
        event_kind=ReportingEventKind.RULE_APPLIED,
        event_payload=_rule_exec_payload("flow:/api/v1/users"),
        instance_id="550e8400-e29b-41d4-a716-446655440000",
        startup_epoch=0,
        sequence=1,
        captured_at="2026-09-13T10:00:00.123456Z",
    )
    raw = encode_envelope(env)
    status, out = go_hello.report(raw)
    assert status == 200, out
    assert out["event_kind"] == "RULE_APPLIED"
    assert out["fields_count"] == 7
    assert set(out["key_order"]) == WIRE_KEYS


def test_go_rejects_batch_envelope(go_hello):
    ev = ReportingEnvelope(
        protocol_version=PROTOCOL_VERSION,
        event_kind=ReportingEventKind.RULE_APPLIED,
        event_payload=_rule_exec_payload("flow:/api/v1/users"),
        instance_id=str(uuid.uuid4()),
        startup_epoch=0,
        sequence=1,
        captured_at="2026-09-13T10:00:00.123456Z",
    )
    batch = ReportingBatch(
        protocol_version=PROTOCOL_VERSION,
        instance_id=ev.instance_id,
        startup_epoch=ev.startup_epoch,
        batch_id=str(uuid.uuid4()),
        sent_at="2026-09-13T10:00:00.000001Z",
        events=[ev],
        dropped_count=0,
    )
    raw = encode_batch(batch)
    status, out = go_hello.report(raw)
    assert 400 <= status < 500
    assert out.get("error_code") in ("MALFORMED_ENVELOPE", "UNKNOWN_EVENT_KIND")


def test_go_rejects_missing_protocol_version(go_hello):
    raw = json.dumps({"event_kind": "RULE_APPLIED"}).encode("utf-8")
    status, out = go_hello.report(raw)
    assert 400 <= status < 500
    assert out["error_code"] == "PROTOCOL_VERSION_MISMATCH"


def test_go_rejects_missing_event_kind(go_hello):
    raw = json.dumps({"protocol_version": PROTOCOL_VERSION}).encode("utf-8")
    status, out = go_hello.report(raw)
    assert 400 <= status < 500
    assert out["error_code"] in ("MALFORMED_ENVELOPE", "UNKNOWN_EVENT_KIND")


def test_go_rejects_unknown_event_kind(go_hello):
    raw = json.dumps({
        "protocol_version": PROTOCOL_VERSION,
        "event_kind": "MAGIC_EVENT",
    }).encode("utf-8")
    status, out = go_hello.report(raw)
    assert 400 <= status < 500
    assert out["error_code"] == "UNKNOWN_EVENT_KIND"


def test_go_rejects_invalid_json(go_hello):
    status, out = go_hello.report(b"not-json")
    assert 400 <= status < 500
    assert out["error_code"] == "MALFORMED_ENVELOPE"


def test_go_rejects_wrong_protocol_version(go_hello):
    raw = json.dumps({
        "protocol_version": "atlas-richie.reporting/v0",
        "event_kind": "RULE_APPLIED",
    }).encode("utf-8")
    status, out = go_hello.report(raw)
    assert 400 <= status < 500
    assert out["error_code"] == "PROTOCOL_VERSION_MISMATCH"


def _make_envelope():
    env = ReportingEnvelope(
        protocol_version=PROTOCOL_VERSION,
        event_kind=ReportingEventKind.RULE_APPLIED,
        event_payload=_rule_exec_payload("flow:/api/v1/users"),
        instance_id=str(uuid.uuid4()),
        startup_epoch=0,
        sequence=1,
        captured_at="2026-09-13T10:00:00.123456Z",
    )
    return encode_envelope(env)


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_go_concurrent_pressure(go_hello):
    raw = _make_envelope()
    n = 10

    async def one_call():
        t0 = time.perf_counter()
        status, _out = go_hello.report(raw)
        assert status == 200
        return (time.perf_counter() - t0) * 1000.0

    samples = await asyncio.gather(*[one_call() for _ in range(n)])
    samples.sort()
    p99 = samples[int(0.99 * n) - 1]
    assert p99 < 2000, f"p99={p99:.0f}ms exceeds 2000ms (samples={samples})"

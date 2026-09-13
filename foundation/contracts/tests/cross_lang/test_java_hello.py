"""Cross-language hello world contract tests: Python ↔ Java.

Verifies that the strict JSON bytes produced by the Python reporting codec
at ``foundation/contracts/src/atlas_richie/contracts/reporting/v1/codec.py``
can be parsed by the Java stdlib-only JSON parser (the Java hello world
at ``cross_lang/java/src/main/java/com/atlas_richie/reporting/Main.java``),
and that the Java hello world correctly accepts / rejects the same
wire-format inputs as the Python codec would (at the level of the two
marker fields ``protocol_version`` and ``event_kind`` — full wire
semantics are out of scope for hello world).

Coverage mirrors ``test_go_hello.py``:
- 7-field envelope (per-kind variants: activated, blocked, failed, health)
- batch / ack / error envelopes are correctly rejected
- invalid JSON / missing marker fields are correctly rejected
- concurrent pressure (N=10, p99 < 5000ms — Java JVM cold start is slower)
"""
from __future__ import annotations

import json
import threading
import time
import uuid

import pytest

from atlas_richie.contracts.reporting.v1 import (
    PROTOCOL_VERSION,
    AckEnvelope,
    AckSequence,
    ErrorDetails,
    ErrorEnvelope,
    ReportingBatch,
    ReportingEnvelope,
    ReportingErrorCode,
    ReportingEventKind,
    encode_ack,
    encode_batch,
    encode_envelope,
    encode_error_envelope,
)

from .conftest import (
    read_fixture,
    run_java,
)


# ---- 1. Build / smoke -----------------------------------------------------


def test_java_hello_jar_exists(java_jar):
    """The Java hello world jar is built and non-empty."""
    assert java_jar.exists() and java_jar.is_file()
    assert java_jar.stat().st_size > 0


def test_java_hello_accepts_valid_envelope_fixture(java_jar):
    """Java hello world accepts the 7-field envelope fixture from disk."""
    raw = read_fixture("valid_envelope.json")
    proc = run_java(raw)
    assert proc.returncode == 0, proc.stderr.decode()
    out = json.loads(proc.stdout)
    assert out["status"] == "ok"
    assert out["fields_count"] == 7
    assert out["protocol_version"] == PROTOCOL_VERSION
    assert out["event_kind"] == "RULE_SOURCE_ACTIVATED"
    assert "key_order" in out
    assert len(out["key_order"]) == 7


# ---- 2. Per-kind envelope variants ---------------------------------------


@pytest.mark.parametrize("fixture_name,expected_kind", [
    ("valid_envelope.json", "RULE_SOURCE_ACTIVATED"),
    ("valid_envelope_blocked.json", "RULE_BLOCKED"),
    ("valid_envelope_failed.json", "RULE_FAILED"),
    ("valid_envelope_health.json", "RULE_SOURCE_STALE"),
])
def test_java_hello_accepts_per_kind_envelope_fixtures(
    java_jar, fixture_name, expected_kind
):
    raw = read_fixture(fixture_name)
    proc = run_java(raw)
    assert proc.returncode == 0, proc.stderr.decode()
    out = json.loads(proc.stdout)
    assert out["status"] == "ok"
    assert out["fields_count"] == 7
    assert out["event_kind"] == expected_kind


# ---- 3. Python-encode → Java-decode wire round-trip ----------------------


def test_java_hello_decodes_python_encoded_envelope(java_jar):
    """Python strict codec output must be parseable by the Java stdlib."""
    env = ReportingEnvelope(
        protocol_version=PROTOCOL_VERSION,
        event_kind=ReportingEventKind.RULE_APPLIED.value,
        event_payload={
            "source_id": "nacos-prod",
            "rule_id": "flow:/api/v1/users",
            "rule_version_epoch": 1726000000,
            "rule_version_revision": 0,
            "rule_version_checksum":
                "sha256:" + "abcdef" * 10 + "abcdef0123",
            "exec_result": "APPLIED",
            "failure_class": None,
        },
        instance_id="550e8400-e29b-41d4-a716-446655440000",
        startup_epoch=0,
        sequence=1,
        captured_at="2026-09-13T10:00:00.123456Z",
    )
    raw = encode_envelope(env)
    proc = run_java(raw)
    assert proc.returncode == 0, proc.stderr.decode()
    out = json.loads(proc.stdout)
    assert out["event_kind"] == "RULE_APPLIED"
    assert out["fields_count"] == 7
    # The Java hello world preserves the same 7 fields on the wire.
    assert set(out["key_order"]) == {
        "protocol_version", "event_kind", "event_payload",
        "instance_id", "startup_epoch", "sequence", "captured_at",
    }


def test_java_hello_decodes_python_encoded_batch(java_jar):
    env = ReportingEnvelope(
        protocol_version=PROTOCOL_VERSION,
        event_kind=ReportingEventKind.RULE_APPLIED.value,
        event_payload={
            "source_id": "nacos-prod",
            "rule_id": "flow:/api/v1/users",
            "rule_version_epoch": 1726000000,
            "rule_version_revision": 0,
            "rule_version_checksum":
                "sha256:" + "abcdef" * 10 + "abcdef0123",
            "exec_result": "APPLIED",
            "failure_class": None,
        },
        instance_id=str(uuid.uuid4()),
        startup_epoch=0,
        sequence=1,
        captured_at="2026-09-13T10:00:00.123456Z",
    )
    batch = ReportingBatch(
        protocol_version=PROTOCOL_VERSION,
        instance_id=env.instance_id,
        startup_epoch=0,
        batch_id=str(uuid.uuid4()),
        sent_at="2026-09-13T10:00:00.123456Z",
        events=[env],
        dropped_count=0,
    )
    raw = encode_batch(batch)
    proc = run_java(raw)
    assert proc.returncode != 0
    assert b"event_kind" in proc.stderr


def test_java_hello_decodes_python_encoded_ack(java_jar):
    ack = AckEnvelope(
        protocol_version=PROTOCOL_VERSION,
        batch_id=str(uuid.uuid4()),
        received_at="2026-09-13T10:00:00.456789Z",
        ack_sequences=[
            AckSequence(
                instance_id=str(uuid.uuid4()),
                startup_epoch=0,
                max_contiguous_sequence=1,
            )
        ],
        duplicate_count=0,
    )
    raw = encode_ack(ack)
    proc = run_java(raw)
    assert proc.returncode != 0
    assert b"event_kind" in proc.stderr


def test_java_hello_decodes_python_encoded_error(java_jar):
    err = ErrorEnvelope(
        protocol_version=PROTOCOL_VERSION,
        error_code=ReportingErrorCode.MALFORMED_ENVELOPE.value,
        message="test error",
        details=ErrorDetails(field="sequence", got_type="string"),
    )
    raw = encode_error_envelope(err)
    proc = run_java(raw)
    assert proc.returncode != 0
    assert b"event_kind" in proc.stderr


# ---- 4. Reject invalid input ---------------------------------------------


def test_java_hello_rejects_invalid_json(java_jar):
    proc = run_java(b"not json at all")
    assert proc.returncode != 0
    assert b"parse" in proc.stderr or b"expected" in proc.stderr


def test_java_hello_rejects_missing_protocol_version(java_jar):
    raw = b'{"event_kind": "RULE_APPLIED", "extra": 1}'
    proc = run_java(raw)
    assert proc.returncode != 0
    assert b"protocol_version" in proc.stderr


def test_java_hello_rejects_missing_event_kind(java_jar):
    raw = b'{"protocol_version": "atlas-richie.reporting/v1"}'
    proc = run_java(raw)
    assert proc.returncode != 0
    assert b"event_kind" in proc.stderr


# ---- 5. Concurrent pressure: N=10, p99 < 5000ms (JVM cold start) --------


def test_java_hello_concurrent_pressure(java_jar):
    """Spawn N=10 concurrent Java JVM runs via threads; p99 < 5000ms."""
    raw = read_fixture("valid_envelope.json")

    def one_call() -> tuple[float, int]:
        t0 = time.perf_counter()
        proc = run_java(raw, timeout=15.0)
        return (time.perf_counter() - t0) * 1000, proc.returncode

    results: list[tuple[float, int]] = []
    threads: list[threading.Thread] = []

    def worker() -> None:
        results.append(one_call())

    n = 10
    t0_all = time.perf_counter()
    for _ in range(n):
        t = threading.Thread(target=worker)
        threads.append(t)
        t.start()
    for t in threads:
        t.join()
    wall_ms = (time.perf_counter() - t0_all) * 1000

    durations = sorted(r[0] for r in results)
    p99 = durations[int(0.99 * n) - 1]
    assert all(rc == 0 for _, rc in results), (
        f"some Java calls failed: {results}"
    )
    assert p99 < 5000, (
        f"Java hello p99 {p99:.1f}ms > 5000ms; wall {wall_ms:.1f}ms"
    )


# ---- 6. Sync / async / blocking simulation ------------------------------


def test_java_hello_sync_call_latency(java_jar):
    """A single sync call: latency is JVM startup + per-call overhead."""
    raw = read_fixture("valid_envelope.json")
    t0 = time.perf_counter()
    proc = run_java(raw)
    elapsed = (time.perf_counter() - t0) * 1000
    assert proc.returncode == 0
    assert elapsed < 5000, f"single Java run took {elapsed:.1f}ms"


def test_java_hello_async_sequential(java_jar):
    """Sequential async-style subprocess calls (simulated via threads)."""
    raw = read_fixture("valid_envelope.json")
    for i in range(3):
        t0 = time.perf_counter()
        proc = run_java(raw)
        elapsed = (time.perf_counter() - t0) * 1000
        assert proc.returncode == 0
        assert elapsed < 5000, f"iter {i} took {elapsed:.1f}ms"


def test_java_hello_blocking_simulation_via_event(java_jar):
    """Block on a threading.Event around a Java JVM subprocess call."""
    raw = read_fixture("valid_envelope.json")
    done = threading.Event()
    result: dict = {}

    def worker() -> None:
        proc = run_java(raw)
        result["proc"] = proc
        done.set()

    t = threading.Thread(target=worker)
    t.start()
    assert done.wait(timeout=10.0), "Java hello world did not finish in 10s"
    t.join()
    assert result["proc"].returncode == 0

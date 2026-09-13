// encode_test.go: Go internal unit tests for the V1 reporting codec.
//
// 1:1 mirror of foundation/contracts/tests/reporting/v1/test_reporting_codec.py
// and the wire spec. At least 5 cases (3 valid + 5 invalid).
package main

import (
	"encoding/json"
	"strings"
	"testing"
)

const (
	testUUIDv4     = "550e8400-e29b-41d4-a716-446655440000"
	testUUIDv4_2   = "550e8400-e29b-41d4-a716-446655440001"
	testChecksum   = "sha256:abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789"
	testTime       = "2026-09-13T10:00:00.123456Z"
	testTimeBatch  = "2026-09-13T10:00:00.000001Z"
	testTimeAck    = "2026-09-13T10:00:00.456789Z"
)

func validEnvelopeMap() map[string]interface{} {
	return map[string]interface{}{
		"protocol_version": ProtocolVersion,
		"event_kind":       "RULE_SOURCE_ACTIVATED",
		"event_payload": map[string]interface{}{
			"source_id":             "nacos-prod",
			"rule_version_epoch":    float64(1726000000),
			"rule_version_revision": float64(0),
			"rule_version_checksum": testChecksum,
		},
		"instance_id":   testUUIDv4,
		"startup_epoch": float64(0),
		"sequence":      float64(1),
		"captured_at":   testTime,
	}
}

func validBatchMap() map[string]interface{} {
	ev := validEnvelopeMap()
	return map[string]interface{}{
		"protocol_version": ProtocolVersion,
		"instance_id":      testUUIDv4,
		"startup_epoch":    float64(0),
		"batch_id":         testUUIDv4_2,
		"sent_at":          testTimeBatch,
		"events":           []interface{}{ev},
		"dropped_count":    float64(0),
	}
}

func validAckMap() map[string]interface{} {
	return map[string]interface{}{
		"protocol_version": ProtocolVersion,
		"batch_id":         testUUIDv4_2,
		"received_at":      testTimeAck,
		"ack_sequences": []interface{}{
			map[string]interface{}{
				"instance_id":             testUUIDv4,
				"startup_epoch":           float64(0),
				"max_contiguous_sequence": float64(100),
			},
		},
		"duplicate_count": float64(0),
	}
}

func validErrorMap() map[string]interface{} {
	return map[string]interface{}{
		"protocol_version": ProtocolVersion,
		"error_code":       "MALFORMED_ENVELOPE",
		"message":          "field 'sequence' must be int64, got string",
		"details": map[string]interface{}{
			"field":    "sequence",
			"got_type": "string",
		},
	}
}

func TestEnvelopeRoundTrip(t *testing.T) {
	obj := validEnvelopeMap()
	raw, err := EncodeEnvelope(obj)
	if err != nil {
		t.Fatalf("encode: %v", err)
	}
	if strings.ContainsAny(string(raw), " \t\n") {
		t.Fatalf("encoded envelope must be compact (no whitespace), got %q", string(raw))
	}
	decoded, err := DecodeEnvelope(raw)
	if err != nil {
		t.Fatalf("decode: %v", err)
	}
	if decoded["instance_id"] != obj["instance_id"] {
		t.Fatalf("instance_id round-trip mismatch")
	}
	if decoded["event_kind"] != obj["event_kind"] {
		t.Fatalf("event_kind round-trip mismatch")
	}
	var top map[string]interface{}
	if err := json.Unmarshal(raw, &top); err != nil {
		t.Fatalf("re-parse: %v", err)
	}
	if len(top) != 7 {
		t.Fatalf("envelope must have exactly 7 fields, got %d", len(top))
	}
	if _, ok := top["received_at"]; ok {
		t.Fatalf("envelope must NOT contain received_at (BUG 收口后 7 字段)")
	}
}

func TestBatchRoundTrip(t *testing.T) {
	obj := validBatchMap()
	raw, err := EncodeBatch(obj)
	if err != nil {
		t.Fatalf("encode: %v", err)
	}
	if strings.ContainsAny(string(raw), " \t\n") {
		t.Fatalf("encoded batch must be compact")
	}
	decoded, err := DecodeBatch(raw)
	if err != nil {
		t.Fatalf("decode: %v", err)
	}
	if decoded["instance_id"] != obj["instance_id"] {
		t.Fatalf("instance_id round-trip mismatch")
	}
	evs, _ := decoded["events"].([]interface{})
	if len(evs) != 1 {
		t.Fatalf("events.length mismatch: %d", len(evs))
	}
}

func TestAckRoundTrip(t *testing.T) {
	obj := validAckMap()
	raw, err := EncodeAck(obj)
	if err != nil {
		t.Fatalf("encode: %v", err)
	}
	decoded, err := DecodeAck(raw)
	if err != nil {
		t.Fatalf("decode: %v", err)
	}
	if decoded["batch_id"] != obj["batch_id"] {
		t.Fatalf("batch_id round-trip mismatch")
	}
	seqs, _ := decoded["ack_sequences"].([]interface{})
	if len(seqs) != 1 {
		t.Fatalf("ack_sequences must be length 1, got %d", len(seqs))
	}
}

func TestErrorEnvelopeRoundTrip(t *testing.T) {
	obj := validErrorMap()
	raw, err := EncodeErrorEnvelope(obj)
	if err != nil {
		t.Fatalf("encode: %v", err)
	}
	decoded, err := DecodeErrorEnvelope(raw)
	if err != nil {
		t.Fatalf("decode: %v", err)
	}
	if decoded["error_code"] != obj["error_code"] {
		t.Fatalf("error_code round-trip mismatch")
	}
}

func TestAllEventKindsAccepted(t *testing.T) {
	payloadByKind := map[string]map[string]interface{}{
		"RULE_SOURCE_ACTIVATED": {
			"source_id":             "nacos-prod",
			"rule_version_epoch":    float64(1726000000),
			"rule_version_revision": float64(0),
			"rule_version_checksum": testChecksum,
		},
		"RULE_SOURCE_STALE": {
			"source_id":             "nacos-prod",
			"health_class":          "STALE",
			"reason_class":          "EMPTY_DATA_ID",
			"rule_version_epoch":    float64(1),
			"rule_version_revision": float64(0),
			"rule_version_checksum": testChecksum,
		},
		"RULE_SOURCE_DEGRADED": {
			"source_id":             "nacos-prod",
			"health_class":          "DISCONNECTED",
			"reason_class":          "NETWORK_UNAVAILABLE",
			"reason_message":        "nacos unreachable",
			"rule_version_epoch":    float64(1),
			"rule_version_revision": float64(0),
			"rule_version_checksum": testChecksum,
		},
		"RULE_APPLIED": {
			"source_id":             "nacos-prod",
			"rule_id":               "flow:/api/v1/users",
			"rule_version_epoch":    float64(1),
			"rule_version_revision": float64(0),
			"rule_version_checksum": testChecksum,
			"exec_result":           "APPLIED",
			"failure_class":         nil,
		},
		"RULE_BLOCKED": {
			"source_id":             "nacos-prod",
			"rule_id":               "flow:/api/v1/users",
			"rule_version_epoch":    float64(1),
			"rule_version_revision": float64(0),
			"rule_version_checksum": testChecksum,
			"exec_result":           "BLOCKED",
			"failure_class":         nil,
		},
		"RULE_FAILED": {
			"source_id":             "nacos-prod",
			"rule_id":               "flow:/api/v1/users",
			"rule_version_epoch":    float64(1),
			"rule_version_revision": float64(0),
			"rule_version_checksum": testChecksum,
			"exec_result":           "FAILED",
			"failure_class":         "DECODE_FAILED",
		},
	}
	for kind, payload := range payloadByKind {
		obj := validEnvelopeMap()
		obj["event_kind"] = kind
		obj["event_payload"] = payload
		raw, err := EncodeEnvelope(obj)
		if err != nil {
			t.Fatalf("encode %s: %v", kind, err)
		}
		if _, err := DecodeEnvelope(raw); err != nil {
			t.Fatalf("decode %s: %v", kind, err)
		}
	}
}

func TestRejectsReceivedAtInIngressEnvelope(t *testing.T) {
	obj := validEnvelopeMap()
	obj["received_at"] = testTimeAck
	_, err := DecodeEnvelope(mustMarshal(t, obj))
	if !errIsCode(err, "MALFORMED_ENVELOPE") {
		t.Fatalf("expected MALFORMED_ENVELOPE, got %v", err)
	}
}

func TestRejectsUnknownEventKind(t *testing.T) {
	obj := validEnvelopeMap()
	obj["event_kind"] = "MAGIC_EVENT"
	_, err := DecodeEnvelope(mustMarshal(t, obj))
	if !errIsCode(err, "UNKNOWN_EVENT_KIND") {
		t.Fatalf("expected UNKNOWN_EVENT_KIND, got %v", err)
	}
}

func TestRejectsBatchMixedInstanceID(t *testing.T) {
	obj := validBatchMap()
	ev := obj["events"].([]interface{})[0].(map[string]interface{})
	ev["instance_id"] = "660e8400-e29b-41d4-a716-446655440099"
	_, err := DecodeBatch(mustMarshal(t, obj))
	if !errIsCode(err, "MALFORMED_ENVELOPE") {
		t.Fatalf("expected MALFORMED_ENVELOPE, got %v", err)
	}
}

func TestRejectsBatchMixedStartupEpoch(t *testing.T) {
	obj := validBatchMap()
	ev := obj["events"].([]interface{})[0].(map[string]interface{})
	ev["startup_epoch"] = float64(999)
	_, err := DecodeBatch(mustMarshal(t, obj))
	if !errIsCode(err, "MALFORMED_ENVELOPE") {
		t.Fatalf("expected MALFORMED_ENVELOPE, got %v", err)
	}
}

func TestRejectsOversizedEnvelope(t *testing.T) {
	raw := []byte(`{"x":"` + strings.Repeat("a", EnvelopeMaxSizeBytes+100) + `"}`)
	_, err := DecodeEnvelope(raw)
	if !errIsCode(err, "ENVELOPE_TOO_LARGE") {
		t.Fatalf("expected ENVELOPE_TOO_LARGE, got %v", err)
	}
}

func TestRejectsOversizedBatch(t *testing.T) {
	raw := []byte(`{"x":"` + strings.Repeat("a", BatchMaxSizeBytes+100) + `"}`)
	_, err := DecodeBatch(raw)
	if !errIsCode(err, "BATCH_TOO_LARGE") {
		t.Fatalf("expected BATCH_TOO_LARGE, got %v", err)
	}
}

func TestRejectsBadChecksum(t *testing.T) {
	obj := validEnvelopeMap()
	obj["event_payload"].(map[string]interface{})["rule_version_checksum"] =
		"md5:" + strings.Repeat("a", 32)
	_, err := DecodeEnvelope(mustMarshal(t, obj))
	if !errIsCode(err, "PAYLOAD_SCHEMA_MISMATCH") {
		t.Fatalf("expected PAYLOAD_SCHEMA_MISMATCH, got %v", err)
	}
}

func TestRejectsAckSequencesNotLength1(t *testing.T) {
	obj := validAckMap()
	obj["ack_sequences"] = []interface{}{}
	_, err := DecodeAck(mustMarshal(t, obj))
	if !errIsCode(err, "MALFORMED_ENVELOPE") {
		t.Fatalf("expected MALFORMED_ENVELOPE, got %v", err)
	}
}

func TestRejectsUnknownErrorCode(t *testing.T) {
	obj := validErrorMap()
	obj["error_code"] = "MAGIC"
	_, err := DecodeErrorEnvelope(mustMarshal(t, obj))
	if !errIsCode(err, "MALFORMED_ENVELOPE") {
		t.Fatalf("expected MALFORMED_ENVELOPE, got %v", err)
	}
}

func TestRejectsWrongProtocolVersion(t *testing.T) {
	obj := validEnvelopeMap()
	obj["protocol_version"] = "atlas-richie.reporting/v0"
	_, err := DecodeEnvelope(mustMarshal(t, obj))
	if !errIsCode(err, "PROTOCOL_VERSION_MISMATCH") {
		t.Fatalf("expected PROTOCOL_VERSION_MISMATCH, got %v", err)
	}
}

func TestRejectsHealthPartialVersion(t *testing.T) {
	obj := validEnvelopeMap()
	obj["event_kind"] = "RULE_SOURCE_STALE"
	obj["event_payload"] = map[string]interface{}{
		"source_id":          "nacos-prod",
		"health_class":       "STALE",
		"reason_class":       "EMPTY_DATA_ID",
		"rule_version_epoch": float64(1),
	}
	_, err := DecodeEnvelope(mustMarshal(t, obj))
	if !errIsCode(err, "PAYLOAD_SCHEMA_MISMATCH") {
		t.Fatalf("expected PAYLOAD_SCHEMA_MISMATCH, got %v", err)
	}
}

func TestRejectsExecAppliedWithFailureClass(t *testing.T) {
	obj := validEnvelopeMap()
	obj["event_kind"] = "RULE_APPLIED"
	obj["event_payload"] = map[string]interface{}{
		"source_id":             "nacos-prod",
		"rule_id":               "flow:/api/v1/users",
		"rule_version_epoch":    float64(1),
		"rule_version_revision": float64(0),
		"rule_version_checksum": testChecksum,
		"exec_result":           "APPLIED",
		"failure_class":         "DECODE_FAILED",
	}
	_, err := DecodeEnvelope(mustMarshal(t, obj))
	if !errIsCode(err, "PAYLOAD_SCHEMA_MISMATCH") {
		t.Fatalf("expected PAYLOAD_SCHEMA_MISMATCH, got %v", err)
	}
}

func TestRejectsExecFailedMissingFailureClass(t *testing.T) {
	obj := validEnvelopeMap()
	obj["event_kind"] = "RULE_FAILED"
	obj["event_payload"] = map[string]interface{}{
		"source_id":             "nacos-prod",
		"rule_id":               "flow:/api/v1/users",
		"rule_version_epoch":    float64(1),
		"rule_version_revision": float64(0),
		"rule_version_checksum": testChecksum,
		"exec_result":           "FAILED",
		"failure_class":         nil,
	}
	_, err := DecodeEnvelope(mustMarshal(t, obj))
	if !errIsCode(err, "PAYLOAD_SCHEMA_MISMATCH") {
		t.Fatalf("expected PAYLOAD_SCHEMA_MISMATCH, got %v", err)
	}
}

func mustMarshal(t *testing.T, v interface{}) []byte {
	t.Helper()
	raw, err := json.Marshal(v)
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	return raw
}

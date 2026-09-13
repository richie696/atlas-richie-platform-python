// CodecTest.java: Java internal unit tests for the V1 reporting codec.
//
// 1:1 mirror of foundation/contracts/tests/reporting/v1/test_reporting_codec.py
// and the wire spec. At least 5 cases (3 valid + 5 invalid).
package com.atlas_richie.reporting;

import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

public class CodecTest {

    private static final String TEST_UUID_V4 = "550e8400-e29b-41d4-a716-446655440000";
    private static final String TEST_UUID_V4_2 = "550e8400-e29b-41d4-a716-446655440001";
    private static final String TEST_CHECKSUM =
        "sha256:abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789";
    private static final String TEST_TIME = "2026-09-13T10:00:00.123456Z";
    private static final String TEST_TIME_BATCH = "2026-09-13T10:00:00.000001Z";
    private static final String TEST_TIME_ACK = "2026-09-13T10:00:00.456789Z";

    static Map<String, Object> validEnvelope() {
        Map<String, Object> env = new LinkedHashMap<>();
        env.put("protocol_version", Codec.PROTOCOL_VERSION);
        env.put("event_kind", "RULE_SOURCE_ACTIVATED");
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("source_id", "nacos-prod");
        payload.put("rule_version_epoch", 1726000000L);
        payload.put("rule_version_revision", 0L);
        payload.put("rule_version_checksum", TEST_CHECKSUM);
        env.put("event_payload", payload);
        env.put("instance_id", TEST_UUID_V4);
        env.put("startup_epoch", 0L);
        env.put("sequence", 1L);
        env.put("captured_at", TEST_TIME);
        return env;
    }

    static Map<String, Object> validBatch() {
        Map<String, Object> batch = new LinkedHashMap<>();
        batch.put("protocol_version", Codec.PROTOCOL_VERSION);
        batch.put("instance_id", TEST_UUID_V4);
        batch.put("startup_epoch", 0L);
        batch.put("batch_id", TEST_UUID_V4_2);
        batch.put("sent_at", TEST_TIME_BATCH);
        batch.put("events", new ArrayList<>(List.of(validEnvelope())));
        batch.put("dropped_count", 0L);
        return batch;
    }

    static Map<String, Object> validAck() {
        Map<String, Object> seq = new LinkedHashMap<>();
        seq.put("instance_id", TEST_UUID_V4);
        seq.put("startup_epoch", 0L);
        seq.put("max_contiguous_sequence", 100L);
        Map<String, Object> ack = new LinkedHashMap<>();
        ack.put("protocol_version", Codec.PROTOCOL_VERSION);
        ack.put("batch_id", TEST_UUID_V4_2);
        ack.put("received_at", TEST_TIME_ACK);
        ack.put("ack_sequences", new ArrayList<>(List.of(seq)));
        ack.put("duplicate_count", 0L);
        return ack;
    }

    static Map<String, Object> validError() {
        Map<String, Object> details = new LinkedHashMap<>();
        details.put("field", "sequence");
        details.put("got_type", "string");
        Map<String, Object> err = new LinkedHashMap<>();
        err.put("protocol_version", Codec.PROTOCOL_VERSION);
        err.put("error_code", "MALFORMED_ENVELOPE");
        err.put("message", "field 'sequence' must be int64, got string");
        err.put("details", details);
        return err;
    }

    @Test
    public void envelopeRoundTrip() throws Exception {
        Map<String, Object> env = validEnvelope();
        byte[] raw = Codec.encodeEnvelope(env);
        for (byte b : raw) {
            char c = (char) b;
            assertFalse(c == ' ' || c == '\t' || c == '\n' || c == '\r',
                "envelope must be compact");
        }
        Map<String, Object> decoded = Codec.decodeEnvelope(raw);
        assertEquals(env.get("instance_id"), decoded.get("instance_id"));
        assertEquals(env.get("event_kind"), decoded.get("event_kind"));
        assertEquals(7, decoded.size());
        assertFalse(decoded.containsKey("received_at"));
    }

    @Test
    public void batchRoundTrip() throws Exception {
        Map<String, Object> batch = validBatch();
        byte[] raw = Codec.encodeBatch(batch);
        Map<String, Object> decoded = Codec.decodeBatch(raw);
        assertEquals(batch.get("instance_id"), decoded.get("instance_id"));
        @SuppressWarnings("unchecked")
        List<Object> evs = (List<Object>) decoded.get("events");
        assertEquals(1, evs.size());
    }

    @Test
    public void ackRoundTrip() throws Exception {
        Map<String, Object> ack = validAck();
        byte[] raw = Codec.encodeAck(ack);
        Map<String, Object> decoded = Codec.decodeAck(raw);
        assertEquals(ack.get("batch_id"), decoded.get("batch_id"));
        @SuppressWarnings("unchecked")
        List<Object> seqs = (List<Object>) decoded.get("ack_sequences");
        assertEquals(1, seqs.size());
    }

    @Test
    public void errorEnvelopeRoundTrip() throws Exception {
        Map<String, Object> err = validError();
        byte[] raw = Codec.encodeErrorEnvelope(err);
        Map<String, Object> decoded = Codec.decodeErrorEnvelope(raw);
        assertEquals(err.get("error_code"), decoded.get("error_code"));
    }

    @Test
    public void allEventKindsAccepted() throws Exception {
        Map<String, Object> base = validEnvelope();
        java.util.Map<String, java.util.Map<String, Object>> payloads = new java.util.LinkedHashMap<>();
        {
            Map<String, Object> p = new LinkedHashMap<>();
            p.put("source_id", "nacos-prod");
            p.put("rule_version_epoch", 1L);
            p.put("rule_version_revision", 0L);
            p.put("rule_version_checksum", TEST_CHECKSUM);
            payloads.put("RULE_SOURCE_ACTIVATED", p);
        }
        {
            Map<String, Object> p = new LinkedHashMap<>();
            p.put("source_id", "nacos-prod");
            p.put("health_class", "STALE");
            p.put("reason_class", "EMPTY_DATA_ID");
            p.put("rule_version_epoch", 1L);
            p.put("rule_version_revision", 0L);
            p.put("rule_version_checksum", TEST_CHECKSUM);
            payloads.put("RULE_SOURCE_STALE", p);
        }
        {
            Map<String, Object> p = new LinkedHashMap<>();
            p.put("source_id", "nacos-prod");
            p.put("health_class", "DISCONNECTED");
            p.put("reason_class", "NETWORK_UNAVAILABLE");
            p.put("reason_message", "nacos unreachable");
            p.put("rule_version_epoch", 1L);
            p.put("rule_version_revision", 0L);
            p.put("rule_version_checksum", TEST_CHECKSUM);
            payloads.put("RULE_SOURCE_DEGRADED", p);
        }
        {
            Map<String, Object> p = new LinkedHashMap<>();
            p.put("source_id", "nacos-prod");
            p.put("rule_id", "flow:/api/v1/users");
            p.put("rule_version_epoch", 1L);
            p.put("rule_version_revision", 0L);
            p.put("rule_version_checksum", TEST_CHECKSUM);
            p.put("exec_result", "APPLIED");
            p.put("failure_class", null);
            payloads.put("RULE_APPLIED", p);
        }
        {
            Map<String, Object> p = new LinkedHashMap<>();
            p.put("source_id", "nacos-prod");
            p.put("rule_id", "flow:/api/v1/users");
            p.put("rule_version_epoch", 1L);
            p.put("rule_version_revision", 0L);
            p.put("rule_version_checksum", TEST_CHECKSUM);
            p.put("exec_result", "BLOCKED");
            p.put("failure_class", null);
            payloads.put("RULE_BLOCKED", p);
        }
        {
            Map<String, Object> p = new LinkedHashMap<>();
            p.put("source_id", "nacos-prod");
            p.put("rule_id", "flow:/api/v1/users");
            p.put("rule_version_epoch", 1L);
            p.put("rule_version_revision", 0L);
            p.put("rule_version_checksum", TEST_CHECKSUM);
            p.put("exec_result", "FAILED");
            p.put("failure_class", "DECODE_FAILED");
            payloads.put("RULE_FAILED", p);
        }
        for (Map.Entry<String, Map<String, Object>> e : payloads.entrySet()) {
            base.put("event_kind", e.getKey());
            base.put("event_payload", e.getValue());
            byte[] raw = Codec.encodeEnvelope(base);
            Map<String, Object> decoded = Codec.decodeEnvelope(raw);
            assertEquals(e.getKey(), decoded.get("event_kind"));
        }
    }

    @Test
    public void rejectsReceivedAtInIngressEnvelope() {
        Map<String, Object> env = validEnvelope();
        env.put("received_at", TEST_TIME_ACK);
        CodecException ex = assertThrows(CodecException.class, () -> Codec.decodeEnvelope(Json.write(env)));
        assertEquals("MALFORMED_ENVELOPE", ex.getCode());
    }

    @Test
    public void rejectsUnknownEventKind() {
        Map<String, Object> env = validEnvelope();
        env.put("event_kind", "MAGIC_EVENT");
        CodecException ex = assertThrows(CodecException.class, () -> Codec.decodeEnvelope(Json.write(env)));
        assertEquals("UNKNOWN_EVENT_KIND", ex.getCode());
    }

    @Test
    public void rejectsBatchMixedInstanceId() {
        Map<String, Object> batch = validBatch();
        @SuppressWarnings("unchecked")
        List<Object> events = (List<Object>) batch.get("events");
        ((Map<String, Object>) events.get(0)).put("instance_id",
            "660e8400-e29b-41d4-a716-446655440099");
        CodecException ex = assertThrows(CodecException.class, () -> Codec.decodeBatch(Json.write(batch)));
        assertEquals("MALFORMED_ENVELOPE", ex.getCode());
        assertTrue(ex.getMessage().contains("instance_id"));
    }

    @Test
    public void rejectsBatchMixedStartupEpoch() {
        Map<String, Object> batch = validBatch();
        @SuppressWarnings("unchecked")
        List<Object> events = (List<Object>) batch.get("events");
        ((Map<String, Object>) events.get(0)).put("startup_epoch", 999L);
        CodecException ex = assertThrows(CodecException.class, () -> Codec.decodeBatch(Json.write(batch)));
        assertEquals("MALFORMED_ENVELOPE", ex.getCode());
    }

    @Test
    public void rejectsOversizedEnvelope() {
        StringBuilder sb = new StringBuilder("{\"x\":\"");
        for (int i = 0; i < Codec.ENVELOPE_MAX_SIZE_BYTES + 100; i++) sb.append('a');
        sb.append("\"}");
        byte[] raw = sb.toString().getBytes(StandardCharsets.UTF_8);
        CodecException ex = assertThrows(CodecException.class, () -> Codec.decodeEnvelope(raw));
        assertEquals("ENVELOPE_TOO_LARGE", ex.getCode());
    }

    @Test
    public void rejectsOversizedBatch() {
        StringBuilder sb = new StringBuilder("{\"x\":\"");
        for (int i = 0; i < Codec.BATCH_MAX_SIZE_BYTES + 100; i++) sb.append('a');
        sb.append("\"}");
        byte[] raw = sb.toString().getBytes(StandardCharsets.UTF_8);
        CodecException ex = assertThrows(CodecException.class, () -> Codec.decodeBatch(raw));
        assertEquals("BATCH_TOO_LARGE", ex.getCode());
    }

    @Test
    public void rejectsBadChecksum() throws Exception {
        Map<String, Object> env = validEnvelope();
        @SuppressWarnings("unchecked")
        Map<String, Object> p = (Map<String, Object>) env.get("event_payload");
        p.put("rule_version_checksum", "md5:" + "a".repeat(32));
        CodecException ex = assertThrows(CodecException.class, () -> Codec.decodeEnvelope(Json.write(env)));
        assertEquals("PAYLOAD_SCHEMA_MISMATCH", ex.getCode());
    }

    @Test
    public void rejectsAckSequencesNotLength1() throws Exception {
        Map<String, Object> ack = validAck();
        ack.put("ack_sequences", new ArrayList<>());
        CodecException ex = assertThrows(CodecException.class, () -> Codec.decodeAck(Json.write(ack)));
        assertEquals("MALFORMED_ENVELOPE", ex.getCode());
    }

    @Test
    public void rejectsUnknownErrorCode() throws Exception {
        Map<String, Object> err = validError();
        err.put("error_code", "MAGIC");
        CodecException ex = assertThrows(CodecException.class, () -> Codec.decodeErrorEnvelope(Json.write(err)));
        assertEquals("MALFORMED_ENVELOPE", ex.getCode());
    }

    @Test
    public void rejectsWrongProtocolVersion() throws Exception {
        Map<String, Object> env = validEnvelope();
        env.put("protocol_version", "atlas-richie.reporting/v0");
        CodecException ex = assertThrows(CodecException.class, () -> Codec.decodeEnvelope(Json.write(env)));
        assertEquals("PROTOCOL_VERSION_MISMATCH", ex.getCode());
    }

    @Test
    public void rejectsHealthPartialVersion() throws Exception {
        Map<String, Object> env = validEnvelope();
        env.put("event_kind", "RULE_SOURCE_STALE");
        Map<String, Object> p = new LinkedHashMap<>();
        p.put("source_id", "nacos-prod");
        p.put("health_class", "STALE");
        p.put("reason_class", "EMPTY_DATA_ID");
        p.put("rule_version_epoch", 1L);
        env.put("event_payload", p);
        CodecException ex = assertThrows(CodecException.class, () -> Codec.decodeEnvelope(Json.write(env)));
        assertEquals("PAYLOAD_SCHEMA_MISMATCH", ex.getCode());
    }

    @Test
    public void rejectsExecAppliedWithFailureClass() throws Exception {
        Map<String, Object> env = validEnvelope();
        env.put("event_kind", "RULE_APPLIED");
        Map<String, Object> p = new LinkedHashMap<>();
        p.put("source_id", "nacos-prod");
        p.put("rule_id", "flow:/api/v1/users");
        p.put("rule_version_epoch", 1L);
        p.put("rule_version_revision", 0L);
        p.put("rule_version_checksum", TEST_CHECKSUM);
        p.put("exec_result", "APPLIED");
        p.put("failure_class", "DECODE_FAILED");
        env.put("event_payload", p);
        CodecException ex = assertThrows(CodecException.class, () -> Codec.decodeEnvelope(Json.write(env)));
        assertEquals("PAYLOAD_SCHEMA_MISMATCH", ex.getCode());
    }

    @Test
    public void rejectsExecFailedMissingFailureClass() throws Exception {
        Map<String, Object> env = validEnvelope();
        env.put("event_kind", "RULE_FAILED");
        Map<String, Object> p = new LinkedHashMap<>();
        p.put("source_id", "nacos-prod");
        p.put("rule_id", "flow:/api/v1/users");
        p.put("rule_version_epoch", 1L);
        p.put("rule_version_revision", 0L);
        p.put("rule_version_checksum", TEST_CHECKSUM);
        p.put("exec_result", "FAILED");
        p.put("failure_class", null);
        env.put("event_payload", p);
        CodecException ex = assertThrows(CodecException.class, () -> Codec.decodeEnvelope(Json.write(env)));
        assertEquals("PAYLOAD_SCHEMA_MISMATCH", ex.getCode());
    }
}

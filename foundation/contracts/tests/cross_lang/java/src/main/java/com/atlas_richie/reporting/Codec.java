// Codec.java: Atlas Richie Agent Reporting Protocol V1 — strict JSON codec (DRAFT).
//
// 1:1 mirror of foundation/contracts/src/atlas_richie/contracts/reporting/v1/codec.py
// plus components/sentinel/docs/protocol/reporting-protocol-01-envelope-v1.md
// and reporting-protocol-02-transport-v1.md.
package com.atlas_richie.reporting;

import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.regex.Pattern;

public final class Codec {

    public static final String PROTOCOL_VERSION = "atlas-richie.reporting/v1";
    public static final int ENVELOPE_MAX_SIZE_BYTES = 16 * 1024;
    public static final int BATCH_MAX_SIZE_BYTES = 64 * 1024;
    public static final int BATCH_MAX_EVENTS = 256;
    public static final long INT64_MIN = 0L;
    public static final long INT64_MAX = (1L << 53) - 1L;
    public static final int SOURCE_ID_MAX_LEN = 256;
    public static final int RULE_ID_MAX_LEN = 256;
    public static final int REASON_MESSAGE_MAX_LEN = 64;
    public static final int ERROR_MESSAGE_MAX_LEN = 1024;
    public static final String CHECKSUM_PREFIX = "sha256:";
    public static final int CHECKSUM_HEX_LEN = 64;
    public static final String X_ATLAS_REPORTING_HEADER = "X-Atlas-Reporting-Token";
    public static final int AUTH_TOKEN_MIN_LEN = 16;

    public static final Set<String> EVENT_KINDS = Set.of(
        "RULE_SOURCE_ACTIVATED",
        "RULE_SOURCE_STALE",
        "RULE_SOURCE_DEGRADED",
        "RULE_APPLIED",
        "RULE_BLOCKED",
        "RULE_FAILED"
    );
    public static final Set<String> HEALTH_CLASSES = Set.of(
        "STALE", "DEGRADED", "DISCONNECTED"
    );
    public static final Set<String> REASON_CLASSES = Set.of(
        "EMPTY_DATA_ID",
        "NETWORK_TIMEOUT",
        "NETWORK_UNAVAILABLE",
        "AUTH_FAILED",
        "DECODE_FAILED",
        "STATE_INVALID",
        "UNKNOWN"
    );
    public static final Set<String> EXEC_RESULTS = Set.of(
        "APPLIED", "BLOCKED", "FAILED"
    );
    public static final Set<String> ERROR_CODES = Set.of(
        "PROTOCOL_VERSION_MISMATCH",
        "MALFORMED_ENVELOPE",
        "UNKNOWN_EVENT_KIND",
        "PAYLOAD_SCHEMA_MISMATCH",
        "INSTANCE_ID_EMPTY",
        "SEQUENCE_NOT_MONOTONIC",
        "SEQUENCE_GAP",
        "STALE_EPOCH",
        "ENVELOPE_TOO_LARGE",
        "BATCH_TOO_LARGE",
        "AUTH_FAILED"
    );

    public static final Set<String> ENVELOPE_REQUIRED_FIELDS = Set.of(
        "protocol_version", "event_kind", "event_payload",
        "instance_id", "startup_epoch", "sequence", "captured_at"
    );
    public static final Set<String> BATCH_REQUIRED_FIELDS = Set.of(
        "protocol_version", "instance_id", "startup_epoch", "batch_id",
        "sent_at", "events", "dropped_count"
    );
    public static final Set<String> ACK_REQUIRED_FIELDS = Set.of(
        "protocol_version", "batch_id", "received_at",
        "ack_sequences", "duplicate_count"
    );
    public static final Set<String> ERROR_REQUIRED_FIELDS = Set.of(
        "protocol_version", "error_code", "message", "details"
    );

    private static final Pattern UUID_V4_RE = Pattern.compile(
        "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$");
    private static final Pattern ISO_8601_UTC_MICRO_RE = Pattern.compile(
        "^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}\\.\\d{6}Z$");
    private static final Pattern CHECKSUM_RE = Pattern.compile(
        "^sha256:[0-9a-f]{64}$");

    private Codec() {}

    private static void validateUuid(String name, Object v) throws CodecException {
        if (!(v instanceof String) || !UUID_V4_RE.matcher((String) v).matches()) {
            throw new CodecException("MALFORMED_ENVELOPE",
                name + " must be UUID v4 (8-4-4-4-12 lowercase hex)");
        }
    }

    private static void validateIso8601UtcMicro(String name, Object v)
            throws CodecException {
        if (!(v instanceof String) || !ISO_8601_UTC_MICRO_RE.matcher((String) v).matches()) {
            throw new CodecException("MALFORMED_ENVELOPE",
                name + " must be ISO 8601 UTC microsecond " +
                "(YYYY-MM-DDTHH:MM:SS.ffffffZ)");
        }
    }

    private static void validateInt64(String name, Object v) throws CodecException {
        long n;
        if (v instanceof Long) {
            n = (Long) v;
        } else if (v instanceof Integer) {
            n = ((Integer) v).longValue();
        } else {
            throw new CodecException("MALFORMED_ENVELOPE",
                name + " must be int");
        }
        if (n < INT64_MIN || n > INT64_MAX) {
            throw new CodecException("MALFORMED_ENVELOPE",
                name + " must be int64 in [0, 2^53-1] (got " + n + ")");
        }
    }

    private static void validateProtocolVersion(Map<String, Object> obj)
            throws CodecException {
        Object pv = obj.get("protocol_version");
        if (!PROTOCOL_VERSION.equals(pv)) {
            throw new CodecException("PROTOCOL_VERSION_MISMATCH",
                "expected protocol_version=\"" + PROTOCOL_VERSION + "\", got " + pv);
        }
    }

    private static void validateCommonRuleVersionTriplet(
            Map<String, Object> payload) throws CodecException {
        validateInt64("rule_version_epoch", payload.get("rule_version_epoch"));
        validateInt64("rule_version_revision", payload.get("rule_version_revision"));
        Object cs = payload.get("rule_version_checksum");
        if (!(cs instanceof String) || !CHECKSUM_RE.matcher((String) cs).matches()) {
            throw new CodecException("PAYLOAD_SCHEMA_MISMATCH",
                "rule_version_checksum must be 'sha256:' + 64 hex chars");
        }
    }

    private static void validateSourceId(Object v) throws CodecException {
        if (!(v instanceof String) || ((String) v).isEmpty()) {
            throw new CodecException("PAYLOAD_SCHEMA_MISMATCH",
                "source_id must be non-empty string");
        }
        if (((String) v).length() > SOURCE_ID_MAX_LEN) {
            throw new CodecException("PAYLOAD_SCHEMA_MISMATCH",
                "source_id exceeds " + SOURCE_ID_MAX_LEN + " chars");
        }
    }

    private static void validateRuleVersionTripletAllOrNone(
            Map<String, Object> payload) throws CodecException {
        boolean hasEpoch = payload.containsKey("rule_version_epoch");
        boolean hasRev = payload.containsKey("rule_version_revision");
        boolean hasCs = payload.containsKey("rule_version_checksum");
        if ((hasEpoch || hasRev || hasCs) && !(hasEpoch && hasRev && hasCs)) {
            throw new CodecException("PAYLOAD_SCHEMA_MISMATCH",
                "3 rule_version_* fields must be all present or all omitted " +
                "(成组可选, 协议 §5.2)");
        }
        if (hasEpoch && hasRev && hasCs) {
            validateCommonRuleVersionTriplet(payload);
        }
    }

    private static List<String> sortedKeys(Map<String, Object> m) {
        String[] keys = m.keySet().toArray(new String[0]);
        Arrays.sort(keys);
        return Arrays.asList(keys);
    }

    @SuppressWarnings("unchecked")
    private static void validatePayloadRuleSourceActivated(
            Map<String, Object> payload) throws CodecException {
        Set<String> required = Set.of(
            "source_id", "rule_version_epoch",
            "rule_version_revision", "rule_version_checksum");
        if (!payload.keySet().equals(required)) {
            throw new CodecException("PAYLOAD_SCHEMA_MISMATCH",
                "RuleSourceActivatedPayload must have " + new java.util.TreeSet<>(required) +
                ", got " + sortedKeys(payload));
        }
        validateSourceId(payload.get("source_id"));
        validateCommonRuleVersionTriplet(payload);
    }

    @SuppressWarnings("unchecked")
    private static void validatePayloadRuleSourceHealth(
            Map<String, Object> payload) throws CodecException {
        Set<String> required = Set.of("source_id", "health_class", "reason_class");
        Set<String> allowed = Set.of(
            "source_id",
            "health_class",
            "reason_class",
            "rule_version_epoch",
            "rule_version_revision",
            "rule_version_checksum",
            "reason_message");
        for (String k : payload.keySet()) {
            if (!allowed.contains(k)) {
                throw new CodecException("PAYLOAD_SCHEMA_MISMATCH",
                    "RuleSourceHealthPayload must have " + new java.util.TreeSet<>(allowed) +
                    ", got " + sortedKeys(payload));
            }
        }
        for (String k : required) {
            if (!payload.containsKey(k)) {
                throw new CodecException("PAYLOAD_SCHEMA_MISMATCH",
                    "RuleSourceHealthPayload missing required field \"" + k + "\"");
            }
        }
        validateSourceId(payload.get("source_id"));
        Object hc = payload.get("health_class");
        if (!(hc instanceof String) || !HEALTH_CLASSES.contains(hc)) {
            throw new CodecException("PAYLOAD_SCHEMA_MISMATCH",
                "health_class must be one of STALE/DEGRADED/DISCONNECTED, got " + asString(hc));
        }
        Object rc = payload.get("reason_class");
        if (!(rc instanceof String) || !REASON_CLASSES.contains(rc)) {
            throw new CodecException("PAYLOAD_SCHEMA_MISMATCH",
                "reason_class must be one of ReasonClass enum, got " + asString(rc));
        }
        validateRuleVersionTripletAllOrNone(payload);
        if (payload.containsKey("reason_message")) {
            Object msg = payload.get("reason_message");
            if (!(msg instanceof String)) {
                throw new CodecException("PAYLOAD_SCHEMA_MISMATCH",
                    "reason_message must be string");
            }
            if (((String) msg).getBytes(StandardCharsets.UTF_8).length > REASON_MESSAGE_MAX_LEN) {
                throw new CodecException("PAYLOAD_SCHEMA_MISMATCH",
                    "reason_message exceeds " + REASON_MESSAGE_MAX_LEN +
                    " bytes (脱敏 reason 上限, 协议 §5.2)");
            }
        }
    }

    @SuppressWarnings("unchecked")
    private static void validatePayloadRuleExec(
            Map<String, Object> payload) throws CodecException {
        Set<String> required = Set.of(
            "source_id", "rule_id",
            "rule_version_epoch", "rule_version_revision", "rule_version_checksum",
            "exec_result", "failure_class");
        if (!payload.keySet().equals(required)) {
            throw new CodecException("PAYLOAD_SCHEMA_MISMATCH",
                "RuleExecPayload must have " + new java.util.TreeSet<>(required) +
                ", got " + sortedKeys(payload));
        }
        validateSourceId(payload.get("source_id"));
        Object ruleId = payload.get("rule_id");
        if (!(ruleId instanceof String) || ((String) ruleId).isEmpty()) {
            throw new CodecException("PAYLOAD_SCHEMA_MISMATCH",
                "rule_id must be non-empty string");
        }
        if (((String) ruleId).length() > RULE_ID_MAX_LEN) {
            throw new CodecException("PAYLOAD_SCHEMA_MISMATCH",
                "rule_id exceeds " + RULE_ID_MAX_LEN + " chars");
        }
        validateCommonRuleVersionTriplet(payload);
        Object er = payload.get("exec_result");
        if (!(er instanceof String) || !EXEC_RESULTS.contains(er)) {
            throw new CodecException("PAYLOAD_SCHEMA_MISMATCH",
                "exec_result must be one of APPLIED/BLOCKED/FAILED, got " + asString(er));
        }
        Object fc = payload.get("failure_class");
        if ("FAILED".equals(er)) {
            if (fc == null) {
                throw new CodecException("PAYLOAD_SCHEMA_MISMATCH",
                    "exec_result=FAILED requires failure_class not None (协议 §5.3)");
            }
            if (!(fc instanceof String) || !REASON_CLASSES.contains(fc)) {
                throw new CodecException("PAYLOAD_SCHEMA_MISMATCH",
                    "failure_class must be ReasonClass enum, got " + asString(fc));
            }
        } else {
            if (fc != null) {
                throw new CodecException("PAYLOAD_SCHEMA_MISMATCH",
                    "exec_result=" + er + " requires failure_class=None (协议 §5.3)");
            }
        }
    }

    @SuppressWarnings("unchecked")
    private static void validatePayload(String eventKind,
                                       Map<String, Object> payload) throws CodecException {
        if (!EVENT_KINDS.contains(eventKind)) {
            throw new CodecException("UNKNOWN_EVENT_KIND",
                "unknown event_kind: \"" + eventKind + "\"");
        }
        switch (eventKind) {
            case "RULE_SOURCE_ACTIVATED":
                validatePayloadRuleSourceActivated(payload);
                break;
            case "RULE_SOURCE_STALE":
            case "RULE_SOURCE_DEGRADED":
                validatePayloadRuleSourceHealth(payload);
                break;
            case "RULE_APPLIED":
            case "RULE_BLOCKED":
            case "RULE_FAILED":
                validatePayloadRuleExec(payload);
                break;
            default:
                throw new CodecException("UNKNOWN_EVENT_KIND",
                    "unsupported event_kind: \"" + eventKind + "\"");
        }
    }

    @SuppressWarnings("unchecked")
    private static void validateEnvelopeDict(Map<String, Object> obj)
            throws CodecException {
        List<String> missing = new ArrayList<>();
        for (String k : ENVELOPE_REQUIRED_FIELDS) {
            if (!obj.containsKey(k)) missing.add(k);
        }
        if (!missing.isEmpty()) {
            java.util.Collections.sort(missing);
            throw new CodecException("MALFORMED_ENVELOPE",
                "missing required fields: " + missing);
        }
        List<String> unknown = new ArrayList<>();
        for (String k : obj.keySet()) {
            if (!ENVELOPE_REQUIRED_FIELDS.contains(k)) unknown.add(k);
        }
        if (!unknown.isEmpty()) {
            java.util.Collections.sort(unknown);
            throw new CodecException("MALFORMED_ENVELOPE",
                "unknown fields not allowed (received_at 不再是 ingress 字段, " +
                "协议 BUG 收口后 7 字段): " + unknown);
        }
        validateProtocolVersion(obj);
        Object ek = obj.get("event_kind");
        if (!(ek instanceof String) || !EVENT_KINDS.contains(ek)) {
            throw new CodecException("UNKNOWN_EVENT_KIND",
                "unknown event_kind: " + ek);
        }
        validateUuid("instance_id", obj.get("instance_id"));
        validateInt64("startup_epoch", obj.get("startup_epoch"));
        validateInt64("sequence", obj.get("sequence"));
        validateIso8601UtcMicro("captured_at", obj.get("captured_at"));
        Object ep = obj.get("event_payload");
        if (!(ep instanceof Map)) {
            throw new CodecException("MALFORMED_ENVELOPE",
                "event_payload must be a JSON object");
        }
        validatePayload((String) ek, (Map<String, Object>) ep);
    }

    @SuppressWarnings("unchecked")
    public static Map<String, Object> decodeEnvelope(byte[] raw)
            throws CodecException {
        if (raw.length > ENVELOPE_MAX_SIZE_BYTES) {
            throw new CodecException("ENVELOPE_TOO_LARGE",
                "envelope exceeds " + ENVELOPE_MAX_SIZE_BYTES +
                " bytes (actual: " + raw.length + ")");
        }
        Object parsed;
        try {
            parsed = Json.parse(raw);
        } catch (CodecException e) {
            throw new CodecException("MALFORMED_ENVELOPE",
                "invalid JSON: " + e.getMessage().replaceFirst("^\\[\\w+\\]\\s*", ""));
        }
        if (!(parsed instanceof Map)) {
            throw new CodecException("MALFORMED_ENVELOPE",
                "envelope must be a JSON object");
        }
        Map<String, Object> obj = (Map<String, Object>) parsed;
        validateEnvelopeDict(obj);
        return obj;
    }

    @SuppressWarnings("unchecked")
    public static byte[] encodeEnvelope(Map<String, Object> obj) throws CodecException {
        validateEnvelopeDict(obj);
        String kind = (String) obj.get("event_kind");
        Map<String, Object> ep = (Map<String, Object>) obj.get("event_payload");
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("protocol_version", obj.get("protocol_version"));
        out.put("event_kind", kind);
        out.put("event_payload", canonicalPayload(kind, ep));
        out.put("instance_id", obj.get("instance_id"));
        out.put("startup_epoch", asLong(obj.get("startup_epoch")));
        out.put("sequence", asLong(obj.get("sequence")));
        out.put("captured_at", obj.get("captured_at"));
        byte[] raw = Json.write(out);
        if (raw.length > ENVELOPE_MAX_SIZE_BYTES) {
            throw new CodecException("ENVELOPE_TOO_LARGE",
                "envelope exceeds " + ENVELOPE_MAX_SIZE_BYTES +
                " bytes (actual: " + raw.length + ")");
        }
        return raw;
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> canonicalPayload(String kind,
            Map<String, Object> payload) {
        Map<String, Object> out = new LinkedHashMap<>();
        switch (kind) {
            case "RULE_SOURCE_ACTIVATED":
                if (payload.containsKey("source_id")) out.put("source_id", payload.get("source_id"));
                if (payload.containsKey("rule_version_epoch")) out.put("rule_version_epoch", asLong(payload.get("rule_version_epoch")));
                if (payload.containsKey("rule_version_revision")) out.put("rule_version_revision", asLong(payload.get("rule_version_revision")));
                if (payload.containsKey("rule_version_checksum")) out.put("rule_version_checksum", payload.get("rule_version_checksum"));
                break;
            case "RULE_SOURCE_STALE":
            case "RULE_SOURCE_DEGRADED":
                if (payload.containsKey("source_id")) out.put("source_id", payload.get("source_id"));
                if (payload.containsKey("health_class")) out.put("health_class", payload.get("health_class"));
                if (payload.containsKey("reason_class")) out.put("reason_class", payload.get("reason_class"));
                if (payload.containsKey("reason_message")) out.put("reason_message", payload.get("reason_message"));
                if (payload.containsKey("rule_version_epoch")) out.put("rule_version_epoch", asLong(payload.get("rule_version_epoch")));
                if (payload.containsKey("rule_version_revision")) out.put("rule_version_revision", asLong(payload.get("rule_version_revision")));
                if (payload.containsKey("rule_version_checksum")) out.put("rule_version_checksum", payload.get("rule_version_checksum"));
                break;
            case "RULE_APPLIED":
            case "RULE_BLOCKED":
            case "RULE_FAILED":
                if (payload.containsKey("source_id")) out.put("source_id", payload.get("source_id"));
                if (payload.containsKey("rule_id")) out.put("rule_id", payload.get("rule_id"));
                if (payload.containsKey("rule_version_epoch")) out.put("rule_version_epoch", asLong(payload.get("rule_version_epoch")));
                if (payload.containsKey("rule_version_revision")) out.put("rule_version_revision", asLong(payload.get("rule_version_revision")));
                if (payload.containsKey("rule_version_checksum")) out.put("rule_version_checksum", payload.get("rule_version_checksum"));
                if (payload.containsKey("exec_result")) out.put("exec_result", payload.get("exec_result"));
                if (payload.containsKey("failure_class")) out.put("failure_class", payload.get("failure_class"));
                break;
        }
        return out;
    }

    @SuppressWarnings("unchecked")
    private static void validateBatchDict(Map<String, Object> obj)
            throws CodecException {
        List<String> missing = new ArrayList<>();
        for (String k : BATCH_REQUIRED_FIELDS) {
            if (!obj.containsKey(k)) missing.add(k);
        }
        if (!missing.isEmpty()) {
            java.util.Collections.sort(missing);
            throw new CodecException("MALFORMED_ENVELOPE",
                "batch missing required fields: " + missing);
        }
        List<String> unknown = new ArrayList<>();
        for (String k : obj.keySet()) {
            if (!BATCH_REQUIRED_FIELDS.contains(k)) unknown.add(k);
        }
        if (!unknown.isEmpty()) {
            java.util.Collections.sort(unknown);
            throw new CodecException("MALFORMED_ENVELOPE",
                "batch unknown fields not allowed: " + unknown);
        }
        validateProtocolVersion(obj);
        validateUuid("instance_id", obj.get("instance_id"));
        validateInt64("startup_epoch", obj.get("startup_epoch"));
        validateUuid("batch_id", obj.get("batch_id"));
        validateIso8601UtcMicro("sent_at", obj.get("sent_at"));
        Object evRaw = obj.get("events");
        if (!(evRaw instanceof List)) {
            throw new CodecException("MALFORMED_ENVELOPE",
                "events must be a JSON array");
        }
        List<Object> events = (List<Object>) evRaw;
        if (events.size() < 1 || events.size() > BATCH_MAX_EVENTS) {
            throw new CodecException("MALFORMED_ENVELOPE",
                "events.length must be in [1, " + BATCH_MAX_EVENTS +
                "], got " + events.size());
        }
        for (int i = 0; i < events.size(); i++) {
            Object e = events.get(i);
            if (!(e instanceof Map)) {
                throw new CodecException("MALFORMED_ENVELOPE",
                    "events[" + i + "] must be a JSON object");
            }
            Map<String, Object> evMap = (Map<String, Object>) e;
            if (!obj.get("protocol_version").equals(evMap.get("protocol_version"))) {
                throw new CodecException("MALFORMED_ENVELOPE",
                    "events[" + i + "].protocol_version != batch.protocol_version " +
                    "(禁止混装, 协议 §7.2)");
            }
            if (!obj.get("instance_id").equals(evMap.get("instance_id"))) {
                throw new CodecException("MALFORMED_ENVELOPE",
                    "events[" + i + "].instance_id != batch.instance_id " +
                    "(禁止混装, 协议 §7.2)");
            }
            if (compareInt64(obj.get("startup_epoch"), evMap.get("startup_epoch")) != 0) {
                throw new CodecException("MALFORMED_ENVELOPE",
                    "events[" + i + "].startup_epoch != batch.startup_epoch " +
                    "(禁止混装, 协议 §7.2)");
            }
            byte[] evBytes = Json.write(evMap);
            if (evBytes.length > ENVELOPE_MAX_SIZE_BYTES) {
                throw new CodecException("ENVELOPE_TOO_LARGE",
                    "events[" + i + "] exceeds " + ENVELOPE_MAX_SIZE_BYTES +
                    " bytes (actual: " + evBytes.length + ")");
            }
        }
        validateInt64("dropped_count", obj.get("dropped_count"));
    }

    @SuppressWarnings("unchecked")
    public static Map<String, Object> decodeBatch(byte[] raw) throws CodecException {
        if (raw.length > BATCH_MAX_SIZE_BYTES) {
            throw new CodecException("BATCH_TOO_LARGE",
                "batch exceeds " + BATCH_MAX_SIZE_BYTES +
                " bytes (actual: " + raw.length + ")");
        }
        Object parsed;
        try {
            parsed = Json.parse(raw);
        } catch (CodecException e) {
            throw new CodecException("MALFORMED_ENVELOPE",
                "invalid JSON: " + e.getMessage().replaceFirst("^\\[\\w+\\]\\s*", ""));
        }
        if (!(parsed instanceof Map)) {
            throw new CodecException("MALFORMED_ENVELOPE",
                "batch must be a JSON object");
        }
        Map<String, Object> obj = (Map<String, Object>) parsed;
        validateBatchDict(obj);
        return obj;
    }

    @SuppressWarnings("unchecked")
    public static byte[] encodeBatch(Map<String, Object> obj) throws CodecException {
        validateBatchDict(obj);
        List<Object> eventsRaw = (List<Object>) obj.get("events");
        List<Object> eventsOut = new ArrayList<>();
        for (Object ev : eventsRaw) {
            Map<String, Object> evMap = (Map<String, Object>) ev;
            String kind = (String) evMap.get("event_kind");
            Map<String, Object> ep = (Map<String, Object>) evMap.get("event_payload");
            Map<String, Object> evOut = new LinkedHashMap<>();
            evOut.put("protocol_version", evMap.get("protocol_version"));
            evOut.put("event_kind", kind);
            evOut.put("event_payload", canonicalPayload(kind, ep));
            evOut.put("instance_id", evMap.get("instance_id"));
            evOut.put("startup_epoch", asLong(evMap.get("startup_epoch")));
            evOut.put("sequence", asLong(evMap.get("sequence")));
            evOut.put("captured_at", evMap.get("captured_at"));
            eventsOut.add(evOut);
        }
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("protocol_version", obj.get("protocol_version"));
        out.put("instance_id", obj.get("instance_id"));
        out.put("startup_epoch", asLong(obj.get("startup_epoch")));
        out.put("batch_id", obj.get("batch_id"));
        out.put("sent_at", obj.get("sent_at"));
        out.put("events", eventsOut);
        out.put("dropped_count", asLong(obj.get("dropped_count")));
        byte[] raw = Json.write(out);
        if (raw.length > BATCH_MAX_SIZE_BYTES) {
            throw new CodecException("BATCH_TOO_LARGE",
                "batch exceeds " + BATCH_MAX_SIZE_BYTES +
                " bytes (actual: " + raw.length + ")");
        }
        return raw;
    }

    @SuppressWarnings("unchecked")
    private static void validateAckDict(Map<String, Object> obj) throws CodecException {
        List<String> missing = new ArrayList<>();
        for (String k : ACK_REQUIRED_FIELDS) {
            if (!obj.containsKey(k)) missing.add(k);
        }
        if (!missing.isEmpty()) {
            java.util.Collections.sort(missing);
            throw new CodecException("MALFORMED_ENVELOPE",
                "ack missing required fields: " + missing);
        }
        List<String> unknown = new ArrayList<>();
        for (String k : obj.keySet()) {
            if (!ACK_REQUIRED_FIELDS.contains(k)) unknown.add(k);
        }
        if (!unknown.isEmpty()) {
            java.util.Collections.sort(unknown);
            throw new CodecException("MALFORMED_ENVELOPE",
                "ack unknown fields not allowed: " + unknown);
        }
        validateProtocolVersion(obj);
        validateUuid("batch_id", obj.get("batch_id"));
        validateIso8601UtcMicro("received_at", obj.get("received_at"));
        Object seqs = obj.get("ack_sequences");
        if (!(seqs instanceof List) || ((List<?>) seqs).size() != 1) {
            throw new CodecException("MALFORMED_ENVELOPE",
                "ack_sequences must be a JSON array of length 1");
        }
        Map<String, Object> seq = (Map<String, Object>) ((List<?>) seqs).get(0);
        validateUuid("ack_sequences[0].instance_id", seq.get("instance_id"));
        validateInt64("ack_sequences[0].startup_epoch", seq.get("startup_epoch"));
        validateInt64("ack_sequences[0].max_contiguous_sequence",
            seq.get("max_contiguous_sequence"));
        validateInt64("duplicate_count", obj.get("duplicate_count"));
    }

    @SuppressWarnings("unchecked")
    public static Map<String, Object> decodeAck(byte[] raw) throws CodecException {
        Object parsed;
        try {
            parsed = Json.parse(raw);
        } catch (CodecException e) {
            throw new CodecException("MALFORMED_ENVELOPE",
                "invalid JSON: " + e.getMessage().replaceFirst("^\\[\\w+\\]\\s*", ""));
        }
        if (!(parsed instanceof Map)) {
            throw new CodecException("MALFORMED_ENVELOPE",
                "ack must be a JSON object");
        }
        Map<String, Object> obj = (Map<String, Object>) parsed;
        validateAckDict(obj);
        return obj;
    }

    @SuppressWarnings("unchecked")
    public static byte[] encodeAck(Map<String, Object> obj) throws CodecException {
        validateAckDict(obj);
        List<Object> seqs = (List<Object>) obj.get("ack_sequences");
        Map<String, Object> seq = (Map<String, Object>) seqs.get(0);
        Map<String, Object> seqOut = new LinkedHashMap<>();
        seqOut.put("instance_id", seq.get("instance_id"));
        seqOut.put("startup_epoch", asLong(seq.get("startup_epoch")));
        seqOut.put("max_contiguous_sequence", asLong(seq.get("max_contiguous_sequence")));
        List<Object> seqsOut = new ArrayList<>();
        seqsOut.add(seqOut);
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("protocol_version", obj.get("protocol_version"));
        out.put("batch_id", obj.get("batch_id"));
        out.put("received_at", obj.get("received_at"));
        out.put("ack_sequences", seqsOut);
        out.put("duplicate_count", asLong(obj.get("duplicate_count")));
        return Json.write(out);
    }

    @SuppressWarnings("unchecked")
    private static void validateErrorDict(Map<String, Object> obj) throws CodecException {
        List<String> missing = new ArrayList<>();
        for (String k : ERROR_REQUIRED_FIELDS) {
            if (!obj.containsKey(k)) missing.add(k);
        }
        if (!missing.isEmpty()) {
            java.util.Collections.sort(missing);
            throw new CodecException("MALFORMED_ENVELOPE",
                "error missing required fields: " + missing);
        }
        List<String> unknown = new ArrayList<>();
        for (String k : obj.keySet()) {
            if (!ERROR_REQUIRED_FIELDS.contains(k)) unknown.add(k);
        }
        if (!unknown.isEmpty()) {
            java.util.Collections.sort(unknown);
            throw new CodecException("MALFORMED_ENVELOPE",
                "error unknown fields not allowed: " + unknown);
        }
        validateProtocolVersion(obj);
        Object ec = obj.get("error_code");
        if (!(ec instanceof String) || !ERROR_CODES.contains(ec)) {
            throw new CodecException("MALFORMED_ENVELOPE",
                "unknown error_code: " + asString(ec));
        }
        Object msg = obj.get("message");
        if (!(msg instanceof String)) {
            throw new CodecException("MALFORMED_ENVELOPE",
                "message must be string");
        }
        if (((String) msg).getBytes(StandardCharsets.UTF_8).length > ERROR_MESSAGE_MAX_LEN) {
            throw new CodecException("MALFORMED_ENVELOPE",
                "message exceeds " + ERROR_MESSAGE_MAX_LEN + " bytes");
        }
        if (!obj.containsKey("details")) {
            throw new CodecException("MALFORMED_ENVELOPE",
                "details must be present (null or object)");
        }
        Object d = obj.get("details");
        if (d != null && !(d instanceof Map)) {
            throw new CodecException("MALFORMED_ENVELOPE",
                "details must be a JSON object or null");
        }
    }

    @SuppressWarnings("unchecked")
    public static Map<String, Object> decodeErrorEnvelope(byte[] raw)
            throws CodecException {
        Object parsed;
        try {
            parsed = Json.parse(raw);
        } catch (CodecException e) {
            throw new CodecException("MALFORMED_ENVELOPE",
                "invalid JSON: " + e.getMessage().replaceFirst("^\\[\\w+\\]\\s*", ""));
        }
        if (!(parsed instanceof Map)) {
            throw new CodecException("MALFORMED_ENVELOPE",
                "error must be a JSON object");
        }
        Map<String, Object> obj = (Map<String, Object>) parsed;
        validateErrorDict(obj);
        return obj;
    }

    @SuppressWarnings("unchecked")
    public static byte[] encodeErrorEnvelope(Map<String, Object> obj)
            throws CodecException {
        validateErrorDict(obj);
        Object d = obj.get("details");
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("protocol_version", obj.get("protocol_version"));
        out.put("error_code", obj.get("error_code"));
        out.put("message", obj.get("message"));
        if (d == null) {
            out.put("details", null);
        } else {
            Map<String, Object> dm = (Map<String, Object>) d;
            Map<String, Object> detailsOut = new LinkedHashMap<>();
            if (dm.containsKey("field")) detailsOut.put("field", dm.get("field"));
            if (dm.containsKey("got_type")) detailsOut.put("got_type", dm.get("got_type"));
            out.put("details", detailsOut);
        }
        return Json.write(out);
    }

    private static long asLong(Object v) {
        if (v instanceof Long) return (Long) v;
        if (v instanceof Integer) return ((Integer) v).longValue();
        throw new IllegalStateException("expected integer, got " +
            (v == null ? "null" : v.getClass().getName()));
    }

    private static int compareInt64(Object a, Object b) {
        long al = asLong(a);
        long bl = asLong(b);
        return Long.compare(al, bl);
    }

    private static String asString(Object v) {
        if (v == null) return "null";
        if (v instanceof String) return (String) v;
        return v.toString();
    }
}

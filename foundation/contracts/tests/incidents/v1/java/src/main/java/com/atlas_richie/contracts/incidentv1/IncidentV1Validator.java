package com.atlas_richie.contracts.incidentv1;

import com.fasterxml.jackson.core.JsonFactory;
import com.fasterxml.jackson.core.StreamReadFeature;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

import java.io.IOException;
import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.time.format.DateTimeParseException;
import java.time.format.ResolverStyle;
import java.util.HashSet;
import java.util.Iterator;
import java.util.Set;

/** Test-only consumer validator for shared Incident Event V1 fixtures. */
public final class IncidentV1Validator {

    private static final String PROTOCOL = "atlas-richie.incident-events/v1";
    private static final String UUID_PATTERN = "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$";
    private static final String DIGEST_PATTERN = "^[0-9a-f]{64}$";
    private static final BigDecimal MAX_SAFE_INTEGER = new BigDecimal("9007199254740991");
    private static final DateTimeFormatter UTC_TIMESTAMP = DateTimeFormatter
        .ofPattern("uuuu-MM-dd'T'HH:mm:ss.SSSSSS'Z'")
        .withResolverStyle(ResolverStyle.STRICT);
    private static final ObjectMapper JSON = new ObjectMapper(JsonFactory.builder()
        .enable(StreamReadFeature.STRICT_DUPLICATE_DETECTION)
        .build())
        .enable(DeserializationFeature.FAIL_ON_TRAILING_TOKENS)
        .enable(DeserializationFeature.USE_BIG_DECIMAL_FOR_FLOATS);

    private IncidentV1Validator() {}

    public static void validateEvent(byte[] payload) {
        require(payload.length > 0 && payload.length <= 16 * 1024, "invalid_payload_size");
        JsonNode root = parse(payload, "invalid_event_json");
        require(root != null && root.isObject(), "invalid_event_object");
        exactFields(root, Set.of("protocol_version", "event_id", "process_epoch", "occurred_at", "severity", "fact"));
        require(PROTOCOL.equals(text(root, "protocol_version")), "unsupported_protocol");
        require(uuid(text(root, "event_id")) && uuid(text(root, "process_epoch")), "invalid_event_identity");
        timestamp(text(root, "occurred_at"));
        require(oneOf(text(root, "severity"), "critical", "warning", "info"), "invalid_severity");

        JsonNode fact = root.get("fact");
        require(fact != null && fact.isObject(), "invalid_fact");
        String kind = text(fact, "kind");
        if ("resource_pressure".equals(kind)) {
            exactFields(fact, Set.of("kind", "metric", "value", "threshold"));
            require(oneOf(text(fact, "metric"), "cpu_ratio", "memory_ratio"), "invalid_metric");
            BigDecimal value = ratio(fact.get("value"));
            BigDecimal threshold = ratio(fact.get("threshold"));
            exceedsAfterProjection(value, threshold);
        } else if ("response_time".equals(kind)) {
            exactFields(fact, Set.of("kind", "p95_ms", "threshold_ms"));
            BigDecimal value = nonnegative(fact.get("p95_ms"));
            BigDecimal threshold = nonnegative(fact.get("threshold_ms"));
            exceedsAfterProjection(value, threshold);
        } else {
            fail("unsupported_fact_kind");
        }
    }

    public static void validateReceipt(byte[] payload) {
        require(payload.length > 0 && payload.length <= 16 * 1024, "invalid_receipt_size");
        JsonNode root = parse(payload, "invalid_receipt_json");
        require(root != null && root.isObject(), "invalid_receipt_object");
        exactFields(root, Set.of("protocol_version", "event_id", "body_sha256", "received_at"));
        require(PROTOCOL.equals(text(root, "protocol_version")), "unsupported_receipt_protocol");
        require(uuid(text(root, "event_id")), "invalid_receipt_event_id");
        require(text(root, "body_sha256").matches(DIGEST_PATTERN), "invalid_receipt_digest");
        timestamp(text(root, "received_at"));
    }

    private static JsonNode parse(byte[] payload, String message) {
        try {
            return JSON.readTree(payload);
        } catch (IOException | RuntimeException exception) {
            throw new IllegalArgumentException(message, exception);
        }
    }

    private static void exactFields(JsonNode object, Set<String> required) {
        Set<String> supplied = new HashSet<>();
        Iterator<String> names = object.fieldNames();
        while (names.hasNext()) supplied.add(names.next());
        require(supplied.equals(required), "invalid_fields");
    }

    private static String text(JsonNode object, String field) {
        JsonNode value = object.get(field);
        require(value != null && value.isTextual(), "invalid_" + field);
        return value.textValue();
    }

    private static boolean uuid(String value) {
        return value.matches(UUID_PATTERN);
    }

    private static void timestamp(String value) {
        require(value.matches("^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\\.[0-9]{6}Z$"), "invalid_timestamp");
        try {
            LocalDateTime.parse(value, UTC_TIMESTAMP);
        } catch (DateTimeParseException exception) {
            throw new IllegalArgumentException("invalid_timestamp", exception);
        }
    }

    private static boolean oneOf(String value, String... allowed) {
        for (String candidate : allowed) if (candidate.equals(value)) return true;
        return false;
    }

    private static BigDecimal ratio(JsonNode value) {
        BigDecimal number = numeric(value);
        require(number.signum() >= 0 && number.compareTo(BigDecimal.ONE) <= 0, "invalid_ratio");
        return number;
    }

    private static BigDecimal nonnegative(JsonNode value) {
        BigDecimal number = numeric(value);
        require(number.signum() >= 0, "invalid_nonnegative_number");
        return number;
    }

    private static void exceedsAfterProjection(BigDecimal value, BigDecimal threshold) {
        require(value.compareTo(threshold) > 0, "threshold_not_breached");
        require(value.doubleValue() > threshold.doubleValue(), "threshold_breach_lost_after_projection");
    }

    private static BigDecimal numeric(JsonNode value) {
        require(value != null && value.isNumber(), "invalid_number");
        BigDecimal number = value.decimalValue();
        require(number.compareTo(MAX_SAFE_INTEGER) <= 0, "unsafe_number");
        return number;
    }

    private static void require(boolean condition, String message) {
        if (!condition) fail(message);
    }

    private static void fail(String message) {
        throw new IllegalArgumentException(message);
    }
}

package com.atlas_richie.contracts.metricsv2;

import com.fasterxml.jackson.core.StreamReadFeature;
import com.fasterxml.jackson.core.JsonFactory;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

import java.io.IOException;
import java.math.BigDecimal;
import java.math.BigInteger;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.time.format.DateTimeParseException;
import java.time.format.ResolverStyle;
import java.util.HashSet;
import java.util.Iterator;
import java.util.Set;

/** Conformance validator used by the Metrics V2 shared contract fixtures. */
public final class MetricsV2Validator {

    private static final String PROTOCOL = "atlas-richie.metrics/v2";
    private static final String UUID_PATTERN = "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$";
    private static final BigInteger MAX_SAFE_INTEGER = new BigInteger("9007199254740991");
    private static final BigInteger[] HTTP_DURATION_BOUNDARIES_NS = {
        BigInteger.valueOf(1_000_000L), BigInteger.valueOf(5_000_000L),
        BigInteger.valueOf(10_000_000L), BigInteger.valueOf(25_000_000L),
        BigInteger.valueOf(50_000_000L), BigInteger.valueOf(100_000_000L),
        BigInteger.valueOf(250_000_000L), BigInteger.valueOf(500_000_000L),
        BigInteger.valueOf(1_000_000_000L), BigInteger.valueOf(2_000_000_000L),
        BigInteger.valueOf(5_000_000_000L), BigInteger.valueOf(10_000_000_000L)
    };
    private static final int MAX_DECIMAL_INTEGER_DIGITS = 38;
    private static final int MAX_PAYLOAD_BYTES = 64 * 1024;
    private static final int MAX_RECORDS = 256;
    private static final DateTimeFormatter UTC_TIMESTAMP = DateTimeFormatter
        .ofPattern("uuuu-MM-dd'T'HH:mm:ss.SSSSSS'Z'")
        .withResolverStyle(ResolverStyle.STRICT);
    private static final ObjectMapper JSON = new ObjectMapper(JsonFactory.builder()
        .enable(StreamReadFeature.STRICT_DUPLICATE_DETECTION)
        .build()).enable(DeserializationFeature.FAIL_ON_TRAILING_TOKENS);

    private MetricsV2Validator() {}

    /** Validate one frozen V2 snapshot, throwing on rejection. */
    public static void validate(byte[] payload) {
        if (payload.length > MAX_PAYLOAD_BYTES) {
            fail("payload_too_large");
        }
        final JsonNode root;
        try {
            root = JSON.readTree(payload);
        } catch (IOException | RuntimeException exception) {
            throw new IllegalArgumentException("invalid_json", exception);
        }
        require(root != null && root.isObject(), "invalid_snapshot_object");
        exactFields(root, Set.of("protocol_version", "reporter_id", "startup_epoch", "sequence",
            "captured_at", "capture_elapsed_ns", "counters", "histograms", "gauges"));
        require(PROTOCOL.equals(text(root, "protocol_version")), "unsupported_protocol");
        require(identifier(root.get("reporter_id")), "invalid_reporter_id");
        require(text(root, "startup_epoch").matches(UUID_PATTERN), "invalid_startup_epoch");
        positiveInteger(root.get("sequence"), "invalid_sequence");
        timestamp(text(root, "captured_at"));
        decimalInteger(root.get("capture_elapsed_ns"), "invalid_capture_elapsed_ns");

        JsonNode counters = array(root.get("counters"), "invalid_counters");
        JsonNode histograms = array(root.get("histograms"), "invalid_histograms");
        JsonNode gauges = array(root.get("gauges"), "invalid_gauges");
        require(counters.size() + histograms.size() + gauges.size() <= MAX_RECORDS, "too_many_records");
        validateCounters(counters);
        validateHistograms(histograms);
        validateGauges(gauges);
    }

    /** Validate one durable Metrics V2 ACK fixture. */
    public static void validateReceipt(byte[] payload) {
        require(payload.length <= MAX_PAYLOAD_BYTES, "receipt_too_large");
        final JsonNode root;
        try {
            root = JSON.readTree(payload);
        } catch (IOException | RuntimeException exception) {
            throw new IllegalArgumentException("invalid_receipt_json", exception);
        }
        require(root != null && root.isObject(), "invalid_receipt_object");
        exactFields(root, Set.of("protocol_version", "reporter_id", "startup_epoch",
            "sequence", "body_sha256", "received_at"));
        require(PROTOCOL.equals(text(root, "protocol_version")), "unsupported_receipt_protocol");
        require(identifier(root.get("reporter_id")), "invalid_reporter_id");
        require(text(root, "startup_epoch").matches(UUID_PATTERN), "invalid_startup_epoch");
        positiveInteger(root.get("sequence"), "invalid_sequence");
        require(text(root, "body_sha256").matches("^[0-9a-f]{64}$"), "invalid_body_sha256");
        timestamp(text(root, "received_at"));
    }

    private static void validateCounters(JsonNode counters) {
        Set<String> identities = new HashSet<>();
        for (JsonNode counter : counters) {
            require(counter.isObject(), "invalid_counter");
            exactFields(counter, Set.of("name", "value"), Set.of("resource"));
            String name = text(counter, "name");
            require(oneOf(name, "http_requests_completed_total", "sentinel_entries_admitted_total",
                "sentinel_entries_blocked_total", "business_transactions_completed_total"), "invalid_counter_name");
            nonnegativeInteger(counter.get("value"), "invalid_counter_value");
            String resource = "";
            if (counter.has("resource")) {
                require(identifier(counter.get("resource")), "invalid_resource");
                resource = counter.get("resource").textValue();
            }
            require(identities.add(name + "\u0000" + resource), "duplicate_counter");
        }
    }

    private static void validateHistograms(JsonNode histograms) {
        Set<String> identities = new HashSet<>();
        for (JsonNode histogram : histograms) {
            require(histogram.isObject(), "invalid_histogram");
            exactFields(histogram, Set.of("name", "boundaries_ns", "bucket_counts", "sample_count",
                "total_ns", "min_ns", "max_ns"), Set.of("resource"));
            require("http_request_duration".equals(text(histogram, "name")), "invalid_histogram_name");
            JsonNode boundaries = array(histogram.get("boundaries_ns"), "invalid_histogram_boundaries");
            JsonNode buckets = array(histogram.get("bucket_counts"), "invalid_histogram_buckets");
            require(boundaries.size() == HTTP_DURATION_BOUNDARIES_NS.length && buckets.size() == boundaries.size() + 1,
                "invalid_histogram_shape");
            BigInteger previous = BigInteger.ZERO;
            for (int index = 0; index < boundaries.size(); index++) {
                JsonNode boundary = boundaries.get(index);
                BigInteger current = positiveInteger(boundary, "invalid_histogram_boundary");
                require(current.equals(HTTP_DURATION_BOUNDARIES_NS[index]), "invalid_histogram_profile");
                require(current.compareTo(previous) > 0, "unordered_histogram_boundaries");
                previous = current;
            }
            BigInteger bucketTotal = BigInteger.ZERO;
            for (JsonNode bucket : buckets) {
                bucketTotal = bucketTotal.add(nonnegativeInteger(bucket, "invalid_histogram_bucket_count"));
            }
            BigInteger sampleCount = nonnegativeInteger(histogram.get("sample_count"), "invalid_sample_count");
            BigInteger total = decimalInteger(histogram.get("total_ns"), "invalid_histogram_total");
            JsonNode minNode = histogram.get("min_ns");
            JsonNode maxNode = histogram.get("max_ns");
            require(bucketTotal.equals(sampleCount), "histogram_count_mismatch");
            if (sampleCount.signum() == 0) {
                require(total.signum() == 0 && minNode.isNull() && maxNode.isNull(), "invalid_empty_histogram");
            } else {
                BigInteger minimum = nonnegativeInteger(minNode, "invalid_histogram_minimum");
                BigInteger maximum = nonnegativeInteger(maxNode, "invalid_histogram_maximum");
                require(minimum.compareTo(maximum) <= 0
                    && total.compareTo(minimum.multiply(sampleCount)) >= 0
                    && total.compareTo(maximum.multiply(sampleCount)) <= 0, "invalid_histogram_statistics");
            }
            String resource = "";
            if (histogram.has("resource")) {
                require(identifier(histogram.get("resource")), "invalid_resource");
                resource = histogram.get("resource").textValue();
            }
            require(identities.add(text(histogram, "name") + "\u0000" + resource), "duplicate_histogram");
        }
    }

    private static void validateGauges(JsonNode gauges) {
        Set<String> identities = new HashSet<>();
        for (JsonNode gauge : gauges) {
            require(gauge.isObject(), "invalid_gauge");
            exactFields(gauge, Set.of("name", "value", "quality"));
            String name = text(gauge, "name");
            require(oneOf(name, "process_cpu_ratio", "process_rss_bytes", "process_memory_ratio",
                "event_loop_lag_ns"), "invalid_gauge_name");
            String quality = text(gauge, "quality");
            require(oneOf(quality, "available", "unavailable"), "invalid_gauge_quality");
            JsonNode value = gauge.get("value");
            if ("unavailable".equals(quality)) {
                require(value.isNull(), "unavailable_gauge_has_value");
            } else {
                require(value.isNumber() && value.decimalValue().signum() >= 0
                    && value.decimalValue().compareTo(new BigDecimal(MAX_SAFE_INTEGER)) <= 0,
                    "invalid_gauge_value");
            }
            require(identities.add(name), "duplicate_gauge");
        }
    }

    private static JsonNode array(JsonNode value, String code) {
        require(value != null && value.isArray(), code);
        return value;
    }

    private static BigInteger positiveInteger(JsonNode value, String code) {
        BigInteger number = nonnegativeInteger(value, code);
        require(number.signum() > 0, code);
        return number;
    }

    private static BigInteger nonnegativeInteger(JsonNode value, String code) {
        require(value != null && value.isIntegralNumber(), code);
        BigInteger number = value.bigIntegerValue();
        require(number.signum() >= 0 && number.compareTo(MAX_SAFE_INTEGER) <= 0, code);
        return number;
    }

    private static BigInteger decimalInteger(JsonNode value, String code) {
        require(value != null && value.isTextual(), code);
        String text = value.textValue();
        require(text.matches("^(0|[1-9][0-9]{0," + (MAX_DECIMAL_INTEGER_DIGITS - 1) + "})$"), code);
        return new BigInteger(text);
    }

    private static boolean identifier(JsonNode value) {
        if (value == null || !value.isTextual()) return false;
        String text = value.textValue();
        if (text.isBlank() || !text.equals(text.strip()) || text.codePointCount(0, text.length()) > 200) return false;
        for (int index = 0; index < text.length(); index++) {
            char character = text.charAt(index);
            if (Character.isHighSurrogate(character)) {
                if (index + 1 >= text.length() || !Character.isLowSurrogate(text.charAt(index + 1))) return false;
                index++;
            } else if (Character.isLowSurrogate(character) || character == '\r' || character == '\n') {
                return false;
            }
        }
        return true;
    }

    private static String text(JsonNode object, String field) {
        JsonNode value = object.get(field);
        require(value != null && value.isTextual(), "invalid_" + field);
        return value.textValue();
    }

    private static void timestamp(String value) {
        require(value.matches("^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\\.[0-9]{6}Z$"),
            "invalid_captured_at");
        try {
            LocalDateTime.parse(value, UTC_TIMESTAMP);
        } catch (DateTimeParseException exception) {
            throw new IllegalArgumentException("invalid_captured_at", exception);
        }
    }

    private static void exactFields(JsonNode object, Set<String> required) {
        exactFields(object, required, Set.of());
    }

    private static void exactFields(JsonNode object, Set<String> required, Set<String> optional) {
        Set<String> allowed = new HashSet<>(required);
        allowed.addAll(optional);
        Set<String> actual = new HashSet<>();
        Iterator<String> names = object.fieldNames();
        while (names.hasNext()) actual.add(names.next());
        require(actual.containsAll(required) && allowed.containsAll(actual), "invalid_fields");
    }

    private static boolean oneOf(String value, String... candidates) {
        for (String candidate : candidates) if (candidate.equals(value)) return true;
        return false;
    }

    private static void require(boolean condition, String code) {
        if (!condition) fail(code);
    }

    private static void fail(String code) {
        throw new IllegalArgumentException(code);
    }
}

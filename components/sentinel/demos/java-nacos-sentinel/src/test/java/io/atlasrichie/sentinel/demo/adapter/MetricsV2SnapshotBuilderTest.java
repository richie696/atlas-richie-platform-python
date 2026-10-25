package io.atlasrichie.sentinel.demo.adapter;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Map;
import java.util.regex.Pattern;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assertions.assertNull;

final class MetricsV2SnapshotBuilderTest {
    private static final ObjectMapper JSON = new ObjectMapper();
    private static final Pattern UTC_MICROS = Pattern.compile(
            "^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\\.[0-9]{6}Z$");

    @Test
    void emitsFrozenProtocolAndCumulativeHttpBoundaryFacts() throws Exception {
        MetricsV2SnapshotBuilder builder = new MetricsV2SnapshotBuilder("java-worker-1");
        builder.recordHttpResponse(true, true, false, true, 5_000_000L);
        builder.recordHttpResponse(true, false, true, false, 250_000_000L);

        Map<String, Object> snapshot = builder.nextSnapshot();
        Map<?, ?> decoded = JSON.readValue(builder.encode(snapshot), Map.class);

        assertEquals("atlas-richie.metrics/v2", decoded.get("protocol_version"));
        assertEquals("java-worker-1", decoded.get("reporter_id"));
        assertTrue(UTC_MICROS.matcher((String) decoded.get("captured_at")).matches());
        assertEquals(1, decoded.get("sequence"));
        assertTrue(((String) decoded.get("capture_elapsed_ns")).matches("^(0|[1-9][0-9]*)$"));
        List<?> counters = (List<?>) decoded.get("counters");
        assertEquals(2, counter(counters, "http_requests_completed_total"));
        assertEquals(1, counter(counters, "sentinel_entries_admitted_total"));
        assertEquals(1, counter(counters, "sentinel_entries_blocked_total"));
        assertEquals(1, counter(counters, "business_transactions_completed_total"));

        List<?> histograms = (List<?>) decoded.get("histograms");
        Map<?, ?> histogram = (Map<?, ?>) histograms.get(0);
        assertEquals(13, ((List<?>) histogram.get("bucket_counts")).size());
        assertEquals(2, histogram.get("sample_count"));
        assertEquals("255000000", histogram.get("total_ns"));
        assertEquals(List.of(0, 1, 0, 0, 0, 0),
                ((List<?>) histogram.get("bucket_counts")).subList(0, 6));

        List<?> gauges = (List<?>) decoded.get("gauges");
        assertNull(gauge(gauges, "process_memory_ratio").get("value"));
        assertEquals("unavailable", gauge(gauges, "process_rss_bytes").get("quality"));
    }

    @Test
    void emitsEmptyHistogramAndAdvancesOnlyOnCreatedSnapshot() {
        MetricsV2SnapshotBuilder builder = new MetricsV2SnapshotBuilder("java-worker-1");
        Map<String, Object> first = builder.nextSnapshot();
        Map<String, Object> second = builder.nextSnapshot();

        assertEquals(1L, first.get("sequence"));
        assertEquals(2L, second.get("sequence"));
        Map<?, ?> histogram = (Map<?, ?>) ((List<?>) first.get("histograms")).get(0);
        assertEquals("http_request_duration", histogram.get("name"));
        assertEquals(13, ((List<?>) histogram.get("bucket_counts")).size());
        assertTrue(((List<?>) histogram.get("bucket_counts")).stream()
                .allMatch(value -> ((Number) value).longValue() == 0));
        assertEquals(0L, histogram.get("sample_count"));
        assertEquals("0", histogram.get("total_ns"));
        assertNull(histogram.get("min_ns"));
        assertNull(histogram.get("max_ns"));
    }

    @Test
    void countsOnlyCompletedHttpResponsesButPreservesSentinelEntryOutcomes() {
        MetricsV2SnapshotBuilder builder = new MetricsV2SnapshotBuilder("java-worker-1");
        builder.recordHttpResponse(false, true, false, true, 20_000_000L);

        Map<String, Object> snapshot = builder.nextSnapshot();
        List<?> counters = (List<?>) snapshot.get("counters");
        assertEquals(0L, counter(counters, "http_requests_completed_total"));
        assertEquals(1L, counter(counters, "sentinel_entries_admitted_total"));
        Map<?, ?> histogram = (Map<?, ?>) ((List<?>) snapshot.get("histograms")).get(0);
        assertEquals(0L, histogram.get("sample_count"));
        assertTrue(((List<?>) histogram.get("bucket_counts")).stream()
                .allMatch(value -> ((Number) value).longValue() == 0));
    }

    private static long counter(List<?> counters, String name) {
        return counters.stream()
                .map(Map.class::cast)
                .filter(value -> name.equals(value.get("name")))
                .map(value -> ((Number) value.get("value")).longValue())
                .findFirst()
                .orElseThrow();
    }

    private static Map<?, ?> gauge(List<?> gauges, String name) {
        return gauges.stream()
                .map(Map.class::cast)
                .filter(value -> name.equals(value.get("name")))
                .findFirst()
                .orElseThrow();
    }
}

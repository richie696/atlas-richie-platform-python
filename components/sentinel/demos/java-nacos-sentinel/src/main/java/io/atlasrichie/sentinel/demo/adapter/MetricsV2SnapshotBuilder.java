package io.atlasrichie.sentinel.demo.adapter;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;

import java.lang.management.ManagementFactory;
import java.time.Instant;
import java.time.ZoneOffset;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicLong;
import java.util.concurrent.atomic.LongAdder;

/** Builds bounded cumulative Metrics V2 snapshots for the demo HTTP boundary. */
public final class MetricsV2SnapshotBuilder {
    private static final ObjectMapper JSON = new ObjectMapper();
    private static final long MAX_SAFE_INTEGER = 9_007_199_254_740_991L;
    private static final DateTimeFormatter UTC_MICROS = new java.time.format.DateTimeFormatterBuilder()
            .appendPattern("uuuu-MM-dd'T'HH:mm:ss")
            .appendFraction(java.time.temporal.ChronoField.NANO_OF_SECOND, 6, 6, true)
            .appendLiteral('Z')
            .toFormatter()
            .withZone(ZoneOffset.UTC);
    private static final long[] BOUNDARIES_NS = {
            1_000_000L, 5_000_000L, 10_000_000L, 25_000_000L,
            50_000_000L, 100_000_000L, 250_000_000L, 500_000_000L,
            1_000_000_000L, 2_000_000_000L, 5_000_000_000L, 10_000_000_000L
    };
    private final String reporterId;
    private final String startupEpoch = UUID.randomUUID().toString();
    private final long epochStartedAt = System.nanoTime();
    private final AtomicLong sequence = new AtomicLong();
    private final LongAdder completed = new LongAdder();
    private final LongAdder admitted = new LongAdder();
    private final LongAdder blocked = new LongAdder();
    private final LongAdder businessCompleted = new LongAdder();
    private final LongAdder[] buckets = new LongAdder[BOUNDARIES_NS.length + 1];
    private final LongAdder sampleCount = new LongAdder();
    private final LongAdder totalNanos = new LongAdder();
    private final AtomicLong minNanos = new AtomicLong(Long.MAX_VALUE);
    private final AtomicLong maxNanos = new AtomicLong();

    public MetricsV2SnapshotBuilder(String reporterId) {
        if (reporterId == null || reporterId.isBlank() || reporterId.length() > 200) {
            throw new IllegalArgumentException("reporter ID is invalid");
        }
        this.reporterId = reporterId;
        for (int index = 0; index < buckets.length; index++) buckets[index] = new LongAdder();
    }

    String reporterId() {
        return reporterId;
    }

    /** Return the runtime epoch shared by Metrics and rule-load reporting. */
    public String startupEpoch() {
        return startupEpoch;
    }

    /** Record one completed business HTTP response, including rejected responses. */
    public void recordHttpResponse(
            boolean completedHttpResponse,
            boolean sentinelAdmitted,
            boolean sentinelBlocked,
            boolean businessTransactionCompleted,
            long elapsedNanos
    ) {
        if (elapsedNanos < 0) throw new IllegalArgumentException("HTTP duration is invalid");
        if (sentinelAdmitted) admitted.increment();
        if (sentinelBlocked) blocked.increment();
        if (!completedHttpResponse) return;
        completed.increment();
        if (businessTransactionCompleted) businessCompleted.increment();
        int bucket = 0;
        while (bucket < BOUNDARIES_NS.length && elapsedNanos > BOUNDARIES_NS[bucket]) bucket++;
        buckets[bucket].increment();
        sampleCount.increment();
        totalNanos.add(elapsedNanos);
        minNanos.accumulateAndGet(elapsedNanos, Math::min);
        maxNanos.accumulateAndGet(elapsedNanos, Math::max);
    }

    /** Create the next cumulative snapshot. Each call advances sequence exactly once. */
    public Map<String, Object> nextSnapshot() {
        long nextSequence = sequence.incrementAndGet();
        if (nextSequence > MAX_SAFE_INTEGER) throw new IllegalStateException("metrics sequence exhausted");
        long elapsed = System.nanoTime() - epochStartedAt;
        Map<String, Object> snapshot = new LinkedHashMap<>();
        snapshot.put("protocol_version", "atlas-richie.metrics/v2");
        snapshot.put("reporter_id", reporterId);
        snapshot.put("startup_epoch", startupEpoch);
        snapshot.put("sequence", nextSequence);
        snapshot.put("captured_at", UTC_MICROS.format(Instant.now()));
        snapshot.put("capture_elapsed_ns", Long.toString(elapsed));
        snapshot.put("counters", counters());
        snapshot.put("histograms", histograms());
        snapshot.put("gauges", gauges());
        return Map.copyOf(snapshot);
    }

    public byte[] encode(Map<String, Object> snapshot) {
        try {
            return JSON.writeValueAsBytes(snapshot);
        } catch (JsonProcessingException error) {
            throw new IllegalStateException("Metrics V2 snapshot encoding failed", error);
        }
    }

    private List<Map<String, Object>> counters() {
        return List.of(
                counter("http_requests_completed_total", completed.sum()),
                counter("sentinel_entries_admitted_total", admitted.sum()),
                counter("sentinel_entries_blocked_total", blocked.sum()),
                counter("business_transactions_completed_total", businessCompleted.sum())
        );
    }

    private List<Map<String, Object>> histograms() {
        long count = sampleCount.sum();
        List<Long> counts = new ArrayList<>(buckets.length);
        for (LongAdder bucket : buckets) counts.add(bucket.sum());
        Map<String, Object> histogram = new LinkedHashMap<>();
        histogram.put("name", "http_request_duration");
        List<Long> boundaries = new ArrayList<>(BOUNDARIES_NS.length);
        for (long boundary : BOUNDARIES_NS) boundaries.add(boundary);
        histogram.put("boundaries_ns", boundaries);
        histogram.put("bucket_counts", counts);
        histogram.put("sample_count", count);
        histogram.put("total_ns", Long.toString(totalNanos.sum()));
        histogram.put("min_ns", count == 0 ? null : minNanos.get());
        histogram.put("max_ns", count == 0 ? null : maxNanos.get());
        return List.of(histogram);
    }

    private List<Map<String, Object>> gauges() {
        double cpuLoad = Double.NaN;
        var operatingSystem = ManagementFactory.getOperatingSystemMXBean();
        if (operatingSystem instanceof com.sun.management.OperatingSystemMXBean extended) {
            cpuLoad = extended.getProcessCpuLoad();
        }
        List<Map<String, Object>> result = new ArrayList<>();
        boolean cpuAvailable = Double.isFinite(cpuLoad) && cpuLoad >= 0 && cpuLoad <= 1;
        result.add(gauge("process_cpu_ratio", cpuAvailable ? cpuLoad : null,
                cpuAvailable ? "available" : "unavailable"));
        // Heap occupancy is not process RSS; do not mislabel it as process memory.
        result.add(gauge("process_memory_ratio", null, "unavailable"));
        result.add(gauge("process_rss_bytes", null, "unavailable"));
        return List.copyOf(result);
    }

    private static Map<String, Object> counter(String name, long value) {
        if (value < 0 || value > MAX_SAFE_INTEGER) throw new IllegalStateException("metrics counter exhausted");
        return Map.of("name", name, "value", value);
    }

    private static Map<String, Object> gauge(String name, Object value, String quality) {
        Map<String, Object> gauge = new LinkedHashMap<>();
        gauge.put("name", name);
        gauge.put("value", value);
        gauge.put("quality", quality);
        return gauge;
    }
}

package io.atlasrichie.sentinel.demo.adapter;

import com.fasterxml.jackson.core.JsonParser;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.atlasrichie.sentinel.demo.adapter.SentinelFlowRuleAdapter.AppliedSnapshot;

import javax.net.ssl.SSLContext;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneOffset;
import java.time.format.DateTimeFormatter;
import java.time.temporal.ChronoUnit;
import java.util.Map;
import java.util.LinkedHashMap;
import java.util.UUID;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;

/** Bounded in-memory exact-body reporter for managed publication apply facts. */
public final class RulePublicationReceiptV1Reporter implements AutoCloseable {
    private static final String PROTOCOL = "atlas-richie.sentinel.rule-publication-receipt/v1";
    private static final int QUEUE_CAPACITY = 128;
    private static final DateTimeFormatter UTC_MILLIS = DateTimeFormatter
            .ofPattern("uuuu-MM-dd'T'HH:mm:ss.SSS'Z'").withZone(ZoneOffset.UTC);
    private static final ObjectMapper JSON = new ObjectMapper()
            .enable(JsonParser.Feature.STRICT_DUPLICATE_DETECTION);

    private final String processEpoch;
    private final URI endpoint;
    private final ReceiptTransport transport;
    private final ArrayBlockingQueue<byte[]> queue = new ArrayBlockingQueue<>(QUEUE_CAPACITY);
    private final AtomicReference<byte[]> inFlight = new AtomicReference<>();
    private long sequence;
    private final ScheduledExecutorService scheduler = Executors.newSingleThreadScheduledExecutor(runnable -> {
        Thread thread = new Thread(runnable, "sentinel-rule-publication-receipt-v1");
        thread.setDaemon(true);
        return thread;
    });

    public RulePublicationReceiptV1Reporter(String processEpoch, URI collectorBaseUri, SSLContext tls) {
        this(processEpoch, collectorBaseUri, createTransport(tls));
    }

    RulePublicationReceiptV1Reporter(
            String processEpoch, URI collectorBaseUri, ReceiptTransport transport) {
        UUID.fromString(processEpoch);
        if (!"https".equalsIgnoreCase(collectorBaseUri.getScheme()) || collectorBaseUri.getUserInfo() != null
                || collectorBaseUri.getQuery() != null || collectorBaseUri.getFragment() != null) {
            throw new IllegalArgumentException("Rule Receipt Collector URL must be a plain HTTPS origin");
        }
        this.processEpoch = processEpoch;
        this.endpoint = collectorBaseUri.resolve("/api/reporting/v1/rule-publication-receipts");
        this.transport = java.util.Objects.requireNonNull(transport, "receipt transport is required");
    }

    /** Start background bounded delivery; queued reports retry exact bytes until durable ACK. */
    public void start() {
        scheduler.scheduleWithFixedDelay(this::sendNext, 0, 1, TimeUnit.SECONDS);
    }

    /** Enqueue only after the official SDK accepted the exact managed target. Never waits for I/O. */
    public synchronized boolean applied(AppliedSnapshot snapshot) {
        if (snapshot == null || snapshot.managedPublication() == null) return true;
        long next = ++sequence;
        if (next > 9_007_199_254_740_991L) throw new IllegalStateException("receipt sequence exhausted");
        var target = snapshot.managedPublication();
        try {
            Map<String, Object> record = new LinkedHashMap<>();
            record.put("protocol_version", PROTOCOL);
            record.put("receipt_id", UUID.randomUUID().toString());
            record.put("process_epoch", processEpoch);
            record.put("sequence", next);
            record.put("binding_id", target.bindingId());
            record.put("publication_id", target.publicationId());
            record.put("target_version_id", target.targetVersionId());
            record.put("target_payload_sha256", target.payloadSha256());
            record.put("state", "applied");
            record.put("reason", null);
            record.put("source_revision", null);
            record.put("observed_at", UTC_MILLIS.format(Instant.now().truncatedTo(ChronoUnit.MILLIS)));
            return queue.offer(JSON.writeValueAsBytes(record));
        } catch (Exception failure) {
            System.err.println("Rule Publication Receipt could not be queued");
            return false;
        }
    }

    @Override
    public void close() {
        scheduler.shutdownNow();
    }

    void sendNext() {
        try {
            byte[] body = inFlight.get();
            if (body == null) {
                body = queue.peek();
                if (body == null || !inFlight.compareAndSet(null, body)) return;
                body = inFlight.get();
            }
            if (transport.post(endpoint, body) == 204 && queue.remove(body)) inFlight.compareAndSet(body, null);
        } catch (InterruptedException interrupted) {
            Thread.currentThread().interrupt();
        } catch (Exception failure) {
            System.err.println("Rule Publication Receipt Collector unavailable; exact receipt retained for retry");
        }
    }

    private static ReceiptTransport createTransport(SSLContext tls) {
        HttpClient client = HttpClient.newBuilder().sslContext(tls).connectTimeout(Duration.ofSeconds(3))
                .followRedirects(HttpClient.Redirect.NEVER).build();
        return (endpoint, body) -> {
            HttpRequest request = HttpRequest.newBuilder(endpoint).timeout(Duration.ofSeconds(5))
                    .header("Content-Type", "application/json")
                    .POST(HttpRequest.BodyPublishers.ofByteArray(body)).build();
            HttpResponse<Void> response = client.send(request, HttpResponse.BodyHandlers.discarding());
            return response.statusCode();
        };
    }

    @FunctionalInterface
    interface ReceiptTransport {
        int post(URI endpoint, byte[] body) throws Exception;
    }
}

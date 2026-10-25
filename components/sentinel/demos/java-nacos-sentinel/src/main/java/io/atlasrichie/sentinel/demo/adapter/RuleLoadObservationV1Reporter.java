package io.atlasrichie.sentinel.demo.adapter;

import com.fasterxml.jackson.core.JsonParser;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.atlasrichie.sentinel.demo.adapter.SentinelFlowRuleAdapter.AppliedSnapshot;

import javax.net.ssl.SSLContext;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneOffset;
import java.time.format.DateTimeFormatter;
import java.time.temporal.ChronoUnit;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;

/** Bounded mTLS sender for runtime-applied rule snapshot observations. */
public final class RuleLoadObservationV1Reporter implements AutoCloseable {
    private static final String PROTOCOL = "atlas-richie.sentinel.rule-load-observation/v1";
    private static final DateTimeFormatter UTC_MILLIS = DateTimeFormatter
            .ofPattern("uuuu-MM-dd'T'HH:mm:ss.SSS'Z'").withZone(ZoneOffset.UTC);
    private static final ObjectMapper JSON = new ObjectMapper()
            .enable(JsonParser.Feature.STRICT_DUPLICATE_DETECTION);

    private final String processEpoch;
    private final String bindingId;
    private final String profileId;
    private final HttpClient client;
    private final URI negotiationEndpoint;
    private final URI observationEndpoint;
    private final ScheduledExecutorService scheduler = Executors.newSingleThreadScheduledExecutor(runnable -> {
        Thread thread = new Thread(runnable, "sentinel-rule-load-observation-v1");
        thread.setDaemon(true);
        return thread;
    });
    private final AtomicReference<AppliedSnapshot> latest = new AtomicReference<>();
    private final AtomicReference<Attempt> latestFailure = new AtomicReference<>();
    private final AtomicReference<Pending> pending = new AtomicReference<>();
    private volatile boolean compatible;
    private volatile long sequence;
    private volatile boolean eventPending;

    public RuleLoadObservationV1Reporter(String processEpoch, String bindingId, String profileId,
                                          URI collectorBaseUri, SSLContext tls) {
        if (processEpoch == null || bindingId == null
                || !bindingId.matches("[A-Za-z0-9][A-Za-z0-9._:-]{0,199}")
                || profileId == null || !profileId.matches("[A-Za-z0-9][A-Za-z0-9._:-]{0,199}")) {
            throw new IllegalArgumentException("rule observation identity is invalid");
        }
        UUID.fromString(processEpoch);
        if (!"https".equalsIgnoreCase(collectorBaseUri.getScheme())
                || collectorBaseUri.getUserInfo() != null || collectorBaseUri.getQuery() != null
                || collectorBaseUri.getFragment() != null) {
            throw new IllegalArgumentException("Rule Observation Collector URL must be a plain HTTPS origin");
        }
        this.processEpoch = processEpoch;
        this.bindingId = bindingId;
        this.profileId = profileId;
        this.negotiationEndpoint = collectorBaseUri.resolve(
                "/api/reporting/v1/protocol-negotiations/rule-load-observation");
        this.observationEndpoint = collectorBaseUri.resolve("/api/reporting/v1/rule-load-observations");
        this.client = HttpClient.newBuilder().sslContext(tls).connectTimeout(Duration.ofSeconds(3))
                .followRedirects(HttpClient.Redirect.NEVER).build();
    }

    /** Start protocol negotiation and an independent 30-second heartbeat loop. */
    public void start(AppliedSnapshot initial) {
        latest.set(initial);
        eventPending = initial != null;
        scheduler.scheduleWithFixedDelay(this::sendNext, 0, 30, TimeUnit.SECONDS);
    }

    /** Call only after the official SDK has applied the whole candidate snapshot. */
    public void applied(AppliedSnapshot snapshot) {
        latest.set(snapshot);
        latestFailure.set(null);
        eventPending = true;
    }

    /** Record only stable failure classes; exception text and rule data are excluded. */
    public void failed(String failureReason) {
        if (!List.of("source_unavailable", "decode_rejected", "profile_unsupported",
                "validation_rejected", "apply_failed").contains(failureReason)) {
            throw new IllegalArgumentException("rule observation failure reason is invalid");
        }
        latestFailure.set(new Attempt(failureReason));
        eventPending = true;
    }

    @Override
    public void close() {
        scheduler.shutdownNow();
    }

    private void sendNext() {
        try {
            if (!compatible && !negotiate()) return;
            Pending current = pending.get();
            if (current == null) {
                Attempt candidateFailure = latestFailure.get();
                Pending created = new Pending(JSON.writeValueAsBytes(observation()), eventPending,
                        latest.get() == null ? null : latest.get().canonicalRulesSha256(),
                        candidateFailure == null ? null : candidateFailure.reason());
                pending.compareAndSet(null, created);
                current = pending.get();
            }
            HttpRequest request = HttpRequest.newBuilder(observationEndpoint).timeout(Duration.ofSeconds(5))
                    .header("Content-Type", "application/json")
                    .POST(HttpRequest.BodyPublishers.ofByteArray(current.bytes())).build();
            HttpResponse<byte[]> response = client.send(request, HttpResponse.BodyHandlers.ofByteArray());
            if (response.statusCode() != 204) {
                System.err.println(rejectedEventMessage(response.statusCode()));
                return;
            }
            if (!pending.compareAndSet(current, null)) return;
            if (current.eventPending() && current.failureReason() != null
                    && latestFailure.get() != null
                    && current.failureReason().equals(latestFailure.get().reason())) {
                latestFailure.compareAndSet(latestFailure.get(), null);
                eventPending = false;
            } else if (current.eventPending() && latestFailure.get() == null && latest.get() != null
                    && latest.get().canonicalRulesSha256().equals(current.snapshotDigest())) {
                eventPending = false;
            } else if (current.eventPending()) {
                eventPending = true;
            }
        } catch (InterruptedException interrupted) {
            Thread.currentThread().interrupt();
        } catch (Exception failure) {
            // Deliberately redact endpoint, identity, body, certificates, and exception details.
            System.err.println("Rule Observation Collector unavailable; exact event retained for retry");
        }
    }

    static String rejectedEventMessage(int statusCode) {
        return "Rule Observation Collector rejected event; response_status=" + statusCode
                + "; exact event retained for retry";
    }

    private boolean negotiate() throws Exception {
        byte[] requestBody = JSON.writeValueAsBytes(Map.of("protocol_version", PROTOCOL));
        HttpRequest request = HttpRequest.newBuilder(negotiationEndpoint).timeout(Duration.ofSeconds(5))
                .header("Content-Type", "application/json")
                .POST(HttpRequest.BodyPublishers.ofByteArray(requestBody)).build();
        HttpResponse<byte[]> response = client.send(request, HttpResponse.BodyHandlers.ofByteArray());
        if (response.statusCode() != 200) return false;
        JsonNode body = JSON.readTree(response.body());
        JsonNode supported = body.path("collector_supported");
        if (!"atlas-richie.protocol-negotiation/v1".equals(body.path("protocol_version").asText())
                || !"rule-load-observation".equals(body.path("boundary").asText())
                || !"compatible".equals(body.path("compatibility").asText()) || !supported.isArray()) return false;
        for (JsonNode version : supported) if (PROTOCOL.equals(version.asText())) {
            compatible = true;
            return true;
        }
        return false;
    }

    private Map<String, Object> observation() {
        if (sequence >= 9_007_199_254_740_991L) throw new IllegalStateException("rule observation sequence exhausted");
        AppliedSnapshot active = latest.get();
        Attempt attempt = latestFailure.get();
        String kind = attempt != null ? "snapshot_failed" : eventPending ? "snapshot_applied" : "heartbeat";
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("protocol_version", PROTOCOL);
        body.put("observation_id", UUID.randomUUID().toString());
        body.put("process_epoch", processEpoch);
        body.put("sequence", ++sequence);
        body.put("binding_id", bindingId);
        body.put("profile_id", profileId);
        body.put("event_kind", kind);
        body.put("active_snapshot", active == null ? null : snapshot(active));
        Map<String, Object> attemptBody = null;
        if (attempt != null) {
            attemptBody = new LinkedHashMap<>();
            attemptBody.put("source_revision", null);
            attemptBody.put("source_bytes_sha256", null);
            attemptBody.put("canonical_rules_sha256", null);
            attemptBody.put("failure_reason", attempt.reason());
        }
        body.put("attempt", attemptBody);
        body.put("observed_at", UTC_MILLIS.format(Instant.now().truncatedTo(ChronoUnit.MILLIS)));
        return body;
    }

    private static Map<String, Object> snapshot(AppliedSnapshot value) {
        List<Map<String, String>> members = new ArrayList<>();
        for (String fingerprint : value.memberFingerprints()) {
            members.add(Map.of("rule_kind", "flow", "fingerprint_sha256", fingerprint));
        }
        Map<String, Object> snapshot = new LinkedHashMap<>();
        snapshot.put("source_revision", null);
        snapshot.put("source_bytes_sha256", value.sourceBytesSha256());
        snapshot.put("canonical_rules_sha256", value.canonicalRulesSha256());
        snapshot.put("membership_complete", true);
        snapshot.put("members", members);
        return snapshot;
    }

    private record Attempt(String reason) { }
    private record Pending(byte[] bytes, boolean eventPending, String snapshotDigest, String failureReason) { }
}

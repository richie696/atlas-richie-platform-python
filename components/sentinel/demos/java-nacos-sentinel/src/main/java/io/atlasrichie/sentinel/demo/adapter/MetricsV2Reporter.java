package io.atlasrichie.sentinel.demo.adapter;

import com.fasterxml.jackson.core.JsonParser;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

import javax.net.ssl.KeyManagerFactory;
import javax.net.ssl.SSLContext;
import javax.net.ssl.TrustManagerFactory;
import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.KeyStore;
import java.security.MessageDigest;
import java.time.Duration;
import java.util.HexFormat;
import java.util.Set;
import java.util.Map;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;

/** Bounded single-flight HTTPS adapter for exact Metrics V2 durable ACKs. */
public final class MetricsV2Reporter implements AutoCloseable {
    private static final String PROTOCOL = "atlas-richie.metrics/v2";
    private static final String SNAPSHOT_PATH = "/api/reporting/v2/snapshots";
    private static final Set<String> RECEIPT_FIELDS = Set.of(
            "protocol_version", "reporter_id", "startup_epoch", "sequence", "body_sha256", "received_at");
    private static final ObjectMapper JSON = new ObjectMapper()
            .enable(JsonParser.Feature.STRICT_DUPLICATE_DETECTION);

    private final String reporterId;
    private final MetricsV2SnapshotBuilder snapshots;
    private final HttpClient client;
    private final URI endpoint;
    private final ScheduledExecutorService scheduler = Executors.newSingleThreadScheduledExecutor(runnable -> {
        Thread thread = new Thread(runnable, "sentinel-metrics-v2-reporter");
        thread.setDaemon(true);
        return thread;
    });
    private final AtomicReference<Pending> pending = new AtomicReference<>();

    public MetricsV2Reporter(String reporterId, MetricsV2SnapshotBuilder snapshots,
                             URI collectorBaseUri, SSLContext tls) {
        if (reporterId == null || reporterId.isBlank() || reporterId.length() > 200) {
            throw new IllegalArgumentException("reporter identity is invalid");
        }
        if (!"https".equalsIgnoreCase(collectorBaseUri.getScheme())
                || collectorBaseUri.getUserInfo() != null || collectorBaseUri.getQuery() != null
                || collectorBaseUri.getFragment() != null) {
            throw new IllegalArgumentException("Metrics V2 Collector URL must be a plain HTTPS origin");
        }
        if (snapshots == null || !reporterId.equals(snapshots.reporterId())) {
            throw new IllegalArgumentException("Metrics V2 snapshot identity does not match enrollment");
        }
        this.reporterId = reporterId;
        this.snapshots = snapshots;
        this.endpoint = collectorBaseUri.resolve(SNAPSHOT_PATH);
        this.client = HttpClient.newBuilder()
                .sslContext(tls)
                .connectTimeout(Duration.ofSeconds(3))
                .followRedirects(HttpClient.Redirect.NEVER)
                .build();
    }

    /** Start a one-second capture/send loop; HTTP work never runs on request threads. */
    public void start() {
        scheduler.scheduleWithFixedDelay(this::captureAndSend, 0, 1, TimeUnit.SECONDS);
    }

    @Override
    public void close() {
        scheduler.shutdownNow();
    }

    private void captureAndSend() {
        try {
            Pending inFlight = pending.get();
            if (inFlight == null) {
                Map<String, Object> snapshot = snapshots.nextSnapshot();
                byte[] bytes = JSON.writeValueAsBytes(snapshot);
                inFlight = new Pending(bytes, sha256(bytes), (long) snapshot.get("sequence"),
                        (String) snapshot.get("startup_epoch"));
                pending.compareAndSet(null, inFlight);
                inFlight = pending.get();
            }
            HttpRequest request = HttpRequest.newBuilder(endpoint)
                    .timeout(Duration.ofSeconds(5))
                    .header("Content-Type", "application/json")
                    .header("Accept", "application/json")
                    .POST(HttpRequest.BodyPublishers.ofByteArray(inFlight.body()))
                    .build();
            HttpResponse<byte[]> response = client.send(request, HttpResponse.BodyHandlers.ofByteArray());
            if (response.statusCode() != 200) {
                System.err.println(rejectedHttpStatusMessage(response.statusCode()));
                return;
            }
            if (!validReceipt(response.body(), inFlight)) {
                System.err.println("Metrics V2 durable ACK malformed or mismatched; exact snapshot retained for retry");
                return;
            }
            pending.compareAndSet(inFlight, null);
        } catch (InterruptedException interrupted) {
            Thread.currentThread().interrupt();
        } catch (Exception failure) {
            // No payload, endpoint credentials, certificate, or exception message is logged.
            System.err.println("Metrics V2 transport unavailable; exact snapshot retained for retry");
        }
    }

    static String rejectedHttpStatusMessage(int statusCode) {
        return "Metrics V2 durable ACK rejected; response_status=" + statusCode
                + "; exact snapshot retained for retry";
    }

    private boolean validReceipt(byte[] body, Pending expected) {
        try {
            JsonNode receipt = JSON.readTree(body);
            if (receipt == null || !receipt.isObject()) return false;
            var names = new java.util.HashSet<String>();
            receipt.fieldNames().forEachRemaining(names::add);
            return names.equals(RECEIPT_FIELDS)
                    && PROTOCOL.equals(receipt.path("protocol_version").asText())
                    && reporterId.equals(receipt.path("reporter_id").asText())
                    && expected.startupEpoch().equals(receipt.path("startup_epoch").asText())
                    && receipt.path("sequence").isIntegralNumber()
                    && expected.sequence() == receipt.path("sequence").longValue()
                    && expected.sha256().equals(receipt.path("body_sha256").asText())
                    && receipt.path("received_at").asText().matches(
                    "^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\\.[0-9]{6}Z$");
        } catch (IOException malformed) {
            return false;
        }
    }

    /** Load a PKCS#12 client identity and a separate PEM CA trust bundle. */
    public static SSLContext mutualTls(Path clientPkcs12, char[] password, Path trustedCaPem)
            throws Exception {
        KeyStore identity = KeyStore.getInstance("PKCS12");
        try (var input = Files.newInputStream(clientPkcs12)) { identity.load(input, password); }
        KeyManagerFactory keys = KeyManagerFactory.getInstance(KeyManagerFactory.getDefaultAlgorithm());
        keys.init(identity, password);
        KeyStore trust = KeyStore.getInstance(KeyStore.getDefaultType());
        trust.load(null, null);
        try (var certificates = Files.newInputStream(trustedCaPem)) {
            var factory = java.security.cert.CertificateFactory.getInstance("X.509");
            var parsed = factory.generateCertificates(certificates);
            int index = 0;
            for (var certificate : parsed) trust.setCertificateEntry("collector-ca-" + index++, certificate);
            if (index == 0) throw new IllegalArgumentException("Collector CA bundle is empty");
        }
        TrustManagerFactory trustManagers = TrustManagerFactory.getInstance(
                TrustManagerFactory.getDefaultAlgorithm());
        trustManagers.init(trust);
        SSLContext context = SSLContext.getInstance("TLS");
        context.init(keys.getKeyManagers(), trustManagers.getTrustManagers(), null);
        return context;
    }

    private static String sha256(byte[] bytes) throws Exception {
        return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes));
    }

    private record Pending(byte[] body, String sha256, long sequence, String startupEpoch) { }
}

package io.atlasrichie.sentinel.demo;

import com.alibaba.csp.sentinel.Entry;
import com.alibaba.csp.sentinel.SphU;
import com.alibaba.csp.sentinel.slots.block.BlockException;
import io.atlasrichie.sentinel.demo.adapter.SentinelFlowRuleAdapter;
import io.atlasrichie.sentinel.demo.adapter.SentinelFlowRuleAdapter.AppliedSnapshot;
import io.atlasrichie.sentinel.demo.adapter.MetricsV2Reporter;
import io.atlasrichie.sentinel.demo.adapter.MetricsV2SnapshotBuilder;
import io.atlasrichie.sentinel.demo.adapter.RuleLoadObservationV1Reporter;
import io.atlasrichie.sentinel.demo.adapter.RulePublicationReceiptV1Reporter;
import io.atlasrichie.sentinel.demo.source.RuleSnapshotSource;
import io.atlasrichie.sentinel.demo.source.RuleSnapshotSources;
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;

import java.io.IOException;
import java.net.InetSocketAddress;
import java.net.URI;
import java.nio.file.Path;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;

/** Small real HTTP service using Alibaba Sentinel and an explicitly selected rule source. */
public final class JavaSentinelDemo {
    private static final String RESOURCE = "GET /api/hello";

    private JavaSentinelDemo() { }

    public static void main(String[] args) throws Exception {
        System.setProperty("csp.sentinel.log.dir", setting("SENTINEL_LOG_DIR", ".sentinel-log"));
        String sourceProvider = setting("RULE_SOURCE_PROVIDER", "nacos");
        int port = Integer.parseInt(setting("DEMO_PORT", "18081"));
        String sourceProfile = setting("RULE_SOURCE_PROFILE", "native-array-v1");
        String bindingId = System.getenv("RULE_BINDING_ID");
        String ruleProfileId = setting("RULE_PROFILE_ID", "sentinel-java-v1");

        RuleSnapshotSource ruleSource = RuleSnapshotSources.fromEnvironment();
        AtomicReference<String> lastContent = new AtomicReference<>("");
        AtomicReference<AppliedSnapshot> activeSnapshot = new AtomicReference<>();
        AtomicReference<String> lastRejectedContent = new AtomicReference<>("");
        AtomicReference<String> lastRefreshFailure = new AtomicReference<>("");
        AtomicReference<RuleLoadObservationV1Reporter> ruleObservationRef = new AtomicReference<>();
        AtomicReference<RulePublicationReceiptV1Reporter> publicationReceiptRef = new AtomicReference<>();
        RuleSnapshotLoader loadSnapshot = switch (sourceProfile) {
            case "native-array-v1" -> SentinelFlowRuleAdapter::apply;
            case "managed-envelope-v1" -> {
                if (bindingId == null || bindingId.isBlank()) {
                    throw new IllegalStateException("managed rule profile requires RULE_BINDING_ID");
                }
                yield content -> SentinelFlowRuleAdapter.applyManaged(content, bindingId,
                        ruleProfileId, activeSnapshot.get());
            }
            default -> throw new IllegalStateException("unsupported RULE_SOURCE_PROFILE");
        };
        String initial = ruleSource.read();
        AppliedSnapshot applied = loadSnapshot.load(initial);
        lastContent.set(initial);
        activeSnapshot.set(applied);
        ScheduledExecutorService rulePoller = Executors.newSingleThreadScheduledExecutor();
        rulePoller.scheduleWithFixedDelay(() -> {
            try {
                String content = ruleSource.read();
                if (content == null || content.equals(lastRejectedContent.get())) return;
                if (content.equals(lastContent.get())) {
                    if (shouldReportSnapshotRecovery(content, lastContent.get(),
                            lastRejectedContent.get(), lastRefreshFailure.getAndSet(""))) {
                        System.out.println("rule source recovered; retained active snapshot");
                        lastRejectedContent.set("");
                        AppliedSnapshot active = activeSnapshot.get();
                        RuleLoadObservationV1Reporter observer = ruleObservationRef.get();
                        if (active != null && observer != null) observer.applied(active);
                        RulePublicationReceiptV1Reporter receiptReporter = publicationReceiptRef.get();
                        if (active != null && receiptReporter != null) receiptReporter.applied(active);
                    }
                    return;
                }
                try {
                    AppliedSnapshot updated = loadSnapshot.load(content);
                    lastContent.set(content);
                    activeSnapshot.set(updated);
                    lastRejectedContent.set("");
                    lastRefreshFailure.set("");
                    RuleLoadObservationV1Reporter observer = ruleObservationRef.get();
                    if (observer != null) observer.applied(updated);
                    RulePublicationReceiptV1Reporter receiptReporter = publicationReceiptRef.get();
                    if (receiptReporter != null) receiptReporter.applied(updated);
                } catch (Exception invalid) {
                    lastRejectedContent.set(content);
                    lastRefreshFailure.set("decode_rejected");
                    RuleLoadObservationV1Reporter observer = ruleObservationRef.get();
                    if (observer != null) observer.failed("decode_rejected");
                    System.err.println("rule source update rejected: invalid_rules; retaining last-known-good rules");
                }
            } catch (Exception error) {
                String previousFailure = lastRefreshFailure.getAndSet("source_unavailable");
                if (!"source_unavailable".equals(previousFailure)) {
                    RuleLoadObservationV1Reporter observer = ruleObservationRef.get();
                    if (observer != null) observer.failed("source_unavailable");
                    System.err.println("rule source unavailable; retaining last-known-good rules");
                }
            }
        }, 1, 1, TimeUnit.SECONDS);

        HttpServer server = HttpServer.create(new InetSocketAddress(
                setting("DEMO_BIND_HOST", "127.0.0.1"), port), 64);
        ExecutorService executor = Executors.newFixedThreadPool(8);
        server.setExecutor(executor);
        MetricsV2SnapshotBuilder metrics = null;
        MetricsV2Reporter reporter = null;
        RulePublicationReceiptV1Reporter publicationReceiptReporter = null;
        String collectorUrl = System.getenv("METRICS_COLLECTOR_URL");
        if (collectorUrl != null && !collectorUrl.isBlank()) {
            String reporterId = required("METRICS_REPORTER_ID");
            metrics = new MetricsV2SnapshotBuilder(reporterId);
            reporter = new MetricsV2Reporter(reporterId, metrics, URI.create(collectorUrl),
                    MetricsV2Reporter.mutualTls(
                            Path.of(required("METRICS_CLIENT_PKCS12")),
                            required("METRICS_CLIENT_PKCS12_PASSWORD").toCharArray(),
                            Path.of(required("METRICS_COLLECTOR_CA"))));
            reporter.start();
            if ("managed-envelope-v1".equals(sourceProfile)) {
                publicationReceiptReporter = new RulePublicationReceiptV1Reporter(
                        metrics.startupEpoch(), URI.create(collectorUrl),
                        MetricsV2Reporter.mutualTls(
                                Path.of(required("METRICS_CLIENT_PKCS12")),
                                required("METRICS_CLIENT_PKCS12_PASSWORD").toCharArray(),
                                Path.of(required("METRICS_COLLECTOR_CA"))));
                publicationReceiptReporter.start();
                publicationReceiptRef.set(publicationReceiptReporter);
                publicationReceiptReporter.applied(applied);
            }
        }
        MetricsV2SnapshotBuilder metricsBuilder = metrics;
        MetricsV2Reporter metricsReporter = reporter;
        RuleLoadObservationV1Reporter ruleObservationReporter = null;
        if (bindingId != null && !bindingId.isBlank()) {
            if (metricsBuilder == null || collectorUrl == null || collectorUrl.isBlank()) {
                throw new IllegalStateException("rule observations require the enrolled Metrics V2 process identity");
            }
            ruleObservationReporter = new RuleLoadObservationV1Reporter(
                    metricsBuilder.startupEpoch(), bindingId,
                    setting("RULE_PROFILE_ID", "sentinel-java-v1"), URI.create(collectorUrl),
                    MetricsV2Reporter.mutualTls(
                            Path.of(required("METRICS_CLIENT_PKCS12")),
                            required("METRICS_CLIENT_PKCS12_PASSWORD").toCharArray(),
                            Path.of(required("METRICS_COLLECTOR_CA"))));
            ruleObservationRef.set(ruleObservationReporter);
            ruleObservationReporter.start(activeSnapshot.get());
        }
        server.createContext("/health", exchange -> respond(exchange, 200, "ok\n"));
        server.createContext("/rules", exchange -> {
            AppliedSnapshot snapshot = activeSnapshot.get();
                String managed = snapshot == null || snapshot.managedPublication() == null ? ""
                        : "\nbinding_id=" + snapshot.managedPublication().bindingId()
                        + "\npublication_id=" + snapshot.managedPublication().publicationId()
                        + "\ntarget_version_id=" + snapshot.managedPublication().targetVersionId()
                        + "\npublication_sequence=" + snapshot.managedPublication().publicationSequence()
                        + "\ntarget_payload_sha256=" + snapshot.managedPublication().payloadSha256();
                respond(exchange, 200, "rules_loaded=" + (snapshot != null)
                    + "\nrule_count=" + (snapshot == null ? 0 : snapshot.ruleCount())
                    + "\nsource_bytes_sha256=" + (snapshot == null ? "" : snapshot.sourceBytesSha256())
                    + "\ncanonical_rules_sha256=" + (snapshot == null ? "" : snapshot.canonicalRulesSha256())
                    + managed + "\n");
        });
        server.createContext("/api/hello", exchange -> handleHello(exchange, metricsBuilder));
        server.createContext("/api/delay", exchange -> handleDelay(exchange, metricsBuilder));
        RuleLoadObservationV1Reporter activeRuleObservationReporter = ruleObservationReporter;
        RulePublicationReceiptV1Reporter activePublicationReceiptReporter = publicationReceiptReporter;
        Runtime.getRuntime().addShutdownHook(new Thread(() -> {
            server.stop(1);
            executor.shutdown();
            rulePoller.shutdownNow();
            if (metricsReporter != null) metricsReporter.close();
            if (activeRuleObservationReporter != null) activeRuleObservationReporter.close();
            if (activePublicationReceiptReporter != null) activePublicationReceiptReporter.close();
            try { ruleSource.close(); } catch (Exception ignored) { }
        }));
        server.start();
        System.out.printf("java-demo listening on %s:%d; rule source=%s%n",
                setting("DEMO_BIND_HOST", "127.0.0.1"), port, sourceProvider);
    }

    static boolean shouldReportSnapshotRecovery(String content, String acceptedContent,
                                                String rejectedContent, String previousFailure) {
        return content != null && content.equals(acceptedContent)
                && !content.equals(rejectedContent) && previousFailure != null && !previousFailure.isEmpty();
    }

    @FunctionalInterface
    interface RuleSnapshotLoader {
        AppliedSnapshot load(String content) throws Exception;
    }

    private static void handleHello(HttpExchange exchange, MetricsV2SnapshotBuilder metrics) throws IOException {
        long started = System.nanoTime();
        if (!"GET".equals(exchange.getRequestMethod())) {
            respond(exchange, 405, "method not allowed\n");
            record(metrics, true, false, false, false, started);
            return;
        }
        boolean admitted = false;
        boolean blocked = false;
        boolean completed = false;
        try (Entry ignored = SphU.entry(RESOURCE)) {
            admitted = true;
            respond(exchange, 200, "hello from Java Sentinel\n");
            completed = true;
        } catch (BlockException rejection) {
            blocked = true;
            respond(exchange, 429, "blocked by Sentinel\n");
            completed = true;
        } finally {
            record(metrics, completed, admitted, blocked, admitted && completed, started);
        }
    }

    private static void handleDelay(HttpExchange exchange, MetricsV2SnapshotBuilder metrics) throws IOException {
        long started = System.nanoTime();
        if (!"GET".equals(exchange.getRequestMethod())) {
            respond(exchange, 405, "method not allowed\n");
            record(metrics, true, false, false, false, started);
            return;
        }
        long delay = 0;
        String query = exchange.getRequestURI().getRawQuery();
        if (query != null) for (String item : query.split("&")) {
            if (item.startsWith("ms=")) try { delay = Long.parseLong(item.substring(3)); }
            catch (NumberFormatException ignored) { delay = 0; }
        }
        delay = Math.max(0, Math.min(2_000, delay));
        try { TimeUnit.MILLISECONDS.sleep(delay); }
        catch (InterruptedException error) { Thread.currentThread().interrupt(); respond(exchange, 503, "interrupted\n"); return; }
        try {
            respond(exchange, 200, "delay_ms=" + delay + "\n");
            record(metrics, true, true, false, true, started);
        } catch (IOException error) {
            record(metrics, false, true, false, false, started);
            throw error;
        }
    }

    private static void record(MetricsV2SnapshotBuilder metrics, boolean completed,
                               boolean admitted, boolean blocked, boolean transaction, long started) {
        if (metrics != null) metrics.recordHttpResponse(completed, admitted, blocked, transaction,
                Math.max(0, System.nanoTime() - started));
    }

    private static void respond(HttpExchange exchange, int status, String body) throws IOException {
        byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
        exchange.getResponseHeaders().set("Content-Type", "text/plain; charset=utf-8");
        exchange.getResponseHeaders().set("Cache-Control", "no-store");
        exchange.sendResponseHeaders(status, bytes.length);
        try (var output = exchange.getResponseBody()) { output.write(bytes); }
    }

    private static String setting(String name, String fallback) {
        String value = System.getenv(name);
        return value == null || value.isBlank() ? fallback : value;
    }

    private static String required(String name) {
        String value = System.getenv(name);
        if (value == null || value.isBlank()) throw new IllegalStateException(name + " is required");
        return value;
    }
}

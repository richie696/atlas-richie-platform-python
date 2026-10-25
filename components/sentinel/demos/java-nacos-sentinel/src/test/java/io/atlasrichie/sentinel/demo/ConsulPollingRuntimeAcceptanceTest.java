package io.atlasrichie.sentinel.demo;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;

import java.io.File;
import java.io.IOException;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.net.ServerSocket;
import java.net.URI;
import java.net.URLEncoder;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.TimeUnit;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

/** Opt-in Consul KV → official Sentinel Java engine polling and recovery acceptance. */
class ConsulPollingRuntimeAcceptanceTest {
    private static final Duration HTTP_TIMEOUT = Duration.ofSeconds(5);

    @Test
    @EnabledIfEnvironmentVariable(named = "SENTINEL_T004_CONSUL_ACCEPTANCE", matches = "true")
    void loadsWithoutTrafficRefreshesRulesRetainsLastKnownGoodAndRestarts() throws Exception {
        String consulUrl = setting("SENTINEL_T004_CONSUL_URL", "").replaceAll("/+$", "");
        assertTrue(consulUrl.matches("http://127\\.0\\.0\\.1:[0-9]+"),
                "acceptance must use the disposable loopback-only Consul provider");
        String key = "sentinel/t004/java-" + UUID.randomUUID() + "/flow-rules.json";
        URI keyUri = consulKeyUri(consulUrl, key);
        HttpClient http = HttpClient.newBuilder().connectTimeout(HTTP_TIMEOUT).build();
        HttpResponse<String> existing = send(http, HttpRequest.newBuilder(URI.create(keyUri + "?raw=true")).GET().build());
        assertEquals(404, existing.statusCode(), "random test key must be unoccupied before the write");

        Path runtimeDirectory = Files.createTempDirectory("sentinel-java-consul-t004-");
        Path processLog = runtimeDirectory.resolve("runtime.log");
        Process runtime = null;
        boolean keyOwned = false;
        try {
            put(http, keyUri, rules(1));
            keyOwned = true;
            int port = unusedLoopbackPort();
            runtime = startRuntime(runtimeDirectory, processLog, consulUrl, key, port);
            URI origin = URI.create("http://127.0.0.1:" + port);
            awaitHealth(runtime, http, origin);
            String initial = awaitSnapshot(runtime, http, origin, null);
            String initialHash = value(initial, "source_bytes_sha256");
            assertTrue(initial.contains("rule_count=1"), "Consul snapshot must load before business traffic");
            List<Integer> initialStatuses = requestBurst(http, origin, 8);
            assertTrue(initialStatuses.contains(200) && initialStatuses.contains(429),
                    "official Sentinel Java engine must enforce the loaded Consul rule");

            put(http, keyUri, rules(100));
            String updated = awaitSnapshot(runtime, http, origin, initialHash);
            String updatedHash = value(updated, "source_bytes_sha256");
            assertTrue(requestBurst(http, origin, 8).stream().allMatch(status -> status == 200),
                    "valid Consul update must change actual request admission");

            put(http, keyUri, invalidRules());
            awaitLog(processLog, "rule source update rejected: invalid_rules");
            assertEquals(updatedHash, value(readRules(http, origin), "source_bytes_sha256"),
                    "invalid Consul content must retain last-known-good snapshot");

            assertEquals("true", send(http, HttpRequest.newBuilder(keyUri).DELETE().build()).body(),
                    "remove only this test's random Consul key");
            awaitLog(processLog, "rule source unavailable; retaining last-known-good rules");
            assertEquals(updatedHash, value(readRules(http, origin), "source_bytes_sha256"),
                    "missing Consul key must not clear active rules");

            put(http, keyUri, rules(2));
            String recovered = awaitSnapshot(runtime, http, origin, updatedHash);
            String recoveredHash = value(recovered, "source_bytes_sha256");
            assertTrue(requestBurst(http, origin, 8).contains(429), "recovered rules must be enforced");

            stopRuntime(runtime);
            runtime = null;
            int restartedPort = unusedLoopbackPort();
            runtime = startRuntime(runtimeDirectory, runtimeDirectory.resolve("runtime-restarted.log"),
                    consulUrl, key, restartedPort);
            URI restartedOrigin = URI.create("http://127.0.0.1:" + restartedPort);
            awaitHealth(runtime, http, restartedOrigin);
            String restarted = awaitSnapshot(runtime, http, restartedOrigin, null);
            assertEquals(recoveredHash, value(restarted, "source_bytes_sha256"),
                    "restart must load the persisted provider snapshot before requests");
            assertTrue(requestBurst(http, restartedOrigin, 8).contains(429),
                    "restarted Java Sentinel engine must enforce the Consul snapshot");
        } finally {
            stopRuntime(runtime);
            try {
                if (keyOwned) {
                    HttpResponse<String> removed = send(http, HttpRequest.newBuilder(keyUri).DELETE().build());
                    assertEquals(200, removed.statusCode(), "cleanup must remove only the random test key");
                }
            } finally {
                deleteTree(runtimeDirectory);
            }
        }
    }

    private static Process startRuntime(Path runtimeDirectory, Path processLog, String consulUrl, String key, int port)
            throws IOException {
        String classPath = Path.of("").toAbsolutePath().resolve("target/classes") + File.pathSeparator
                + System.getProperty("surefire.test.class.path", System.getProperty("java.class.path"));
        ProcessBuilder builder = new ProcessBuilder("java", "-cp", classPath, JavaSentinelDemo.class.getName());
        builder.directory(runtimeDirectory.toFile()).redirectErrorStream(true).redirectOutput(processLog.toFile());
        builder.environment().put("RULE_SOURCE_PROVIDER", "consul");
        builder.environment().put("CONSUL_URL", consulUrl);
        builder.environment().put("CONSUL_KEY", key);
        builder.environment().put("RULE_SOURCE_PROFILE", "native-array-v1");
        builder.environment().put("NACOS_AUTH_ENABLED", "false");
        builder.environment().put("DEMO_BIND_HOST", "127.0.0.1");
        builder.environment().put("DEMO_PORT", Integer.toString(port));
        builder.environment().remove("METRICS_COLLECTOR_URL");
        builder.environment().remove("RULE_BINDING_ID");
        return builder.start();
    }

    private static URI consulKeyUri(String endpoint, String key) {
        String encoded = java.util.Arrays.stream(key.split("/", -1))
                .map(segment -> URLEncoder.encode(segment, StandardCharsets.UTF_8).replace("+", "%20"))
                .reduce((left, right) -> left + "/" + right).orElseThrow();
        return URI.create(endpoint + "/v1/kv/" + encoded);
    }

    private static void put(HttpClient http, URI uri, String content) throws Exception {
        HttpRequest request = HttpRequest.newBuilder(uri).timeout(HTTP_TIMEOUT)
                .PUT(HttpRequest.BodyPublishers.ofString(content, StandardCharsets.UTF_8)).build();
        HttpResponse<String> response = send(http, request);
        assertEquals(200, response.statusCode(), "Consul KV must accept the test-owned snapshot");
        assertEquals("true", response.body());
    }

    private static HttpResponse<String> send(HttpClient http, HttpRequest request) throws IOException, InterruptedException {
        return http.send(request, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
    }

    private static void awaitHealth(Process runtime, HttpClient http, URI origin) throws Exception {
        long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(30);
        while (System.nanoTime() < deadline) {
            assertTrue(runtime.isAlive(), "Java Runtime exited before health became ready");
            try {
                if (send(http, HttpRequest.newBuilder(origin.resolve("/health")).GET().build()).statusCode() == 200) return;
            } catch (IOException ignored) { }
            Thread.sleep(100L);
        }
        throw new AssertionError("Java Runtime did not become healthy");
    }

    private static String awaitSnapshot(Process runtime, HttpClient http, URI origin, String previousHash) throws Exception {
        long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(20);
        while (System.nanoTime() < deadline) {
            assertTrue(runtime.isAlive(), "Java Runtime exited while waiting for Consul snapshot");
            String current = readRules(http, origin);
            String hash = value(current, "source_bytes_sha256");
            if (current.contains("rules_loaded=true") && current.contains("rule_count=1")
                    && (previousHash == null || !hash.equals(previousHash))) return current;
            Thread.sleep(100L);
        }
        throw new AssertionError("timed out waiting for Consul snapshot update");
    }

    private static void awaitLog(Path path, String expected) throws Exception {
        long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(15);
        while (System.nanoTime() < deadline) {
            String log = Files.exists(path) ? Files.readString(path) : "";
            if (log.contains(expected)) return;
            Thread.sleep(100L);
        }
        throw new AssertionError("runtime log did not contain expected stable event: " + expected);
    }

    private static String readRules(HttpClient http, URI origin) throws Exception {
        HttpResponse<String> response = send(http, HttpRequest.newBuilder(origin.resolve("/rules")).GET().build());
        assertEquals(200, response.statusCode());
        return response.body();
    }

    private static List<Integer> requestBurst(HttpClient http, URI origin, int size) throws Exception {
        List<Integer> statuses = new ArrayList<>(size);
        for (int index = 0; index < size; index++) {
            statuses.add(send(http, HttpRequest.newBuilder(origin.resolve("/api/hello")).GET().build()).statusCode());
        }
        return statuses;
    }

    private static String rules(int qps) {
        return "[{\"resource\":\"GET /api/hello\",\"grade\":1,\"count\":" + qps
                + ",\"strategy\":0,\"controlBehavior\":0,\"limitApp\":\"default\"}]";
    }

    private static String invalidRules() {
        return "[{\"resource\":\"GET /api/hello\",\"grade\":1,\"count\":1,"
                + "\"strategy\":0,\"controlBehavior\":0,\"limitApp\":\"default\",\"unknown_acceptance_field\":true}]";
    }

    private static String value(String snapshot, String key) {
        String prefix = key + "=";
        for (String line : snapshot.split("\\R")) if (line.startsWith(prefix)) return line.substring(prefix.length()).trim();
        throw new AssertionError("snapshot missing " + key);
    }

    private static int unusedLoopbackPort() throws IOException {
        try (ServerSocket socket = new ServerSocket()) {
            socket.bind(new InetSocketAddress(InetAddress.getLoopbackAddress(), 0));
            return socket.getLocalPort();
        }
    }

    private static void stopRuntime(Process runtime) throws InterruptedException {
        if (runtime == null) return;
        runtime.destroy();
        if (!runtime.waitFor(5, TimeUnit.SECONDS)) {
            runtime.destroyForcibly();
            assertTrue(runtime.waitFor(5, TimeUnit.SECONDS));
        }
    }

    private static void deleteTree(Path directory) throws IOException {
        if (!Files.exists(directory)) return;
        try (var paths = Files.walk(directory)) {
            for (Path path : paths.sorted(Comparator.reverseOrder()).toList()) Files.deleteIfExists(path);
        }
    }

    private static String setting(String name, String fallback) {
        String value = System.getenv(name);
        return value == null || value.isBlank() ? fallback : value;
    }
}

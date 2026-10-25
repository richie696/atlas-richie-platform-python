package io.atlasrichie.sentinel.demo;

import com.alibaba.nacos.api.NacosFactory;
import com.alibaba.nacos.api.config.ConfigService;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;

import java.io.File;
import java.io.IOException;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.net.ServerSocket;
import java.net.URI;
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
import java.util.Properties;
import java.util.UUID;
import java.util.concurrent.TimeUnit;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

/** Opt-in Nacos 3 → official Sentinel Java SDK polling, LKG recovery, and restart acceptance. */
class NacosPollingRuntimeAcceptanceTest {
    private static final String GROUP = "DEFAULT_GROUP";
    private static final Duration HTTP_TIMEOUT = Duration.ofSeconds(5);

    @Test
    @EnabledIfEnvironmentVariable(named = "SENTINEL_T004_NACOS_ACCEPTANCE", matches = "true")
    void loadsWithoutBusinessTrafficRefreshesRulesAndRetainsLastKnownGood() throws Exception {
        boolean authEnabled = !"false".equalsIgnoreCase(setting("NACOS_AUTH_ENABLED", "true"));
        if (!authEnabled) {
            assertEquals("true", System.getenv("SENTINEL_T004_DISPOSABLE_NACOS"),
                    "disabling auth is allowed only for an explicitly disposable provider");
        }
        String password = System.getenv("NACOS_PASSWORD");
        if (authEnabled) {
            assertNotNull(password, "NACOS_PASSWORD must be supplied by the local secret environment");
            assertFalse(password.isBlank(), "NACOS_PASSWORD must not be blank");
        } else {
            password = "";
        }

        String serverAddress = setting("NACOS_SERVER_ADDR", "127.0.0.1:8848");
        String namespace = setting("NACOS_NAMESPACE", "public");
        String username = authEnabled ? setting("NACOS_USERNAME", "nacos") : "";
        String dataId = "sentinel-t004-acceptance-" + UUID.randomUUID() + "-flow-rules.json";
        Path runtimeDirectory = Files.createTempDirectory("sentinel-java-t004-");
        Path processLog = runtimeDirectory.resolve("runtime.log");
        ConfigService configService = createConfigService(serverAddress, namespace, username, password,
                runtimeDirectory.resolve("publisher-cache"), runtimeDirectory.resolve("publisher-log"));
        Process runtime = null;
        boolean createdConfig = false;

        try {
            String existing = configService.getConfig(dataId, GROUP, 5_000L);
            assertTrue(existing == null || existing.isEmpty(), "random acceptance Data ID must be unused");
            // From this point the random ID is owned by this test, including an uncertain publish result.
            createdConfig = true;
            publish(configService, dataId, rules(1));

            int port = unusedLoopbackPort();
            runtime = startRuntime(runtimeDirectory, processLog, serverAddress, namespace, username,
                    password, dataId, port);
            HttpClient http = HttpClient.newBuilder().connectTimeout(HTTP_TIMEOUT).build();
            URI origin = URI.create("http://127.0.0.1:" + port);

            awaitHealth(runtime, http, origin);
            String initial = awaitSnapshot(runtime, http, origin, null);
            assertTrue(initial.contains("rules_loaded=true"), "initial snapshot must load before traffic");
            assertTrue(initial.contains("rule_count=1"), "initial snapshot must contain one rule");
            String initialHash = value(initial, "source_bytes_sha256");

            List<Integer> restrictiveStatuses = requestBurst(http, origin, 8);
            assertTrue(restrictiveStatuses.contains(200), "the restrictive rule should admit a request");
            assertTrue(restrictiveStatuses.contains(429), "official Sentinel must block excess requests");

            publish(configService, dataId, rules(100));
            String updated = awaitSnapshot(runtime, http, origin, initialHash);
            String updatedHash = value(updated, "source_bytes_sha256");
            assertFalse(updatedHash.equals(initialHash), "valid provider update must become active");
            assertTrue(requestBurst(http, origin, 8).stream().allMatch(status -> status == 200),
                    "updated high threshold should admit the bounded request burst");

            publish(configService, dataId, invalidRules());
            Thread.sleep(1_500L); // allow at least one configured one-second poll after publication
            String afterRejectedUpdate = readRules(http, origin);
            assertEquals(updatedHash, value(afterRejectedUpdate, "source_bytes_sha256"),
                    "invalid provider update must not replace the accepted snapshot");
            assertTrue(requestBurst(http, origin, 8).stream().allMatch(status -> status == 200),
                    "the accepted high-threshold last-known-good rule must remain active");

            publish(configService, dataId, rules(2));
            String recovered = awaitSnapshot(runtime, http, origin, updatedHash);
            String recoveredHash = value(recovered, "source_bytes_sha256");
            assertTrue(requestBurst(http, origin, 8).contains(429),
                    "a valid provider recovery must replace last-known-good and enforce the new threshold");

            if ("true".equals(System.getenv("SENTINEL_T004_DISPOSABLE_NACOS"))) {
                DisposableNacos disposableNacos = pauseDisposableNacos();
                try {
                    assertTrue(disposableNacos.isPaused(), "the exact disposable provider must be paused during outage checks");
                    String duringOutage = readRules(http, origin);
                    assertEquals(recoveredHash, value(duringOutage, "source_bytes_sha256"),
                            "Nacos outage must retain the active last-known-good snapshot");
                    assertTrue(requestBurst(http, origin, 8).contains(429),
                            "the restrictive last-known-good rule must remain active during provider outage");
                } finally {
                    disposableNacos.resume();
                }
                assertFalse(disposableNacos.isPaused(), "the disposable provider must be resumed before recovery checks");
                publish(configService, dataId, rules(3));
                String afterOutage = awaitSnapshot(runtime, http, origin, recoveredHash);
                recoveredHash = value(afterOutage, "source_bytes_sha256");
                assertTrue(requestBurst(http, origin, 8).contains(429),
                        "the newly fetched restrictive rule must be enforced after provider recovery");
            }

            stopRuntime(runtime);
            runtime = null;
            runtime = startRuntime(runtimeDirectory, runtimeDirectory.resolve("runtime-restarted.log"),
                    serverAddress, namespace, username, password, dataId, port);
            awaitHealth(runtime, http, origin);
            String restarted = awaitSnapshot(runtime, http, origin, null);
            assertEquals(recoveredHash, value(restarted, "source_bytes_sha256"),
                    "process restart must load the persisted provider snapshot before business traffic");
            assertTrue(requestBurst(http, origin, 8).contains(429),
                    "the restarted runtime must execute the provider rule");
        } finally {
            stopRuntime(runtime);
            try {
                if (createdConfig) {
                    String remaining = configService.getConfig(dataId, GROUP, 5_000L);
                    if (remaining != null && !remaining.isEmpty()) {
                        assertTrue(configService.removeConfig(dataId, GROUP),
                                "the test-owned random Nacos Data ID must be removed");
                    }
                }
            } finally {
                configService.shutDown();
                deleteTree(runtimeDirectory);
            }
        }
    }

    private static ConfigService createConfigService(String serverAddress, String namespace,
                                                     String username, String password,
                                                     Path cacheDirectory, Path logDirectory) throws Exception {
        Files.createDirectories(cacheDirectory);
        Files.createDirectories(logDirectory);
        Properties properties = new Properties();
        properties.setProperty("serverAddr", serverAddress);
        properties.setProperty("namespace", namespace);
        if (!username.isBlank() && !password.isBlank()) {
            properties.setProperty("username", username);
            properties.setProperty("password", password);
        }
        properties.setProperty("cacheDir", cacheDirectory.toString());
        properties.setProperty("logDir", logDirectory.toString());
        return NacosFactory.createConfigService(properties);
    }

    private static Process startRuntime(Path runtimeDirectory, Path processLog, String serverAddress,
                                        String namespace, String username, String password,
                                        String dataId, int port) throws IOException {
        Path projectRoot = Path.of("").toAbsolutePath();
        String testClassPath = System.getProperty("surefire.test.class.path",
                System.getProperty("java.class.path"));
        String classPath = projectRoot.resolve("target/classes") + File.pathSeparator + testClassPath;
        ProcessBuilder builder = new ProcessBuilder("java", "-cp", classPath,
                JavaSentinelDemo.class.getName());
        builder.directory(runtimeDirectory.toFile());
        builder.redirectErrorStream(true);
        builder.redirectOutput(processLog.toFile());
        builder.environment().put("NACOS_SERVER_ADDR", serverAddress);
        builder.environment().put("NACOS_NAMESPACE", namespace);
        builder.environment().put("NACOS_USERNAME", username);
        builder.environment().put("NACOS_PASSWORD", password);
        builder.environment().put("NACOS_AUTH_ENABLED", setting("NACOS_AUTH_ENABLED", "true"));
        builder.environment().put("NACOS_DATA_ID", dataId);
        builder.environment().put("NACOS_GROUP", GROUP);
        builder.environment().put("DEMO_BIND_HOST", "127.0.0.1");
        builder.environment().put("DEMO_PORT", Integer.toString(port));
        builder.environment().put("NACOS_CACHE_DIR", runtimeDirectory.resolve("runtime-cache").toString());
        builder.environment().put("NACOS_LOG_DIR", runtimeDirectory.resolve("runtime-nacos-log").toString());
        builder.environment().put("SENTINEL_LOG_DIR", runtimeDirectory.resolve("runtime-sentinel-log").toString());
        return builder.start();
    }

    private static void awaitHealth(Process runtime, HttpClient http, URI origin) throws Exception {
        long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(30);
        while (System.nanoTime() < deadline) {
            assertTrue(runtime.isAlive(), "runtime exited before health became ready");
            try {
                HttpResponse<String> response = get(http, origin.resolve("/health"));
                if (response.statusCode() == 200) return;
            } catch (IOException ignored) {
                // The child may still be binding its loopback HTTP server.
            }
            Thread.sleep(100L);
        }
        throw new AssertionError("runtime did not become healthy before the bounded startup deadline");
    }

    private static String awaitSnapshot(Process runtime, HttpClient http, URI origin,
                                        String previousHash) throws Exception {
        long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(20);
        String current = "";
        while (System.nanoTime() < deadline) {
            assertTrue(runtime.isAlive(), "runtime exited while waiting for a rule snapshot");
            current = readRules(http, origin);
            String hash = value(current, "source_bytes_sha256");
            if (current.contains("rules_loaded=true") && current.contains("rule_count=1")
                    && (previousHash == null || !hash.equals(previousHash))) return current;
            Thread.sleep(100L);
        }
        throw new AssertionError("runtime did not apply the expected provider snapshot within 20 seconds");
    }

    private static String readRules(HttpClient http, URI origin) throws Exception {
        HttpResponse<String> response = get(http, origin.resolve("/rules"));
        assertEquals(200, response.statusCode(), "runtime rule diagnostic endpoint must be readable");
        return response.body();
    }

    private static List<Integer> requestBurst(HttpClient http, URI origin, int size) throws Exception {
        List<Integer> statuses = new ArrayList<>(size);
        for (int index = 0; index < size; index++) {
            statuses.add(get(http, origin.resolve("/api/hello")).statusCode());
        }
        return statuses;
    }

    private static HttpResponse<String> get(HttpClient http, URI uri) throws IOException, InterruptedException {
        HttpRequest request = HttpRequest.newBuilder(uri).timeout(HTTP_TIMEOUT).GET().build();
        return http.send(request, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
    }

    private static void publish(ConfigService configService, String dataId, String content) throws Exception {
        assertTrue(configService.publishConfig(dataId, GROUP, content),
                "Nacos must accept the test-owned rule snapshot");
    }

    private static String rules(int qps) {
        return "[{\"resource\":\"GET /api/hello\",\"grade\":1,\"count\":" + qps
                + ",\"strategy\":0,\"controlBehavior\":0,\"limitApp\":\"default\"}]";
    }

    private static String invalidRules() {
        return "[{\"resource\":\"GET /api/hello\",\"grade\":1,\"count\":1,"
                + "\"strategy\":0,\"controlBehavior\":0,\"limitApp\":\"default\","
                + "\"unknown_acceptance_field\":true}]";
    }

    private static String value(String snapshot, String key) {
        String prefix = key + "=";
        for (String line : snapshot.split("\\R")) {
            if (line.startsWith(prefix)) return line.substring(prefix.length()).trim();
        }
        throw new AssertionError("runtime snapshot is missing " + key);
    }

    private static DisposableNacos pauseDisposableNacos() throws Exception {
        String containerName = setting("SENTINEL_T004_DISPOSABLE_NACOS_CONTAINER", "").trim();
        String expectedOwner = setting("SENTINEL_T004_DISPOSABLE_NACOS_OWNER", "").trim();
        assertFalse(containerName.isEmpty(), "network outage acceptance needs the exact disposable Nacos name");
        assertFalse(expectedOwner.isEmpty(), "network outage acceptance needs its owner label");
        Process inspect = new ProcessBuilder("docker", "inspect", "--format={{index .Config.Labels \"com.atlas-richie.sentinel-t004.run\"}}", containerName)
                .redirectErrorStream(true).start();
        String owner = new String(inspect.getInputStream().readAllBytes(), StandardCharsets.UTF_8).trim();
        assertTrue(inspect.waitFor(5, TimeUnit.SECONDS), "docker inspect must complete within five seconds");
        assertEquals(0, inspect.exitValue(), "docker inspect must find only the declared disposable Nacos");
        assertEquals(expectedOwner, owner, "refusing to pause a container owned by another test/run");
        runDocker("pause", containerName);
        return new DisposableNacos(containerName);
    }

    private record DisposableNacos(String containerName) {
        private boolean isPaused() throws Exception {
            Process inspect = new ProcessBuilder("docker", "inspect", "--format={{.State.Paused}}", containerName)
                    .redirectErrorStream(true).start();
            String paused = new String(inspect.getInputStream().readAllBytes(), StandardCharsets.UTF_8).trim();
            assertTrue(inspect.waitFor(5, TimeUnit.SECONDS), "Docker paused-state inspection must be bounded");
            assertEquals(0, inspect.exitValue(), "Docker paused-state inspection must succeed");
            return Boolean.parseBoolean(paused);
        }

        private void resume() throws Exception {
            runDocker("unpause", containerName);
        }
    }

    private static void runDocker(String operation, String containerName) throws Exception {
        Process process = new ProcessBuilder("docker", operation, containerName).redirectErrorStream(true).start();
        String output = new String(process.getInputStream().readAllBytes(), StandardCharsets.UTF_8).trim();
        assertTrue(process.waitFor(10, TimeUnit.SECONDS), "docker " + operation + " must complete within ten seconds");
        assertEquals(0, process.exitValue(), "docker " + operation + " failed: " + output);
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
            assertTrue(runtime.waitFor(5, TimeUnit.SECONDS), "runtime child process must terminate");
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

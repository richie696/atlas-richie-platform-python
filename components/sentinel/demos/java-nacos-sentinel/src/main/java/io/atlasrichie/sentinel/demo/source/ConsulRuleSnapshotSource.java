package io.atlasrichie.sentinel.demo.source;

import java.io.InputStream;
import java.net.URI;
import java.net.URLEncoder;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.Arrays;
import java.util.stream.Collectors;

/** Reads one exact Consul KV value using the stable Consul HTTP API. */
final class ConsulRuleSnapshotSource implements RuleSnapshotSource {
    static final int MAX_SNAPSHOT_BYTES = 65_536;
    private static final Duration REQUEST_TIMEOUT = Duration.ofSeconds(5);

    private final HttpClient client;
    private final URI endpoint;
    private final String key;
    private final String datacenter;
    private final String token;

    ConsulRuleSnapshotSource(URI endpoint, String key, String datacenter, String token) {
        this.endpoint = validateEndpoint(endpoint);
        this.key = validateKey(key);
        this.datacenter = datacenter == null ? "" : datacenter;
        this.token = token == null ? "" : token;
        this.client = HttpClient.newBuilder()
                .connectTimeout(REQUEST_TIMEOUT)
                .followRedirects(HttpClient.Redirect.NEVER)
                .build();
    }

    static ConsulRuleSnapshotSource fromEnvironment() {
        String endpoint = required("CONSUL_URL");
        String key = required("CONSUL_KEY");
        return new ConsulRuleSnapshotSource(URI.create(endpoint), key,
                setting("CONSUL_DATACENTER", ""), setting("CONSUL_TOKEN", ""));
    }

    @Override
    public String read() throws Exception {
        URI uri = requestUri(endpoint, key, datacenter);
        HttpRequest.Builder builder = HttpRequest.newBuilder(uri)
                .timeout(REQUEST_TIMEOUT)
                .header("Accept", "application/octet-stream")
                .GET();
        if (!token.isBlank()) builder.header("X-Consul-Token", token);

        try {
            HttpResponse<InputStream> response = client.send(builder.build(), HttpResponse.BodyHandlers.ofInputStream());
            try (InputStream body = response.body()) {
                int status = response.statusCode();
                if (status == 404) throw new RuleSourceReadFailure(RuleSourceReadFailure.Kind.MISSING);
                if (status == 401 || status == 403) throw new RuleSourceReadFailure(RuleSourceReadFailure.Kind.REJECTED);
                if (status != 200) throw new RuleSourceReadFailure(RuleSourceReadFailure.Kind.UNAVAILABLE);
                byte[] bytes = body.readNBytes(MAX_SNAPSHOT_BYTES + 1);
                if (bytes.length > MAX_SNAPSHOT_BYTES) {
                    throw new RuleSourceReadFailure(RuleSourceReadFailure.Kind.UNAVAILABLE);
                }
                return new String(bytes, StandardCharsets.UTF_8);
            }
        } catch (RuleSourceReadFailure failure) {
            throw failure;
        } catch (InterruptedException interrupted) {
            Thread.currentThread().interrupt();
            throw new RuleSourceReadFailure(RuleSourceReadFailure.Kind.UNAVAILABLE);
        } catch (Exception failure) {
            throw new RuleSourceReadFailure(RuleSourceReadFailure.Kind.UNAVAILABLE);
        }
    }

    @Override
    public void close() {
        // JDK HttpClient owns no closeable per-source socket handle.
    }

    private static URI requestUri(URI endpoint, String key, String datacenter) {
        String encodedKey = Arrays.stream(key.split("/", -1))
                .map(ConsulRuleSnapshotSource::encode)
                .collect(Collectors.joining("/"));
        String path = endpoint.toASCIIString().replaceAll("/+$", "") + "/v1/kv/" + encodedKey;
        String query = "raw=true" + (datacenter.isBlank() ? "" : "&dc=" + encode(datacenter));
        return URI.create(path + "?" + query);
    }

    private static URI validateEndpoint(URI endpoint) {
        if (endpoint == null || endpoint.getHost() == null || endpoint.getRawUserInfo() != null
                || endpoint.getRawQuery() != null || endpoint.getRawFragment() != null
                || !("http".equalsIgnoreCase(endpoint.getScheme())
                || "https".equalsIgnoreCase(endpoint.getScheme()))) {
            throw new IllegalArgumentException("Consul endpoint must be an HTTP(S) origin without credentials or query");
        }
        return endpoint;
    }

    private static String validateKey(String key) {
        if (key == null || key.isBlank() || key.length() > 512 || key.startsWith("/") || key.endsWith("/")
                || key.contains("\\") || key.contains("?") || key.contains("#")
                || Arrays.stream(key.split("/", -1)).anyMatch(part -> part.isEmpty() || part.equals(".") || part.equals(".."))) {
            throw new IllegalArgumentException("Consul KV key is invalid");
        }
        return key;
    }

    private static String encode(String value) {
        return URLEncoder.encode(value, StandardCharsets.UTF_8).replace("+", "%20");
    }

    private static String setting(String name, String fallback) {
        String value = System.getenv(name);
        return value == null || value.isBlank() ? fallback : value;
    }

    private static String required(String name) {
        String value = System.getenv(name);
        if (value == null || value.isBlank()) throw new IllegalStateException(name + " is required for Consul");
        return value;
    }
}

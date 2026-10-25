package io.atlasrichie.sentinel.demo.source;

import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.net.InetSocketAddress;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.atomic.AtomicReference;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

final class ConsulRuleSnapshotSourceTest {
    @Test
    void readsExactEncodedKeyWithDatacenterAndAclToken() throws Exception {
        AtomicReference<String> observed = new AtomicReference<>();
        HttpServer server = server(exchange -> {
            observed.set(exchange.getRequestURI().toASCIIString() + "|" + exchange.getRequestHeaders().getFirst("X-Consul-Token"));
            respond(exchange, 200, "[]");
        });
        try {
            ConsulRuleSnapshotSource source = source(server, "sentinel/rules v1.json", "dc-east", "fixture-secret");
            assertEquals("[]", source.read());
            assertEquals("/gateway/v1/kv/sentinel/rules%20v1.json?raw=true&dc=dc-east|fixture-secret", observed.get());
            source.close();
        } finally {
            server.stop(0);
        }
    }

    @Test
    void classifiesProviderFailuresWithoutLeakingResponseOrCredentials() throws Exception {
        for (int[] scenario : new int[][]{{404, 0}, {401, 1}, {403, 1}, {503, 2}}) {
            HttpServer server = server(exchange -> respond(exchange, scenario[0], "secret-response-body"));
            try {
                ConsulRuleSnapshotSource source = source(server, "flow/rules.json", "", "secret-token");
                RuleSourceReadFailure failure = assertThrows(RuleSourceReadFailure.class, source::read);
                RuleSourceReadFailure.Kind expected = switch (scenario[1]) {
                    case 0 -> RuleSourceReadFailure.Kind.MISSING;
                    case 1 -> RuleSourceReadFailure.Kind.REJECTED;
                    default -> RuleSourceReadFailure.Kind.UNAVAILABLE;
                };
                assertEquals(expected, failure.kind());
                assertTrue(!failure.getMessage().contains("secret"));
            } finally {
                server.stop(0);
            }
        }
    }

    @Test
    void rejectsOversizedResponseAsUnavailable() throws Exception {
        HttpServer server = server(exchange -> {
            byte[] body = new byte[ConsulRuleSnapshotSource.MAX_SNAPSHOT_BYTES + 1];
            respond(exchange, 200, body);
        });
        try {
            ConsulRuleSnapshotSource source = source(server, "flow/rules.json", "", "");
            RuleSourceReadFailure failure = assertThrows(RuleSourceReadFailure.class, source::read);
            assertEquals(RuleSourceReadFailure.Kind.UNAVAILABLE, failure.kind());
        } finally {
            server.stop(0);
        }
    }

    @Test
    void rejectsUnsafeEndpointAndKeys() throws Exception {
        assertThrows(IllegalArgumentException.class, () -> new ConsulRuleSnapshotSource(
                URI.create("ftp://consul.local"), "flow/rules.json", "", ""));
        assertThrows(IllegalArgumentException.class, () -> new ConsulRuleSnapshotSource(
                URI.create("http://user:pass@consul.local"), "flow/rules.json", "", ""));
        assertThrows(IllegalArgumentException.class, () -> new ConsulRuleSnapshotSource(
                URI.create("http://consul.local?token=secret"), "flow/rules.json", "", ""));
        for (String key : new String[]{"../flow", "flow//rules", "/flow", "flow/"}) {
            assertThrows(IllegalArgumentException.class, () -> new ConsulRuleSnapshotSource(
                    URI.create("http://consul.local"), key, "", ""));
        }
    }

    private static ConsulRuleSnapshotSource source(HttpServer server, String key, String datacenter, String token) {
        String address = "http://127.0.0.1:" + server.getAddress().getPort() + "/gateway";
        return new ConsulRuleSnapshotSource(URI.create(address), key, datacenter, token);
    }

    private static HttpServer server(com.sun.net.httpserver.HttpHandler handler) throws IOException {
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/gateway/v1/kv/", handler);
        server.start();
        return server;
    }

    private static void respond(com.sun.net.httpserver.HttpExchange exchange, int status, String body) throws IOException {
        respond(exchange, status, body.getBytes(StandardCharsets.UTF_8));
    }

    private static void respond(com.sun.net.httpserver.HttpExchange exchange, int status, byte[] body) throws IOException {
        exchange.sendResponseHeaders(status, body.length);
        try (var output = exchange.getResponseBody()) {
            output.write(body);
        }
    }
}

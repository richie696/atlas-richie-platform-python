package com.atlas_richie.contracts.managedrulev1;

import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import java.io.IOException;
import java.net.InetSocketAddress;
import java.net.URI;
import java.net.URLDecoder;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.Executors;

/** Tiny Java HTTP peer for cross-language transport smoke checks only. */
public final class InteropDemoServer {
    private static final String FIXED_RESPONSE = "atlas-sentinel-interop-ok";
    private static final double MAX_DELAY_SECONDS = 5.0;

    private InteropDemoServer() {}

    public static void main(String[] arguments) throws IOException {
        int port = arguments.length == 0 ? 18762 : Integer.parseInt(arguments[0]);
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", port), 0);
        server.setExecutor(Executors.newCachedThreadPool());
        server.createContext("/demo/fixed", exchange -> respond(exchange, FIXED_RESPONSE, 200));
        server.createContext("/demo/delay", InteropDemoServer::respondAfterDelay);
        server.start();
        Runtime.getRuntime().addShutdownHook(new Thread(() -> server.stop(0)));
    }

    private static void respondAfterDelay(HttpExchange exchange) throws IOException {
        URI uri = exchange.getRequestURI();
        String query = uri.getRawQuery();
        if (query == null || !query.startsWith("seconds=") || query.indexOf('&') >= 0) {
            respond(exchange, "invalid-delay", 400);
            return;
        }
        try {
            String raw = URLDecoder.decode(query.substring("seconds=".length()), StandardCharsets.UTF_8);
            double delay = Double.parseDouble(raw);
            if (!Double.isFinite(delay) || delay < 0 || delay > MAX_DELAY_SECONDS) {
                respond(exchange, "invalid-delay", 400);
                return;
            }
            Thread.sleep((long) (delay * 1_000));
            respond(exchange, FIXED_RESPONSE, 200);
        } catch (IllegalArgumentException exception) {
            respond(exchange, "invalid-delay", 400);
        } catch (InterruptedException exception) {
            Thread.currentThread().interrupt();
            respond(exchange, "interrupted", 503);
        }
    }

    private static void respond(HttpExchange exchange, String value, int status) throws IOException {
        byte[] body = value.getBytes(StandardCharsets.UTF_8);
        exchange.getResponseHeaders().set("Content-Type", "text/plain; charset=utf-8");
        exchange.getResponseHeaders().set("Cache-Control", "no-store");
        exchange.sendResponseHeaders(status, body.length);
        try (var output = exchange.getResponseBody()) {
            output.write(body);
        }
    }
}

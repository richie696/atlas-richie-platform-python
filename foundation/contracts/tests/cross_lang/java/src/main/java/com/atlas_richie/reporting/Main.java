// Hello world web service: Atlas Richie Agent Reporting Protocol V1
// wire compatibility smoke test (Java).
//
// Spins up a minimal HTTP/1.1 server using JDK 21 stdlib only
// (``com.sun.net.httpserver.HttpServer``). No third-party dependencies.
// Validates the two wire marker fields ``protocol_version`` and
// ``event_kind`` from a POST JSON body via stdlib string scanning —
// hello world is wire-format compatibility only; full JSON parsing
// is out of scope (per richie696 2026-09-13 simplification).
package com.atlas_richie.reporting;

import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpHandler;
import com.sun.net.httpserver.HttpServer;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.HashSet;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

public final class Main {

    private static final String PROTOCOL_VERSION = "atlas-richie.reporting/v1";
    private static final Set<String> ALLOWED_EVENT_KINDS = new HashSet<>(Arrays.asList(
        "RULE_SOURCE_ACTIVATED", "RULE_SOURCE_STALE", "RULE_SOURCE_DEGRADED",
        "RULE_APPLIED", "RULE_BLOCKED", "RULE_FAILED"));
    // Stdlib regex scan for top-level "key": "value" pairs. Tolerates
    // arbitrary whitespace; rejects nested object/array values (good
    // enough for hello world).
    private static final Pattern TOP_LEVEL_STRING = Pattern.compile(
        "\"([A-Za-z_][A-Za-z0-9_]*)\"\\s*:\\s*\"([^\"\\\\]*(?:\\\\.[^\"\\\\]*)*)\"");

    private Main() {}

    public static void main(String[] args) throws IOException {
        String addr = "127.0.0.1:18081";
        for (int i = 0; i < args.length - 1; i++) {
            if ("-addr".equals(args[i])) {
                addr = args[i + 1];
            }
        }
        int port = Integer.parseInt(addr.split(":")[1]);
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", port), 0);
        server.createContext("/healthz", new HealthzHandler());
        server.createContext("/report", new ReportHandler());
        server.setExecutor(null);
        System.out.println("cross_lang hello world listening on http://" + addr);
        server.start();
    }

    static final class HealthzHandler implements HttpHandler {
        @Override
        public void handle(HttpExchange ex) throws IOException {
            try {
                if (!"GET".equalsIgnoreCase(ex.getRequestMethod())) {
                    writeError(ex, 405, "METHOD_NOT_ALLOWED", "only GET is accepted on /healthz");
                    return;
                }
                byte[] body = "{\"status\":\"ok\"}".getBytes(StandardCharsets.UTF_8);
                ex.getResponseHeaders().add("Content-Type", "application/json; charset=utf-8");
                ex.sendResponseHeaders(200, body.length);
                try (OutputStream os = ex.getResponseBody()) {
                    os.write(body);
                }
            } finally {
                ex.close();
            }
        }
    }

    static final class ReportHandler implements HttpHandler {
        @Override
        public void handle(HttpExchange ex) throws IOException {
            try {
                if (!"POST".equalsIgnoreCase(ex.getRequestMethod())) {
                    writeError(ex, 405, "METHOD_NOT_ALLOWED",
                        "only POST is accepted on /report");
                    return;
                }
                byte[] body = readAllBytes(ex.getRequestBody());
                String text = new String(body, StandardCharsets.UTF_8);
                if (!text.startsWith("{")) {
                    writeError(ex, 400, "MALFORMED_ENVELOPE",
                        "body must be a JSON object");
                    return;
                }
                String pv = null;
                String ek = null;
                int fields = 0;
                StringBuilder keys = new StringBuilder("[");
                boolean first = true;
                Matcher m = TOP_LEVEL_STRING.matcher(text);
                while (m.find()) {
                    String k = m.group(1);
                    String v = m.group(2);
                    if ("protocol_version".equals(k)) pv = v;
                    else if ("event_kind".equals(k)) ek = v;
                    if (!first) keys.append(",");
                    keys.append("\"").append(k).append("\"");
                    first = false;
                    fields++;
                }
                keys.append("]");
                if (pv == null) {
                    writeError(ex, 400, "PROTOCOL_VERSION_MISMATCH",
                        "protocol_version must be a string");
                    return;
                }
                if (!PROTOCOL_VERSION.equals(pv)) {
                    writeError(ex, 400, "PROTOCOL_VERSION_MISMATCH",
                        "protocol_version must equal \"" + PROTOCOL_VERSION
                            + "\", got \"" + pv + "\"");
                    return;
                }
                if (ek == null) {
                    writeError(ex, 400, "MALFORMED_ENVELOPE",
                        "event_kind must be a string");
                    return;
                }
                if (!ALLOWED_EVENT_KINDS.contains(ek)) {
                    writeError(ex, 400, "UNKNOWN_EVENT_KIND",
                        "event_kind=\"" + ek + "\" not in V1 6 enums");
                    return;
                }
                StringBuilder sb = new StringBuilder(256);
                sb.append("{");
                sb.append("\"status\":\"ok\",");
                sb.append("\"fields_count\":").append(fields).append(",");
                sb.append("\"protocol_version\":\"").append(pv).append("\",");
                sb.append("\"event_kind\":\"").append(ek).append("\",");
                sb.append("\"key_order\":").append(keys);
                sb.append("}");
                byte[] resp = sb.toString().getBytes(StandardCharsets.UTF_8);
                ex.getResponseHeaders().add("Content-Type", "application/json; charset=utf-8");
                ex.sendResponseHeaders(200, resp.length);
                try (OutputStream os = ex.getResponseBody()) {
                    os.write(resp);
                }
            } catch (Exception e) {
                writeError(ex, 500, "INTERNAL_ERROR",
                    e.getClass().getSimpleName() + ": " + e.getMessage());
            } finally {
                ex.close();
            }
        }
    }

    private static void writeError(HttpExchange ex, int status, String code, String msg)
            throws IOException {
        String body = "{"
            + "\"protocol_version\":\"" + PROTOCOL_VERSION + "\","
            + "\"error_code\":\"" + code + "\","
            + "\"message\":\"" + msg.replace("\\", "\\\\").replace("\"", "\\\"") + "\","
            + "\"details\":null"
            + "}";
        byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
        ex.getResponseHeaders().add("Content-Type", "application/json; charset=utf-8");
        ex.sendResponseHeaders(status, bytes.length);
        try (OutputStream os = ex.getResponseBody()) {
            os.write(bytes);
        }
    }

    private static byte[] readAllBytes(InputStream is) throws IOException {
        ByteArrayOutputStream buf = new ByteArrayOutputStream();
        byte[] chunk = new byte[4096];
        int n;
        while ((n = is.read(chunk)) > 0) {
            buf.write(chunk, 0, n);
        }
        return buf.toByteArray();
    }
}

package com.atlas_richie.contracts.managedrulev1;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.TimeUnit;

/** Calls the Python demo peer and verifies fixed, delayed, and timeout paths. */
public final class InteropDemoClient {
    private static final String EXPECTED = "atlas-sentinel-interop-ok";

    private InteropDemoClient() {}

    public static void main(String[] arguments) throws Exception {
        String baseUrl = arguments.length == 0 ? "http://127.0.0.1:18761" : arguments[0];
        HttpClient client = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(2)).build();
        assertBody(client, baseUrl + "/demo/fixed", Duration.ofSeconds(2));
        long start = System.nanoTime();
        assertBody(client, baseUrl + "/demo/delay?seconds=0.2", Duration.ofSeconds(2));
        long elapsedMillis = TimeUnit.NANOSECONDS.toMillis(System.nanoTime() - start);
        if (elapsedMillis < 150) {
            throw new AssertionError("Python delay endpoint returned too early");
        }
        try {
            assertBody(client, baseUrl + "/demo/delay?seconds=0.4", Duration.ofMillis(50));
            throw new AssertionError("Python delay endpoint did not trigger client timeout");
        } catch (java.net.http.HttpTimeoutException expectedTimeout) {
            // Expected: only the caller times out; the server keeps serving requests.
        }
        assertBody(client, baseUrl + "/demo/fixed", Duration.ofSeconds(2));
        System.out.println("Java -> Python demo passed: fixed, delayed, timeout, recovery");
    }

    private static void assertBody(HttpClient client, String url, Duration timeout) throws Exception {
        HttpRequest request = HttpRequest.newBuilder(URI.create(url)).timeout(timeout).GET().build();
        HttpResponse<String> response = client.send(request, HttpResponse.BodyHandlers.ofString());
        if (response.statusCode() != 200 || !EXPECTED.equals(response.body())) {
            throw new AssertionError("Python demo response did not match the fixed contract");
        }
    }
}

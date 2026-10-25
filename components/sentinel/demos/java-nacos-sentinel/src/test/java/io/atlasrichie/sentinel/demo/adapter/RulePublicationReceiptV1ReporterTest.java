package io.atlasrichie.sentinel.demo.adapter;

import com.fasterxml.jackson.databind.ObjectMapper;
import io.atlasrichie.sentinel.demo.adapter.SentinelFlowRuleAdapter.AppliedSnapshot;
import io.atlasrichie.sentinel.demo.adapter.SentinelFlowRuleAdapter.ManagedPublicationProvenance;
import org.junit.jupiter.api.Test;

import javax.net.ssl.SSLContext;
import java.lang.reflect.Field;
import java.net.URI;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Executors;
import java.util.concurrent.ArrayBlockingQueue;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

class RulePublicationReceiptV1ReporterTest {
    @Test
    void retriesTheSameReceiptUntilCollectorReturnsDurableAck() throws Exception {
        var attempts = new AtomicInteger();
        var bodies = new ArrayList<byte[]>();
        var reporter = new RulePublicationReceiptV1Reporter(
                "f1a4d8b2-9a26-4c5d-a8b7-12e7a5c7d3a1",
                URI.create("https://127.0.0.1:8443"),
                (endpoint, body) -> {
                    assertEquals(URI.create("https://127.0.0.1:8443/api/reporting/v1/rule-publication-receipts"), endpoint);
                    bodies.add(body.clone());
                    return attempts.incrementAndGet() == 1 ? 503 : 204;
                });
        var snapshot = new AppliedSnapshot(0, "b".repeat(64), "c".repeat(64), List.of(),
                new ManagedPublicationProvenance("binding-01", "publication-42", "version-42", 42,
                        "a".repeat(64), "[]"));
        try {
            assertTrue(reporter.applied(snapshot));

            reporter.sendNext();
            assertEquals(1, attempts.get(), "503 must leave the exact receipt pending");
            reporter.sendNext();
            reporter.sendNext();

            assertEquals(2, attempts.get(), "204 must remove the receipt from the queue");
            assertEquals(2, bodies.size());
            assertTrue(Arrays.equals(bodies.get(0), bodies.get(1)), "retry bytes must be identical");
        } finally {
            reporter.close();
        }
    }

    @Test
    void queuesExactManagedTupleAndReportsQueuePressureWithoutBlocking() throws Exception {
        var reporter = new RulePublicationReceiptV1Reporter(
                "f1a4d8b2-9a26-4c5d-a8b7-12e7a5c7d3a1", URI.create("https://127.0.0.1:8443"),
                SSLContext.getDefault());
        try {
            Field field = RulePublicationReceiptV1Reporter.class.getDeclaredField("queue");
            field.setAccessible(true);
            @SuppressWarnings("unchecked")
            ArrayBlockingQueue<byte[]> queue = (ArrayBlockingQueue<byte[]>) field.get(reporter);
            AppliedSnapshot snapshot = new AppliedSnapshot(0, "b".repeat(64), "c".repeat(64), List.of(),
                    new ManagedPublicationProvenance("binding-01", "publication-42", "version-42", 42,
                            "a".repeat(64), "[]"));

            assertTrue(reporter.applied(snapshot));
            var receipt = new ObjectMapper().readTree(queue.peek());
            assertEquals("atlas-richie.sentinel.rule-publication-receipt/v1", receipt.path("protocol_version").asText());
            assertNotNull(receipt.path("receipt_id").textValue());
            assertEquals("f1a4d8b2-9a26-4c5d-a8b7-12e7a5c7d3a1", receipt.path("process_epoch").asText());
            assertEquals(1, receipt.path("sequence").asLong());
            assertEquals("binding-01", receipt.path("binding_id").asText());
            assertEquals("publication-42", receipt.path("publication_id").asText());
            assertEquals("version-42", receipt.path("target_version_id").asText());
            assertEquals("a".repeat(64), receipt.path("target_payload_sha256").asText());
            assertEquals("applied", receipt.path("state").asText());
            assertTrue(receipt.path("reason").isNull());
            assertTrue(receipt.path("source_revision").isNull());
            assertTrue(receipt.path("observed_at").asText().matches(
                    "^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\\.[0-9]{3}Z$"));

            for (int index = 0; index < 127; index++) assertTrue(reporter.applied(snapshot));
            assertFalse(reporter.applied(snapshot));
        } finally {
            reporter.close();
        }
    }

    @Test
    void concurrentAdmissionsKeepReceiptSequenceAndQueueOrderAligned() throws Exception {
        var reporter = new RulePublicationReceiptV1Reporter(
                "f1a4d8b2-9a26-4c5d-a8b7-12e7a5c7d3a1", URI.create("https://127.0.0.1:8443"),
                SSLContext.getDefault());
        try {
            Field field = RulePublicationReceiptV1Reporter.class.getDeclaredField("queue");
            field.setAccessible(true);
            @SuppressWarnings("unchecked")
            ArrayBlockingQueue<byte[]> queue = (ArrayBlockingQueue<byte[]>) field.get(reporter);
            AppliedSnapshot snapshot = new AppliedSnapshot(0, "b".repeat(64), "c".repeat(64), List.of(),
                    new ManagedPublicationProvenance("binding-01", "publication-42", "version-42", 42,
                            "a".repeat(64), "[]"));
            int count = 64;
            var ready = new CountDownLatch(count);
            var start = new CountDownLatch(1);
            var executor = Executors.newFixedThreadPool(count);
            try {
                for (int index = 0; index < count; index++) {
                    executor.submit(() -> {
                        ready.countDown();
                        start.await();
                        assertTrue(reporter.applied(snapshot));
                        return null;
                    });
                }
                ready.await();
                start.countDown();
            } finally {
                executor.shutdown();
                assertTrue(executor.awaitTermination(5, java.util.concurrent.TimeUnit.SECONDS));
            }
            var mapper = new ObjectMapper();
            for (int expected = 1; expected <= count; expected++) {
                assertEquals(expected, mapper.readTree(queue.remove()).path("sequence").asInt());
            }
        } finally {
            reporter.close();
        }
    }
}

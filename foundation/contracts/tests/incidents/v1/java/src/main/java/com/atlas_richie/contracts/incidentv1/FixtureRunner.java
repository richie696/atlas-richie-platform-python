package com.atlas_richie.contracts.incidentv1;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;

/** Runs the same positive and negative event/receipt fixtures as Python and Go. */
public final class FixtureRunner {

    private FixtureRunner() {}

    public static void main(String[] args) throws IOException {
        if (args.length != 1) throw new IllegalArgumentException("expected fixture directory");
        Path fixtures = Path.of(args[0]);
        int validEvents = 0;
        int invalidEvents = 0;
        try (var paths = Files.list(fixtures)) {
            for (Path path : paths.filter(item -> item.toString().endsWith(".json")).sorted().toList()) {
                String name = path.getFileName().toString();
                byte[] payload = Files.readAllBytes(path);
                boolean valid = name.equals("resource-pressure.json") || name.equals("response-time.json") || name.equals("response-time-max-safe.json");
                boolean invalid = name.startsWith("invalid-");
                if (!valid && !invalid) throw new AssertionError("unclassified event fixture: " + name);
                try {
                    IncidentV1Validator.validateEvent(payload);
                    if (!valid) throw new AssertionError("invalid event accepted: " + name);
                    validEvents++;
                } catch (IllegalArgumentException error) {
                    if (valid) throw new AssertionError("valid event rejected: " + name, error);
                    invalidEvents++;
                }
            }
        }
        if (validEvents != 3 || invalidEvents == 0) throw new AssertionError("event fixture coverage incomplete");

        int validReceipts = 0;
        int invalidReceipts = 0;
        Path receipts = fixtures.resolve("receipts");
        try (var paths = Files.list(receipts)) {
            List<Path> receiptPaths = paths.filter(item -> item.toString().endsWith(".json")).sorted().toList();
            for (Path path : receiptPaths) {
                String name = path.getFileName().toString();
                byte[] payload = Files.readAllBytes(path);
                boolean valid = name.equals("valid.json");
                boolean invalid = name.startsWith("invalid-");
                if (!valid && !invalid) throw new AssertionError("unclassified receipt fixture: " + name);
                try {
                    IncidentV1Validator.validateReceipt(payload);
                    if (!valid) throw new AssertionError("invalid receipt accepted: " + name);
                    validReceipts++;
                } catch (IllegalArgumentException error) {
                    if (valid) throw new AssertionError("valid receipt rejected: " + name, error);
                    invalidReceipts++;
                }
            }
        }
        if (validReceipts != 1 || invalidReceipts == 0) throw new AssertionError("receipt fixture coverage incomplete");
        System.out.printf("Java Incident V1 conformance: %d valid events, %d invalid events, %d valid receipts, %d invalid receipts%n",
            validEvents, invalidEvents, validReceipts, invalidReceipts);
    }
}

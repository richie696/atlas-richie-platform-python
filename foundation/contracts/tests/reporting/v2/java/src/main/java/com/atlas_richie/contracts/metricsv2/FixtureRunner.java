package com.atlas_richie.contracts.metricsv2;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;

/** Runs the shared positive and negative fixture set without adding a test framework. */
public final class FixtureRunner {

    private FixtureRunner() {}

    public static void main(String[] args) throws IOException {
        if (args.length != 1) throw new IllegalArgumentException("expected fixture directory");
        Path fixtureDirectory = Path.of(args[0]);
        int accepted = 0;
        int rejected = 0;
        try (var files = Files.list(fixtureDirectory)) {
            for (Path path : files.filter(item -> item.toString().endsWith(".json")).sorted().toList()) {
                byte[] payload = Files.readAllBytes(path);
                String fixtureName = path.getFileName().toString();
                boolean valid = fixtureName.startsWith("valid_");
                boolean invalid = fixtureName.startsWith("invalid_");
                if (!valid && !invalid) throw new AssertionError("fixture lacks classification: " + fixtureName);
                try {
                    MetricsV2Validator.validate(payload);
                    if (!valid) throw new AssertionError("invalid fixture accepted: " + fixtureName);
                    accepted++;
                } catch (IllegalArgumentException error) {
                    if (valid) throw new AssertionError("valid fixture rejected: " + fixtureName, error);
                    rejected++;
                }
            }
        }
        if (accepted == 0 || rejected == 0) throw new AssertionError("fixture coverage incomplete");
        System.out.printf("Java Metrics V2 conformance: %d valid accepted, %d invalid rejected%n", accepted, rejected);

        Path receiptDirectory = fixtureDirectory.resolve("receipts");
        int validReceipts = 0;
        int invalidReceipts = 0;
        try (var files = Files.list(receiptDirectory)) {
            for (Path path : files.filter(item -> item.toString().endsWith(".json")).sorted().toList()) {
                byte[] payload = Files.readAllBytes(path);
                String fixtureName = path.getFileName().toString();
                boolean valid = fixtureName.startsWith("valid_");
                boolean invalid = fixtureName.startsWith("invalid_");
                if (!valid && !invalid) throw new AssertionError("receipt fixture lacks classification: " + fixtureName);
                try {
                    MetricsV2Validator.validateReceipt(payload);
                    if (!valid) throw new AssertionError("invalid receipt accepted: " + fixtureName);
                    validReceipts++;
                } catch (IllegalArgumentException error) {
                    if (valid) throw new AssertionError("valid receipt rejected: " + fixtureName, error);
                    invalidReceipts++;
                }
            }
        }
        if (validReceipts == 0 || invalidReceipts == 0) throw new AssertionError("receipt fixture coverage incomplete");
        System.out.printf("Java Metrics V2 receipts: %d valid accepted, %d invalid rejected%n", validReceipts, invalidReceipts);
    }
}

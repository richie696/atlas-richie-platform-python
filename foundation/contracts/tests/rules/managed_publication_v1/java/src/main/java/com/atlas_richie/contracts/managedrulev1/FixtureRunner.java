package com.atlas_richie.contracts.managedrulev1;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.util.HexFormat;

/** Runs Java against the shared draft envelope fixtures used by Python. */
public final class FixtureRunner {

    private FixtureRunner() {}

    public static void main(String[] args) throws IOException {
        if (args.length != 1) throw new IllegalArgumentException("expected fixture directory");
        Path fixtures = Path.of(args[0]);
        int accepted = 0;
        int rejected = 0;
        try (var paths = Files.list(fixtures)) {
            for (Path path : paths.filter(item -> item.toString().endsWith(".json")).sorted().toList()) {
                String name = path.getFileName().toString();
                boolean valid = name.startsWith("valid_");
                boolean invalid = name.startsWith("invalid_");
                if (!valid && !invalid) throw new AssertionError("unclassified fixture: " + name);
                try {
                    byte[] inner = ManagedRuleEnvelopeValidator.validateAndExtract(Files.readAllBytes(path));
                    String digest = HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(inner));
                    if (!valid) throw new AssertionError("invalid fixture accepted: " + name);
                    if (name.equals("valid_empty_rules.json") && !digest.equals("4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945")) {
                        throw new AssertionError("empty payload digest vector mismatch");
                    }
                    if (name.equals("valid_utf8_rules.json") && !digest.equals("56bcfa001340bd02000b96afc9108918f4173531881bc5e2c23a8a7784c19943")) {
                        throw new AssertionError("UTF-8 payload digest vector mismatch");
                    }
                    accepted++;
                } catch (IllegalArgumentException error) {
                    if (valid) throw new AssertionError("valid fixture rejected: " + name, error);
                    rejected++;
                } catch (java.security.NoSuchAlgorithmException error) {
                    throw new IllegalStateException("SHA-256 is unavailable", error);
                }
            }
        }
        if (accepted != 2 || rejected < 1) throw new AssertionError("fixture coverage incomplete");
        System.out.printf("Java managed-envelope draft conformance: %d valid accepted, %d invalid rejected%n", accepted, rejected);
    }
}

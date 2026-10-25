package com.atlas_richie.contracts.ruleloadv1;

import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

final class RuleLoadObservationV1FixtureTest {

    @Test
    void validatesEverySharedFixture() throws IOException {
        Path fixtures = Path.of(System.getProperty("fixture.dir", "../fixtures"));
        List<Path> paths;
        try (var files = Files.list(fixtures)) {
            paths = files.filter(path -> path.toString().endsWith(".json")).sorted().toList();
        }
        long valid = 0;
        long invalid = 0;
        for (Path path : paths) {
            String name = path.getFileName().toString();
            byte[] payload = Files.readAllBytes(path);
            if (name.startsWith("valid_")) {
                assertDoesNotThrow(() -> RuleLoadObservationV1Validator.validate(payload), name);
                valid++;
            } else if (name.startsWith("invalid_")) {
                assertThrows(IllegalArgumentException.class, () -> RuleLoadObservationV1Validator.validate(payload), name);
                invalid++;
            } else {
                throw new AssertionError("unclassified fixture: " + name);
            }
        }
        assertTrue(valid >= 3 && invalid >= 8, "fixture corpus unexpectedly incomplete");
    }

    @Test
    void rejectsTrailingJsonAndPayloadOverflow() {
        assertThrows(IllegalArgumentException.class, () -> RuleLoadObservationV1Validator.validate("{} {}".getBytes()));
        assertThrows(IllegalArgumentException.class, () -> RuleLoadObservationV1Validator.validate(new byte[512 * 1024 + 1]));
    }
}

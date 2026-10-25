package io.atlasrichie.sentinel.demo.adapter;

import com.alibaba.csp.sentinel.slots.block.flow.FlowRuleManager;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import com.fasterxml.jackson.databind.ObjectMapper;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.util.HexFormat;
import java.util.Map;
import java.util.stream.Stream;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class SentinelFlowRuleAdapterTest {
    @AfterEach
    void clearSdkRules() {
        FlowRuleManager.loadRules(java.util.List.of());
    }

    @Test
    void appliesOnlyAValidatedFlowSnapshotToTheOfficialManager() throws Exception {
        var vector = new ObjectMapper().readTree(Files.readString(Path.of(
                "../../../../foundation/contracts/tests/cross_lang/rule_profile_v1/fixtures/equivalent_flow_snapshots.json")));
        var snapshot = SentinelFlowRuleAdapter.apply(vector.path("javaSnapshot").asText());

        assertEquals(1, snapshot.ruleCount());
        assertTrue(snapshot.sourceBytesSha256().matches("[0-9a-f]{64}"));
        assertEquals(vector.path("canonicalRulesSha256").asText(), snapshot.canonicalRulesSha256());
        assertEquals(vector.path("memberFingerprint").asText(), snapshot.memberFingerprints().get(0));
        assertEquals(1, FlowRuleManager.getRules().size());
        assertEquals("GET /api/hello", FlowRuleManager.getRules().get(0).getResource());
    }

    @Test
    void rejectsUnknownFieldsWithoutReplacingLastKnownGoodRules() throws Exception {
        SentinelFlowRuleAdapter.apply(
                "[{\"resource\":\"GET /api/hello\",\"grade\":1,\"count\":3}]"
        );
        var activeRules = FlowRuleManager.getRules();

        assertThrows(IOException.class, () -> SentinelFlowRuleAdapter.apply(
                "[{\"resource\":\"GET /api/hello\",\"grade\":1,\"count\":1,\"mystery\":true}]"
        ));

        assertEquals(activeRules, FlowRuleManager.getRules());
        assertEquals(3.0, FlowRuleManager.getRules().get(0).getCount());
    }

    @Test
    void rejectsDuplicateJsonKeysAndUnsupportedClusterMode() {
        assertThrows(IOException.class, () -> SentinelFlowRuleAdapter.apply(
                "[{\"resource\":\"a\",\"resource\":\"b\",\"count\":1}]"
        ));
        assertThrows(IOException.class, () -> SentinelFlowRuleAdapter.apply(
                "[{\"resource\":\"a\",\"grade\":1,\"count\":1,\"clusterMode\":true}]"
        ));
    }

    @Test
    void rejectsKnownButUnmodeledFlowFieldsWithoutReplacingLastKnownGoodRules() throws Exception {
        SentinelFlowRuleAdapter.apply(
                "[{\"resource\":\"GET /api/hello\",\"grade\":1,\"count\":3}]"
        );
        var activeRules = FlowRuleManager.getRules();

        assertThrows(IOException.class, () -> SentinelFlowRuleAdapter.apply(
                "[{\"resource\":\"GET /api/hello\",\"grade\":1,\"count\":1,"
                        + "\"warmUpColdFactor\":3}]"
        ));

        assertEquals(activeRules, FlowRuleManager.getRules());
        assertEquals(3.0, FlowRuleManager.getRules().get(0).getCount());
    }

    @Test
    void acceptsAnEmptySnapshotAndClearsTheOfficialRuleManager() throws Exception {
        SentinelFlowRuleAdapter.apply(
                "[{\"resource\":\"GET /api/hello\",\"grade\":1,\"count\":3}]"
        );

        var empty = SentinelFlowRuleAdapter.apply("[]");

        assertEquals(0, empty.ruleCount());
        assertTrue(FlowRuleManager.getRules().isEmpty());
        assertNotEquals("", empty.sourceBytesSha256());
    }

    @Test
    void decodesSharedManagedEnvelopeFixturesAndAppliesExactUtf8Payload() throws Exception {
        Path fixtureDirectory = Path.of("../../../../foundation/contracts/tests/rules/managed_publication_v1/fixtures");
        var empty = ManagedRuleEnvelopeV1Decoder.decode(
                Files.readString(fixtureDirectory.resolve("valid_empty_rules.json")),
                "binding-01", "sentinel-nacos-flow-v1");
        assertEquals(42, empty.publicationSequence());
        assertEquals("publication-42", empty.publicationId());
        assertEquals("[]", empty.rulePayload());
        SentinelFlowRuleAdapter.apply(empty.rulePayload());
        assertTrue(FlowRuleManager.getRules().isEmpty());

        var utf8 = ManagedRuleEnvelopeV1Decoder.decode(
                Files.readString(fixtureDirectory.resolve("valid_utf8_rules.json")),
                "binding-02", "sentinel-nacos-flow-v1");
        assertEquals("[{\"resource\":\"订单\",\"grade\":1,\"count\":10}]", utf8.rulePayload());
        SentinelFlowRuleAdapter.apply(utf8.rulePayload());
        assertEquals("订单", FlowRuleManager.getRules().get(0).getResource());
    }

    @Test
    void rejectsEveryInvalidSharedManagedEnvelopeFixture() throws Exception {
        Path fixtureDirectory = Path.of("../../../../foundation/contracts/tests/rules/managed_publication_v1/fixtures");
        try (Stream<Path> fixtures = Files.list(fixtureDirectory)) {
            for (Path fixture : fixtures.filter(path -> path.getFileName().toString().startsWith("invalid_")).toList()) {
                assertThrows(IOException.class, () -> ManagedRuleEnvelopeV1Decoder.decode(
                        Files.readString(fixture), "binding-01", "sentinel-nacos-flow-v1"),
                        fixture.getFileName().toString());
            }
        }
    }

    @Test
    void managedApplyRetainsRulesAndProvenanceWhenSequenceOrPayloadIsRejected() throws Exception {
        String payload = "[{\"resource\":\"GET /api/hello\",\"grade\":1,\"count\":3}]";
        var initial = SentinelFlowRuleAdapter.applyManaged(
                managedEnvelope("publication-2", 2, payload), "binding-01", "sentinel-java-v1", null);
        assertEquals("publication-2", initial.managedPublication().publicationId());
        assertNotEquals(initial.sourceBytesSha256(), initial.managedPublication().payloadSha256());

        var replay = SentinelFlowRuleAdapter.applyManaged(
                managedEnvelope("publication-2", 2, payload), "binding-01", "sentinel-java-v1", initial);
        assertEquals(initial, replay);
        assertThrows(IOException.class, () -> SentinelFlowRuleAdapter.applyManaged(
                managedEnvelope("publication-1", 1, payload), "binding-01", "sentinel-java-v1", initial));
        assertThrows(IOException.class, () -> SentinelFlowRuleAdapter.applyManaged(
                managedEnvelope("publication-conflict", 2, payload), "binding-01", "sentinel-java-v1", initial));
        assertThrows(IOException.class, () -> SentinelFlowRuleAdapter.applyManaged(
                managedEnvelope("publication-2", 3, payload), "binding-01", "sentinel-java-v1", initial));
        assertThrows(IOException.class, () -> SentinelFlowRuleAdapter.applyManaged(
                managedEnvelope("publication-3", 3,
                        "[{\"resource\":\"GET /api/hello\",\"grade\":1,\"count\":0}]"),
                "binding-01", "sentinel-java-v1", initial));

        assertEquals("publication-2", initial.managedPublication().publicationId());
        assertEquals(3.0, FlowRuleManager.getRules().get(0).getCount());
    }

    private static String managedEnvelope(String publicationId, long sequence, String payload) throws Exception {
        String digest = HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256")
                .digest(payload.getBytes(StandardCharsets.UTF_8)));
        return new ObjectMapper().writeValueAsString(Map.of(
                "protocol_version", ManagedRuleEnvelopeV1Decoder.PROTOCOL,
                "binding_id", "binding-01",
                "publication_id", publicationId,
                "target_version_id", publicationId + "-version",
                "publication_sequence", sequence,
                "rule_kind", "flow",
                "profile_id", "sentinel-java-v1",
                "payload_sha256", digest,
                "rule_payload", payload));
    }
}

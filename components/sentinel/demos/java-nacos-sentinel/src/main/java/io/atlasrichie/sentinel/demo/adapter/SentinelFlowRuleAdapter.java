package io.atlasrichie.sentinel.demo.adapter;

import com.alibaba.csp.sentinel.slots.block.flow.FlowRule;
import com.alibaba.csp.sentinel.slots.block.flow.FlowRuleManager;
import com.fasterxml.jackson.core.JsonParser;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

import java.io.IOException;
import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashSet;
import java.util.HexFormat;
import java.util.List;
import java.util.Set;

/** Applies only the explicitly supported Sentinel Java flow-rule profile. */
public final class SentinelFlowRuleAdapter {
    private static final int MAX_RULES_BYTES = 65_536;
    private static final BigDecimal MAX_THRESHOLD = new BigDecimal("1000000000");
    private static final Set<String> SUPPORTED_FIELDS = Set.of(
            "resource", "grade", "count", "strategy", "controlBehavior", "limitApp",
            "warmUpPeriodSec", "maxQueueingTimeMs", "clusterMode", "refResource");
    private static final ObjectMapper JSON = new ObjectMapper()
            .enable(JsonParser.Feature.STRICT_DUPLICATE_DETECTION)
            .enable(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES);

    private SentinelFlowRuleAdapter() { }

    /**
     * Strictly decode and validate a complete Nacos snapshot before atomically
     * replacing the official Sentinel rule manager. Empty arrays are valid and
     * intentionally clear this binding's active rule set.
     */
    public static AppliedSnapshot apply(String sourceContent) throws IOException {
        if (sourceContent == null || sourceContent.getBytes(StandardCharsets.UTF_8).length > MAX_RULES_BYTES) {
            throw new IOException("rule snapshot is absent or exceeds its bound");
        }
        JsonNode decoded = JSON.readTree(sourceContent);
        if (decoded == null || !decoded.isArray()) {
            throw new IOException("rule snapshot must be a JSON array");
        }
        List<String> memberFingerprints = new ArrayList<>();
        List<FlowRule> rules = new ArrayList<>();
        Set<String> resources = new HashSet<>();
        for (JsonNode candidate : decoded) {
            if (!candidate.isObject()) throw new IOException("rule item must be an object");
            var fieldNames = candidate.fieldNames();
            while (fieldNames.hasNext()) {
                String fieldName = fieldNames.next();
                if (!SUPPORTED_FIELDS.contains(fieldName)) {
                    throw new IOException("rule snapshot contains unsupported flow field: " + fieldName);
                }
            }
            if (!candidate.path("resource").isTextual()
                    || !candidate.path("grade").canConvertToInt()
                    || !candidate.path("count").isNumber()
                    || !optionalInteger(candidate, "strategy", 0)
                    || !optionalInteger(candidate, "controlBehavior", 0)
                    || !optionalInteger(candidate, "warmUpPeriodSec", 0)
                    || !optionalInteger(candidate, "maxQueueingTimeMs", 0)
                    || !optionalBoolean(candidate, "clusterMode", false)
                    || !optionalText(candidate, "refResource", "")) {
                throw new IOException("rule snapshot contains invalid field types");
            }
            String resource = candidate.path("resource").textValue();
            String rawThreshold = candidate.path("count").asText();
            BigDecimal threshold = candidate.path("count").decimalValue().stripTrailingZeros();
            if (resource.isBlank() || !resource.equals(resource.trim())
                    || resource.getBytes(StandardCharsets.UTF_8).length > 200
                    || hasUnpairedSurrogate(resource) || !resources.add(resource)
                    || candidate.path("grade").intValue() != 1
                    || !rawThreshold.matches("^(?:0|[1-9][0-9]*)(?:\\.[0-9]+)?$")
                    || !threshold.toPlainString().matches("^(?:0|[1-9][0-9]*)(?:\\.[0-9]{1,6})?$")
                    || threshold.signum() <= 0 || threshold.compareTo(MAX_THRESHOLD) > 0
                    || !optionalDefaultApplication(candidate)) {
                throw new IOException("rule snapshot exceeds sentinel-java-v1 flow semantics");
            }
            memberFingerprints.add(sha256(canonicalMember(resource, threshold.toPlainString())
                    .getBytes(StandardCharsets.UTF_8)));
            FlowRule rule = new FlowRule(resource)
                    .setGrade(1)
                    .setCount(threshold.doubleValue())
                    .setStrategy(0)
                    .setControlBehavior(0)
                    .setWarmUpPeriodSec(0)
                    .setMaxQueueingTimeMs(0);
            rule.setLimitApp("default");
            rules.add(rule);
        }

        String sourceDigest = sha256(sourceContent.getBytes(StandardCharsets.UTF_8));
        memberFingerprints.sort(Comparator.naturalOrder());
        String canonicalSnapshot = "sentinel-flow-snapshot-v1\n"
                + String.join("\n", memberFingerprints) + (memberFingerprints.isEmpty() ? "" : "\n");
        String canonicalDigest = sha256(canonicalSnapshot.getBytes(StandardCharsets.UTF_8));
        FlowRuleManager.loadRules(rules);
        return new AppliedSnapshot(rules.size(), sourceDigest, canonicalDigest,
                List.copyOf(memberFingerprints), null);
    }

    /** Apply an explicitly configured managed envelope after validating the binding and sequence. */
    public static AppliedSnapshot applyManaged(String sourceContent, String bindingId,
                                               String profileId, AppliedSnapshot current) throws IOException {
        ManagedRuleEnvelopeV1Decoder.Envelope envelope = ManagedRuleEnvelopeV1Decoder.decode(
                sourceContent, bindingId, profileId);
        ManagedPublicationProvenance previous = current == null ? null : current.managedPublication();
        if (previous != null) {
            if (envelope.publicationSequence() > previous.publicationSequence()
                    && envelope.publicationId().equals(previous.publicationId())) {
                throw new IOException("managed publication id cannot be reused");
            }
            if (envelope.publicationSequence() < previous.publicationSequence()) {
                throw new IOException("managed publication sequence is stale");
            }
            if (envelope.publicationSequence() == previous.publicationSequence()) {
                if (envelope.bindingId().equals(previous.bindingId())
                        && envelope.publicationId().equals(previous.publicationId())
                        && envelope.targetVersionId().equals(previous.targetVersionId())
                        && envelope.payloadSha256().equals(previous.payloadSha256())
                        && envelope.rulePayload().equals(previous.rulePayload())) return current;
                throw new IOException("managed publication sequence conflicts");
            }
        }
        AppliedSnapshot nativeSnapshot = apply(envelope.rulePayload());
        return new AppliedSnapshot(nativeSnapshot.ruleCount(), sha256(sourceContent.getBytes(StandardCharsets.UTF_8)),
                nativeSnapshot.canonicalRulesSha256(), nativeSnapshot.memberFingerprints(),
                new ManagedPublicationProvenance(envelope.bindingId(), envelope.publicationId(),
                        envelope.targetVersionId(), envelope.publicationSequence(),
                        envelope.payloadSha256(), envelope.rulePayload()));
    }

    private static boolean optionalInteger(JsonNode object, String field, int defaultValue) {
        JsonNode value = object.get(field);
        return value == null || (value.canConvertToInt() && value.intValue() == defaultValue);
    }

    private static boolean optionalBoolean(JsonNode object, String field, boolean defaultValue) {
        JsonNode value = object.get(field);
        return value == null || (value.isBoolean() && value.booleanValue() == defaultValue);
    }

    private static boolean optionalText(JsonNode object, String field, String defaultValue) {
        JsonNode value = object.get(field);
        return value == null || value.isNull()
                || (value.isTextual() && defaultValue.equals(value.textValue()));
    }

    private static boolean optionalDefaultApplication(JsonNode object) {
        JsonNode value = object.get("limitApp");
        return value == null || (value.isTextual() && "default".equals(value.textValue()));
    }

    private static boolean hasUnpairedSurrogate(String value) {
        for (int index = 0; index < value.length(); index++) {
            char character = value.charAt(index);
            if (Character.isHighSurrogate(character)) {
                if (index + 1 >= value.length() || !Character.isLowSurrogate(value.charAt(++index))) return true;
            } else if (Character.isLowSurrogate(character)) {
                return true;
            }
        }
        return false;
    }

    private static String canonicalMember(String resource, String threshold) {
        int resourceLength = resource.getBytes(StandardCharsets.UTF_8).length;
        return "sentinel-flow-member-v1\n" + resourceLength + ":" + resource + "\n"
                + threshold.length() + ":" + threshold + "\n";
    }

    private static String sha256(byte[] bytes) {
        try {
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes));
        } catch (NoSuchAlgorithmException impossible) {
            throw new IllegalStateException("SHA-256 is unavailable", impossible);
        }
    }

    /** Safe, non-secret facts about the snapshot that the SDK accepted. */
    public record AppliedSnapshot(int ruleCount, String sourceBytesSha256,
                                  String canonicalRulesSha256,
                                  List<String> memberFingerprints,
                                  ManagedPublicationProvenance managedPublication) { }

    /** Exact managed publication identity retained alongside applied rules. */
    public record ManagedPublicationProvenance(String bindingId, String publicationId,
                                               String targetVersionId, long publicationSequence,
                                               String payloadSha256, String rulePayload) { }
}

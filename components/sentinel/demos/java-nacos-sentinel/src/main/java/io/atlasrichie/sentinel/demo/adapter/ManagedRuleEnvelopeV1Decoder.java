package io.atlasrichie.sentinel.demo.adapter;

import com.fasterxml.jackson.core.JsonParser;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

import java.io.IOException;
import java.math.BigInteger;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HashSet;
import java.util.Set;
import java.util.regex.Pattern;

/** Strict opt-in decoder for Managed Rule Publication Envelope V1. */
public final class ManagedRuleEnvelopeV1Decoder {
    public static final String PROTOCOL = "atlas-richie.sentinel.managed-rule-publication/v1";
    private static final int MAX_ENVELOPE_BYTES = 512 * 1024;
    private static final int MAX_PAYLOAD_BYTES = 500 * 1024;
    private static final BigInteger MAX_SEQUENCE = new BigInteger("9007199254740991");
    private static final Pattern IDENTIFIER = Pattern.compile("[A-Za-z0-9][A-Za-z0-9._:-]{0,199}");
    private static final Pattern DIGEST = Pattern.compile("[0-9a-f]{64}");
    private static final Set<String> FIELDS = Set.of("protocol_version", "binding_id", "publication_id",
            "target_version_id", "publication_sequence", "rule_kind", "profile_id",
            "payload_sha256", "rule_payload");
    private static final ObjectMapper JSON = new ObjectMapper()
            .enable(JsonParser.Feature.STRICT_DUPLICATE_DETECTION)
            .enable(DeserializationFeature.FAIL_ON_TRAILING_TOKENS);

    private ManagedRuleEnvelopeV1Decoder() { }

    /** Validate a managed envelope and preserve the exact inner payload text. */
    public static Envelope decode(String content, String expectedBindingId, String expectedProfileId)
            throws IOException {
        if (content == null || content.isEmpty()
                || content.getBytes(StandardCharsets.UTF_8).length > MAX_ENVELOPE_BYTES) {
            throw new IOException("managed rule envelope is absent or oversized");
        }
        JsonNode root = JSON.readTree(content);
        if (root == null || !root.isObject()) throw new IOException("managed rule envelope must be an object");
        Set<String> names = new HashSet<>();
        root.fieldNames().forEachRemaining(names::add);
        if (!names.equals(FIELDS)) throw new IOException("managed rule envelope fields are invalid");

        String protocol = text(root, "protocol_version");
        String binding = text(root, "binding_id");
        String publication = text(root, "publication_id");
        String version = text(root, "target_version_id");
        JsonNode sequenceNode = root.get("publication_sequence");
        String kind = text(root, "rule_kind");
        String profile = text(root, "profile_id");
        String digest = text(root, "payload_sha256");
        String payload = text(root, "rule_payload");
        if (sequenceNode == null || !sequenceNode.isIntegralNumber()) {
            throw new IOException("managed publication sequence is invalid");
        }
        BigInteger sequence = sequenceNode.bigIntegerValue();
        if (sequence.signum() <= 0 || sequence.compareTo(MAX_SEQUENCE) > 0) {
            throw new IOException("managed publication sequence is invalid");
        }
        if (!PROTOCOL.equals(protocol) || !identifier(binding) || !identifier(publication)
                || !identifier(version) || !identifier(profile) || !binding.equals(expectedBindingId)
                || !profile.equals(expectedProfileId) || !"flow".equals(kind) || !DIGEST.matcher(digest).matches()) {
            throw new IOException("managed rule envelope identity or profile is unsupported");
        }
        byte[] payloadBytes = payload.getBytes(StandardCharsets.UTF_8);
        if (payloadBytes.length == 0 || payloadBytes.length > MAX_PAYLOAD_BYTES) {
            throw new IOException("managed rule payload is absent or oversized");
        }
        if (!MessageDigest.isEqual(sha256(payloadBytes).getBytes(StandardCharsets.US_ASCII),
                digest.getBytes(StandardCharsets.US_ASCII))) {
            throw new IOException("managed rule payload digest mismatch");
        }
        JsonNode rules = JSON.readTree(payload);
        if (rules == null || !rules.isArray()) throw new IOException("managed rule payload must be an array");
        for (JsonNode rule : rules) {
            if (!rule.isObject()) throw new IOException("managed rule payload contains a non-object item");
        }
        return new Envelope(binding, publication, version, sequence.longValueExact(), kind, profile, digest, payload);
    }

    private static String text(JsonNode object, String field) throws IOException {
        JsonNode value = object.get(field);
        if (value == null || !value.isTextual()) throw new IOException("managed rule envelope field type is invalid");
        return value.textValue();
    }

    private static boolean identifier(String value) {
        return value != null && IDENTIFIER.matcher(value).matches();
    }

    private static String sha256(byte[] content) {
        try {
            return java.util.HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(content));
        } catch (NoSuchAlgorithmException impossible) {
            throw new IllegalStateException("SHA-256 is unavailable", impossible);
        }
    }

    /** Immutable, validated publication provenance carried beside native rules. */
    public record Envelope(String bindingId, String publicationId, String targetVersionId,
                           long publicationSequence, String ruleKind, String profileId,
                           String payloadSha256, String rulePayload) { }
}

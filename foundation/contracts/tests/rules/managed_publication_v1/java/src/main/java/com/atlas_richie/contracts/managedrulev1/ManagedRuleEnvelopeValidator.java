package com.atlas_richie.contracts.managedrulev1;

import com.fasterxml.jackson.core.JsonFactory;
import com.fasterxml.jackson.core.StreamReadFeature;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

import java.io.IOException;
import java.math.BigInteger;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HashSet;
import java.util.Iterator;
import java.util.Set;

/** Test-only validator for the draft managed rule-publication envelope. */
public final class ManagedRuleEnvelopeValidator {

    private static final String PROTOCOL = "atlas-richie.sentinel.managed-rule-publication/v1";
    private static final String IDENTIFIER = "^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$";
    private static final String DIGEST = "^[0-9a-f]{64}$";
    private static final Set<String> FIELDS = Set.of("protocol_version", "binding_id", "publication_id",
        "target_version_id", "publication_sequence", "rule_kind", "profile_id", "payload_sha256", "rule_payload");
    private static final Set<String> RULE_KINDS = Set.of("flow", "degrade", "system", "authority", "param");
    private static final BigInteger MAX_SEQUENCE = new BigInteger("9007199254740991");
    private static final int MAX_PAYLOAD_BYTES = 512 * 1024;
    private static final int MAX_RULE_PAYLOAD_BYTES = 500 * 1024;
    private static final ObjectMapper JSON = new ObjectMapper(JsonFactory.builder()
        .enable(StreamReadFeature.STRICT_DUPLICATE_DETECTION)
        .build()).enable(DeserializationFeature.FAIL_ON_TRAILING_TOKENS);

    private ManagedRuleEnvelopeValidator() {}

    /** Validate one envelope and return the exact UTF-8 inner rule-array bytes. */
    public static byte[] validateAndExtract(byte[] payload) {
        require(payload != null && payload.length > 0 && payload.length <= MAX_PAYLOAD_BYTES, "payload_size");
        JsonNode root = parse(payload, "invalid_json");
        require(root != null && root.isObject(), "object");
        exactFields(root);
        require(PROTOCOL.equals(text(root, "protocol_version")), "protocol_version");
        identifier(root, "binding_id");
        identifier(root, "publication_id");
        identifier(root, "target_version_id");
        identifier(root, "profile_id");
        JsonNode sequence = root.get("publication_sequence");
        require(sequence != null && sequence.isIntegralNumber() && sequence.bigIntegerValue().signum() > 0
            && sequence.bigIntegerValue().compareTo(MAX_SEQUENCE) <= 0, "publication_sequence");
        require(RULE_KINDS.contains(text(root, "rule_kind")), "rule_kind");
        String digest = text(root, "payload_sha256");
        require(digest.matches(DIGEST), "payload_sha256");
        String inner = text(root, "rule_payload");
        require(hasUnicodeScalars(inner), "rule_payload_unicode");
        byte[] ruleBytes = inner.getBytes(StandardCharsets.UTF_8);
        require(ruleBytes.length <= MAX_RULE_PAYLOAD_BYTES, "rule_payload_size");
        JsonNode rules = parse(ruleBytes, "rule_payload_json");
        require(rules != null && rules.isArray(), "rule_payload_array");
        for (JsonNode rule : rules) require(rule.isObject(), "rule_payload_item");
        require(digest(ruleBytes).equals(digest), "payload_sha256_mismatch");
        return ruleBytes;
    }

    private static JsonNode parse(byte[] payload, String error) {
        try {
            return JSON.readTree(payload);
        } catch (IOException | RuntimeException exception) {
            throw new IllegalArgumentException(error, exception);
        }
    }

    private static void exactFields(JsonNode object) {
        Set<String> supplied = new HashSet<>();
        Iterator<String> names = object.fieldNames();
        while (names.hasNext()) supplied.add(names.next());
        require(supplied.equals(FIELDS), "fields");
    }

    private static void identifier(JsonNode object, String field) {
        require(text(object, field).matches(IDENTIFIER), field);
    }

    private static String text(JsonNode object, String field) {
        JsonNode value = object.get(field);
        require(value != null && value.isTextual(), field);
        return value.textValue();
    }

    private static boolean hasUnicodeScalars(String value) {
        for (int index = 0; index < value.length(); index++) {
            char current = value.charAt(index);
            if (Character.isHighSurrogate(current)) {
                if (++index >= value.length() || !Character.isLowSurrogate(value.charAt(index))) return false;
            } else if (Character.isLowSurrogate(current)) {
                return false;
            }
        }
        return true;
    }

    private static String digest(byte[] value) {
        try {
            byte[] bytes = MessageDigest.getInstance("SHA-256").digest(value);
            StringBuilder result = new StringBuilder(bytes.length * 2);
            for (byte item : bytes) result.append(String.format("%02x", item & 0xff));
            return result.toString();
        } catch (NoSuchAlgorithmException exception) {
            throw new IllegalStateException("SHA-256 is unavailable", exception);
        }
    }

    private static void require(boolean condition, String error) {
        if (!condition) throw new IllegalArgumentException(error);
    }
}

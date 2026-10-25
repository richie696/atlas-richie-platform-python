package com.atlas_richie.contracts.ruleloadv1;

import com.fasterxml.jackson.core.JsonFactory;
import com.fasterxml.jackson.core.StreamReadFeature;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

import java.io.IOException;
import java.math.BigInteger;
import java.time.Instant;
import java.time.format.DateTimeParseException;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.regex.Pattern;

/** Test-only strict validator for the shared Rule Load Observation V1 fixtures. */
public final class RuleLoadObservationV1Validator {

    private static final String PROTOCOL = "atlas-richie.sentinel.rule-load-observation/v1";
    private static final int MAX_BYTES = 512 * 1024;
    private static final BigInteger MAX_SAFE_INTEGER = new BigInteger("9007199254740991");
    private static final Pattern UUID_V4 = Pattern.compile("^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$");
    private static final Pattern IDENTIFIER = Pattern.compile("^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$");
    private static final Pattern DIGEST = Pattern.compile("^[0-9a-f]{64}$");
    private static final Pattern UTC_MILLIS = Pattern.compile("^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\\.[0-9]{3}Z$");
    private static final Set<String> RULE_KINDS = Set.of("flow", "degrade", "param_flow", "system", "authority");
    private static final Set<String> FAILURE_REASONS = Set.of("source_unavailable", "decode_rejected", "profile_unsupported", "validation_rejected", "apply_failed");
    private static final ObjectMapper JSON = new ObjectMapper(JsonFactory.builder()
        .enable(StreamReadFeature.STRICT_DUPLICATE_DETECTION)
        .build())
        .enable(DeserializationFeature.FAIL_ON_TRAILING_TOKENS);

    private RuleLoadObservationV1Validator() {}

    public static void validate(byte[] payload) {
        require(payload != null && payload.length > 0 && payload.length <= MAX_BYTES, "invalid_payload_size");
        JsonNode root = parse(payload);
        require(root.isObject(), "invalid_object");
        exact(root, Set.of("protocol_version", "observation_id", "process_epoch", "sequence", "binding_id", "profile_id", "event_kind", "active_snapshot", "attempt", "observed_at"));
        require(PROTOCOL.equals(text(root, "protocol_version")), "unsupported_protocol");
        require(uuid(text(root, "observation_id")) && uuid(text(root, "process_epoch")), "invalid_uuid");
        require(identifier(text(root, "binding_id")) && identifier(text(root, "profile_id")), "invalid_identifier");
        JsonNode sequence = root.get("sequence");
        require(sequence != null && sequence.isIntegralNumber() && sequence.bigIntegerValue().signum() > 0 && sequence.bigIntegerValue().compareTo(MAX_SAFE_INTEGER) <= 0, "invalid_sequence");
        timestamp(text(root, "observed_at"));
        String eventKind = text(root, "event_kind");
        require(Set.of("snapshot_applied", "snapshot_failed", "heartbeat").contains(eventKind), "invalid_event_kind");

        JsonNode active = root.get("active_snapshot");
        JsonNode attempt = root.get("attempt");
        if (!active.isNull()) validateSnapshot(active);
        if (!attempt.isNull()) validateAttempt(attempt);
        switch (eventKind) {
            case "snapshot_applied" -> require(!active.isNull() && attempt.isNull(), "invalid_applied_state");
            case "snapshot_failed" -> require(!attempt.isNull(), "invalid_failed_state");
            case "heartbeat" -> require(attempt.isNull(), "invalid_heartbeat_state");
            default -> throw new IllegalArgumentException("invalid_event_kind");
        }
    }

    private static JsonNode parse(byte[] payload) {
        try {
            JsonNode value = JSON.readTree(payload);
            if (value == null) throw new IllegalArgumentException("invalid_json");
            return value;
        } catch (IOException | RuntimeException exception) {
            throw new IllegalArgumentException("invalid_json", exception);
        }
    }

    private static void validateSnapshot(JsonNode snapshot) {
        require(snapshot.isObject(), "invalid_snapshot");
        exact(snapshot, Set.of("source_revision", "source_bytes_sha256", "canonical_rules_sha256", "membership_complete", "members"));
        revisionOrNull(snapshot.get("source_revision"));
        digestOrNull(snapshot.get("source_bytes_sha256"));
        require(digest(text(snapshot, "canonical_rules_sha256")), "invalid_canonical_digest");
        JsonNode completeNode = snapshot.get("membership_complete");
        JsonNode members = snapshot.get("members");
        require(completeNode.isBoolean() && members.isArray() && members.size() <= 8192, "invalid_members");
        if (!completeNode.booleanValue()) require(members.isEmpty(), "incomplete_membership_claims_members");
        List<String> identities = new ArrayList<>();
        for (JsonNode member : members) {
            require(member.isObject(), "invalid_member");
            exact(member, Set.of("rule_kind", "fingerprint_sha256"));
            String kind = text(member, "rule_kind");
            String fingerprint = text(member, "fingerprint_sha256");
            require(RULE_KINDS.contains(kind) && digest(fingerprint), "invalid_member_value");
            identities.add(kind + "\u0000" + fingerprint);
        }
        List<String> sorted = identities.stream().sorted().toList();
        require(identities.equals(sorted) && new HashSet<>(identities).size() == identities.size(), "members_not_sorted_unique");
    }

    private static void validateAttempt(JsonNode attempt) {
        require(attempt.isObject(), "invalid_attempt");
        exact(attempt, Set.of("source_revision", "source_bytes_sha256", "canonical_rules_sha256", "failure_reason"));
        revisionOrNull(attempt.get("source_revision"));
        digestOrNull(attempt.get("source_bytes_sha256"));
        digestOrNull(attempt.get("canonical_rules_sha256"));
        require(FAILURE_REASONS.contains(text(attempt, "failure_reason")), "invalid_failure_reason");
    }

    private static void exact(JsonNode object, Set<String> expected) {
        Set<String> actual = new HashSet<>();
        object.fieldNames().forEachRemaining(actual::add);
        require(actual.equals(expected), "invalid_fields");
    }

    private static String text(JsonNode object, String field) {
        JsonNode value = object.get(field);
        require(value != null && value.isTextual(), "invalid_" + field);
        return value.textValue();
    }

    private static boolean uuid(String value) { return UUID_V4.matcher(value).matches(); }
    private static boolean identifier(String value) { return IDENTIFIER.matcher(value).matches(); }
    private static boolean digest(String value) { return DIGEST.matcher(value).matches(); }

    private static void digestOrNull(JsonNode value) {
        require(value != null && (value.isNull() || (value.isTextual() && digest(value.textValue()))), "invalid_digest");
    }

    private static void revisionOrNull(JsonNode value) {
        if (value == null || value.isNull()) return;
        require(value.isTextual() && value.textValue().length() <= 200 && !value.textValue().isEmpty(), "invalid_source_revision");
        require(value.textValue().chars().allMatch(character -> character >= 0x20 && character <= 0x7e), "invalid_source_revision");
    }

    private static void timestamp(String value) {
        require(UTC_MILLIS.matcher(value).matches(), "invalid_timestamp");
        try {
            Instant.parse(value);
        } catch (DateTimeParseException exception) {
            throw new IllegalArgumentException("invalid_timestamp", exception);
        }
    }

    private static void require(boolean condition, String message) {
        if (!condition) throw new IllegalArgumentException(message);
    }
}

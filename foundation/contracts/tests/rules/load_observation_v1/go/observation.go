// Package observationv1 validates the shared Rule Load Observation V1 fixture
// corpus. It is a test-only conformance helper, not a production Runtime SDK.
package observationv1

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"regexp"
	"sort"
	"strings"
	"time"
)

const (
	protocol   = "atlas-richie.sentinel.rule-load-observation/v1"
	maxPayload = 512 * 1024
	maxSafeInt = int64(9007199254740991)
)

var (
	uuidV4Pattern = regexp.MustCompile(`^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$`)
	identifier    = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$`)
	digest        = regexp.MustCompile(`^[0-9a-f]{64}$`)
	instant       = regexp.MustCompile(`^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}Z$`)
)

// Validate checks one exact V1 body, including duplicate keys and state invariants.
func Validate(payload []byte) error {
	if len(payload) == 0 || len(payload) > maxPayload {
		return errors.New("invalid_payload_size")
	}
	decoder := json.NewDecoder(bytes.NewReader(payload))
	decoder.UseNumber()
	value, err := readValue(decoder)
	if err != nil {
		return fmt.Errorf("invalid_json: %w", err)
	}
	if _, err = decoder.Token(); !errors.Is(err, io.EOF) {
		return errors.New("invalid_trailing_json")
	}
	root, ok := value.(map[string]any)
	if !ok || !exact(root, "protocol_version", "observation_id", "process_epoch", "sequence", "binding_id", "profile_id", "event_kind", "active_snapshot", "attempt", "observed_at") {
		return errors.New("invalid_fields")
	}
	if root["protocol_version"] != protocol {
		return errors.New("unsupported_protocol")
	}
	if !validUUID(root["observation_id"]) || !validUUID(root["process_epoch"]) {
		return errors.New("invalid_uuid")
	}
	for _, field := range []string{"binding_id", "profile_id"} {
		text, ok := root[field].(string)
		if !ok || !identifier.MatchString(text) {
			return errors.New("invalid_identifier")
		}
	}
	sequence, ok := root["sequence"].(json.Number)
	if !ok {
		return errors.New("invalid_sequence")
	}
	sequenceInt, err := sequence.Int64()
	if err != nil || sequenceInt < 1 || sequenceInt > maxSafeInt {
		return errors.New("invalid_sequence")
	}
	observedAt, ok := root["observed_at"].(string)
	if !ok || !instant.MatchString(observedAt) {
		return errors.New("invalid_observed_at")
	}
	if _, err := time.Parse("2006-01-02T15:04:05.000Z", observedAt); err != nil {
		return errors.New("invalid_observed_at")
	}
	kind, ok := root["event_kind"].(string)
	if !ok || !oneOf(kind, "snapshot_applied", "snapshot_failed", "heartbeat") {
		return errors.New("invalid_event_kind")
	}
	active, activeOK := root["active_snapshot"]
	attempt, attemptOK := root["attempt"]
	if !activeOK || !attemptOK {
		return errors.New("invalid_fields")
	}
	if active != nil {
		if err := validateSnapshot(active); err != nil {
			return err
		}
	}
	if attempt != nil {
		if err := validateAttempt(attempt); err != nil {
			return err
		}
	}
	switch kind {
	case "snapshot_applied":
		if active == nil || attempt != nil {
			return errors.New("invalid_applied_state")
		}
	case "snapshot_failed":
		if attempt == nil {
			return errors.New("invalid_failed_state")
		}
	case "heartbeat":
		if attempt != nil {
			return errors.New("invalid_heartbeat_state")
		}
	}
	return nil
}

func validateSnapshot(value any) error {
	snapshot, ok := value.(map[string]any)
	if !ok || !exact(snapshot, "source_revision", "source_bytes_sha256", "canonical_rules_sha256", "membership_complete", "members") {
		return errors.New("invalid_snapshot_fields")
	}
	if !validRevisionOrNull(snapshot["source_revision"]) || !validDigestOrNull(snapshot["source_bytes_sha256"]) || !validDigest(snapshot["canonical_rules_sha256"]) {
		return errors.New("invalid_snapshot_digest_or_revision")
	}
	complete, ok := snapshot["membership_complete"].(bool)
	if !ok {
		return errors.New("invalid_membership_complete")
	}
	members, ok := snapshot["members"].([]any)
	if !ok || len(members) > 8192 || (!complete && len(members) != 0) {
		return errors.New("invalid_members")
	}
	identities := make([]string, 0, len(members))
	for _, item := range members {
		member, ok := item.(map[string]any)
		if !ok || !exact(member, "rule_kind", "fingerprint_sha256") {
			return errors.New("invalid_member_fields")
		}
		kind, kindOK := member["rule_kind"].(string)
		fingerprint, fingerprintOK := member["fingerprint_sha256"].(string)
		if !kindOK || !oneOf(kind, "flow", "degrade", "param_flow", "system", "authority") || !fingerprintOK || !digest.MatchString(fingerprint) {
			return errors.New("invalid_member")
		}
		identities = append(identities, kind+"\x00"+fingerprint)
	}
	if !sort.StringsAreSorted(identities) {
		return errors.New("members_not_sorted")
	}
	for index := 1; index < len(identities); index++ {
		if identities[index] == identities[index-1] {
			return errors.New("duplicate_member")
		}
	}
	return nil
}

func validateAttempt(value any) error {
	attempt, ok := value.(map[string]any)
	if !ok || !exact(attempt, "source_revision", "source_bytes_sha256", "canonical_rules_sha256", "failure_reason") {
		return errors.New("invalid_attempt_fields")
	}
	reason, reasonOK := attempt["failure_reason"].(string)
	if !validRevisionOrNull(attempt["source_revision"]) || !validDigestOrNull(attempt["source_bytes_sha256"]) || !validDigestOrNull(attempt["canonical_rules_sha256"]) || !reasonOK || !oneOf(reason, "source_unavailable", "decode_rejected", "profile_unsupported", "validation_rejected", "apply_failed") {
		return errors.New("invalid_attempt")
	}
	return nil
}

func readValue(decoder *json.Decoder) (any, error) {
	token, err := decoder.Token()
	if err != nil {
		return nil, err
	}
	delim, ok := token.(json.Delim)
	if !ok {
		return token, nil
	}
	switch delim {
	case '{':
		object := map[string]any{}
		for decoder.More() {
			keyToken, readErr := decoder.Token()
			if readErr != nil {
				return nil, readErr
			}
			key, ok := keyToken.(string)
			if !ok {
				return nil, errors.New("invalid_object_key")
			}
			if _, exists := object[key]; exists {
				return nil, errors.New("duplicate_json_key")
			}
			value, readErr := readValue(decoder)
			if readErr != nil {
				return nil, readErr
			}
			object[key] = value
		}
		_, err = decoder.Token()
		return object, err
	case '[':
		array := []any{}
		for decoder.More() {
			value, readErr := readValue(decoder)
			if readErr != nil {
				return nil, readErr
			}
			array = append(array, value)
		}
		_, err = decoder.Token()
		return array, err
	default:
		return nil, errors.New("invalid_json_delimiter")
	}
}

func exact(value map[string]any, fields ...string) bool {
	if len(value) != len(fields) {
		return false
	}
	for _, field := range fields {
		if _, found := value[field]; !found {
			return false
		}
	}
	return true
}

func validUUID(value any) bool {
	text, ok := value.(string)
	return ok && uuidV4Pattern.MatchString(text)
}

func validDigest(value any) bool {
	text, ok := value.(string)
	return ok && digest.MatchString(text)
}

func validDigestOrNull(value any) bool { return value == nil || validDigest(value) }

func validRevisionOrNull(value any) bool {
	if value == nil {
		return true
	}
	text, ok := value.(string)
	if !ok || len(text) < 1 || len(text) > 200 {
		return false
	}
	return strings.IndexFunc(text, func(character rune) bool { return character < 0x20 || character > 0x7e }) == -1
}

func oneOf(value string, choices ...string) bool {
	for _, choice := range choices {
		if value == choice {
			return true
		}
	}
	return false
}

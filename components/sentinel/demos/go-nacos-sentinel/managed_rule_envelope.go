package main

import (
	"bytes"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"regexp"
	"strconv"
	"unicode/utf8"
)

const (
	managedRulePublicationProtocolV1 = "atlas-richie.sentinel.managed-rule-publication/v1"
	maxManagedEnvelopeBytes          = 512 * 1024
	maxManagedPayloadBytes           = 500 * 1024
	maxManagedSequence               = int64(9_007_199_254_740_991)
)

var managedIdentifierPattern = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$`)
var managedDigestPattern = regexp.MustCompile(`^[0-9a-f]{64}$`)

type managedRuleEnvelopeV1 struct {
	ProtocolVersion     string      `json:"protocol_version"`
	BindingID           string      `json:"binding_id"`
	PublicationID       string      `json:"publication_id"`
	TargetVersionID     string      `json:"target_version_id"`
	PublicationSequence json.Number `json:"publication_sequence"`
	RuleKind            string      `json:"rule_kind"`
	ProfileID           string      `json:"profile_id"`
	PayloadSHA256       string      `json:"payload_sha256"`
	RulePayload         string      `json:"rule_payload"`
}

// decodeManagedRuleEnvelopeV1 validates the frozen envelope without changing SDK state.
func decodeManagedRuleEnvelopeV1(content, expectedBindingID, expectedProfileID string) (managedRuleEnvelopeV1, error) {
	if len([]byte(content)) == 0 || len([]byte(content)) > maxManagedEnvelopeBytes || !utf8.ValidString(content) {
		return managedRuleEnvelopeV1{}, errors.New("managed rule envelope is absent or oversized")
	}
	if !hasUniqueJSONKeys([]byte(content)) {
		return managedRuleEnvelopeV1{}, errors.New("managed rule envelope has duplicate fields or invalid JSON")
	}
	decoder := json.NewDecoder(bytes.NewBufferString(content))
	decoder.DisallowUnknownFields()
	decoder.UseNumber()
	var envelope managedRuleEnvelopeV1
	if err := decoder.Decode(&envelope); err != nil {
		return managedRuleEnvelopeV1{}, errors.New("managed rule envelope is invalid")
	}
	var trailing any
	if err := decoder.Decode(&trailing); err != io.EOF {
		return managedRuleEnvelopeV1{}, errors.New("managed rule envelope has trailing data")
	}
	sequence, err := strconv.ParseInt(envelope.PublicationSequence.String(), 10, 64)
	if err != nil || sequence < 1 || sequence > maxManagedSequence || strconv.FormatInt(sequence, 10) != envelope.PublicationSequence.String() {
		return managedRuleEnvelopeV1{}, errors.New("managed publication sequence is invalid")
	}
	if envelope.ProtocolVersion != managedRulePublicationProtocolV1 ||
		!managedIdentifierPattern.MatchString(envelope.BindingID) ||
		!managedIdentifierPattern.MatchString(envelope.PublicationID) ||
		!managedIdentifierPattern.MatchString(envelope.TargetVersionID) ||
		!managedIdentifierPattern.MatchString(envelope.ProfileID) ||
		envelope.BindingID != expectedBindingID || envelope.ProfileID != expectedProfileID ||
		envelope.RuleKind != "flow" || !managedDigestPattern.MatchString(envelope.PayloadSHA256) {
		return managedRuleEnvelopeV1{}, errors.New("managed rule envelope identity or profile is unsupported")
	}
	payload := []byte(envelope.RulePayload)
	if len(payload) == 0 || len(payload) > maxManagedPayloadBytes || !utf8.Valid(payload) {
		return managedRuleEnvelopeV1{}, errors.New("managed rule payload is absent or oversized")
	}
	digest := sha256.Sum256(payload)
	if subtle.ConstantTimeCompare([]byte(hex.EncodeToString(digest[:])), []byte(envelope.PayloadSHA256)) != 1 {
		return managedRuleEnvelopeV1{}, errors.New("managed rule payload digest mismatch")
	}
	var items []json.RawMessage
	if !hasUniqueJSONKeys(payload) {
		return managedRuleEnvelopeV1{}, errors.New("managed rule payload has duplicate fields or invalid JSON")
	}
	inner := json.NewDecoder(bytes.NewReader(payload))
	inner.DisallowUnknownFields()
	if err := inner.Decode(&items); err != nil || items == nil {
		return managedRuleEnvelopeV1{}, errors.New("managed rule payload must be a JSON array")
	}
	var innerTrailing any
	if err := inner.Decode(&innerTrailing); err != io.EOF {
		return managedRuleEnvelopeV1{}, errors.New("managed rule payload has trailing data")
	}
	for _, item := range items {
		var object map[string]json.RawMessage
		if err := json.Unmarshal(item, &object); err != nil || object == nil {
			return managedRuleEnvelopeV1{}, errors.New("managed rule payload contains a non-object item")
		}
	}
	return envelope, nil
}

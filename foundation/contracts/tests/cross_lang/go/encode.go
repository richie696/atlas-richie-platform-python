// Package main: Atlas Richie Agent Reporting Protocol V1 — strict JSON codec (DRAFT).
//
// 1:1 mirror of foundation/contracts/src/atlas_richie/contracts/reporting/v1/codec.py
// plus components/sentinel/docs/protocol/reporting-protocol-01-envelope-v1.md
// and reporting-protocol-02-transport-v1.md.
//
// Strict JSON encode / decode. Rejects:
//   - unknown field (V1 strict even in DRAFT)
//   - missing required field
//   - protocol_version != "atlas-richie.reporting/v1"
//   - event_kind not in V1 6 enums
//   - error_code not in V1 11 enums
//   - health_class / reason_class / exec_result not in their enums
//   - rule_version_checksum not "sha256:" + 64 hex chars
//   - time fields not ISO 8601 UTC microsecond
//   - UUID fields not 8-4-4-4-12 lowercase hex
//   - envelope > 16 KiB / batch > 64 KiB / batch > 256 events
//   - mixed identity/generation in batch events
//   - error batch atomic rejection (no per-event disposition)
package main

import (
	"encoding/json"
	"errors"
	"fmt"
	"regexp"
	"sort"
	"strconv"
)

const (
	ProtocolVersion       = "atlas-richie.reporting/v1"
	EnvelopeMaxSizeBytes  = 16 * 1024
	BatchMaxSizeBytes     = 64 * 1024
	BatchMaxEvents        = 256
	Int64Min              = 0
	Int64Max              = int64(1)<<53 - 1
	SourceIDMaxLen        = 256
	RuleIDMaxLen          = 256
	ReasonMessageMaxLen   = 64
	ErrorMessageMaxLen    = 1024
	ChecksumPrefix        = "sha256:"
	ChecksumHexLen        = 64
	XAtlasReportingHeader = "X-Atlas-Reporting-Token"
	AuthTokenMinLen       = 16
)

var eventKinds = map[string]bool{
	"RULE_SOURCE_ACTIVATED": true,
	"RULE_SOURCE_STALE":     true,
	"RULE_SOURCE_DEGRADED":  true,
	"RULE_APPLIED":          true,
	"RULE_BLOCKED":          true,
	"RULE_FAILED":           true,
}

var healthClasses = map[string]bool{
	"STALE":        true,
	"DEGRADED":     true,
	"DISCONNECTED": true,
}

var reasonClasses = map[string]bool{
	"EMPTY_DATA_ID":       true,
	"NETWORK_TIMEOUT":     true,
	"NETWORK_UNAVAILABLE": true,
	"AUTH_FAILED":         true,
	"DECODE_FAILED":       true,
	"STATE_INVALID":       true,
	"UNKNOWN":             true,
}

var execResults = map[string]bool{
	"APPLIED": true,
	"BLOCKED": true,
	"FAILED":  true,
}

var errorCodes = map[string]bool{
	"PROTOCOL_VERSION_MISMATCH": true,
	"MALFORMED_ENVELOPE":        true,
	"UNKNOWN_EVENT_KIND":        true,
	"PAYLOAD_SCHEMA_MISMATCH":   true,
	"INSTANCE_ID_EMPTY":         true,
	"SEQUENCE_NOT_MONOTONIC":    true,
	"SEQUENCE_GAP":              true,
	"STALE_EPOCH":               true,
	"ENVELOPE_TOO_LARGE":        true,
	"BATCH_TOO_LARGE":           true,
	"AUTH_FAILED":               true,
}

var envelopeRequiredFields = map[string]bool{
	"protocol_version": true,
	"event_kind":       true,
	"event_payload":    true,
	"instance_id":      true,
	"startup_epoch":    true,
	"sequence":         true,
	"captured_at":      true,
}

var batchRequiredFields = map[string]bool{
	"protocol_version": true,
	"instance_id":      true,
	"startup_epoch":    true,
	"batch_id":         true,
	"sent_at":          true,
	"events":           true,
	"dropped_count":    true,
}

var ackRequiredFields = map[string]bool{
	"protocol_version": true,
	"batch_id":         true,
	"received_at":      true,
	"ack_sequences":    true,
	"duplicate_count":  true,
}

var errorRequiredFields = map[string]bool{
	"protocol_version": true,
	"error_code":       true,
	"message":          true,
	"details":          true,
}

type CodecError struct {
	Code    string
	Message string
}

func (e *CodecError) Error() string {
	return "[" + e.Code + "] " + e.Message
}

func newCodecError(code, msg string) *CodecError {
	return &CodecError{Code: code, Message: msg}
}

var (
	uuidV4Re          = regexp.MustCompile(`^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$`)
	iso8601UTCMicroRe = regexp.MustCompile(`^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$`)
	checksumRe        = regexp.MustCompile(`^sha256:[0-9a-f]{64}$`)
)

func validateUUID(name string, v interface{}) {
	s, ok := v.(string)
	if !ok || !uuidV4Re.MatchString(s) {
		panic(newCodecError("MALFORMED_ENVELOPE",
			name+" must be UUID v4 (8-4-4-4-12 lowercase hex)"))
	}
}

func validateISO8601UTCMicro(name string, v interface{}) {
	s, ok := v.(string)
	if !ok || !iso8601UTCMicroRe.MatchString(s) {
		panic(newCodecError("MALFORMED_ENVELOPE",
			name+" must be ISO 8601 UTC microsecond (YYYY-MM-DDTHH:MM:SS.ffffffZ)"))
	}
}

func validateInt64(name string, v interface{}) {
	f, ok := v.(float64)
	if !ok {
		panic(newCodecError("MALFORMED_ENVELOPE", name+" must be int"))
	}
	if f != float64(int64(f)) {
		panic(newCodecError("MALFORMED_ENVELOPE", name+" must be int (no fractional part)"))
	}
	n := int64(f)
	if n < Int64Min || n > Int64Max {
		panic(newCodecError("MALFORMED_ENVELOPE",
			name+" must be int64 in [0, 2^53-1] (got "+strconv.FormatInt(n, 10)+")"))
	}
}

func validateProtocolVersion(obj map[string]interface{}) {
	if obj["protocol_version"] != ProtocolVersion {
		panic(newCodecError("PROTOCOL_VERSION_MISMATCH",
			fmt.Sprintf("expected protocol_version=%q, got %v",
				ProtocolVersion, obj["protocol_version"])))
	}
}

func validateCommonRuleVersionTriplet(payload map[string]interface{}) {
	validateInt64("rule_version_epoch", payload["rule_version_epoch"])
	validateInt64("rule_version_revision", payload["rule_version_revision"])
	cs, ok := payload["rule_version_checksum"].(string)
	if !ok || !checksumRe.MatchString(cs) {
		panic(newCodecError("PAYLOAD_SCHEMA_MISMATCH",
			"rule_version_checksum must be 'sha256:' + 64 hex chars"))
	}
}

func validateSourceID(v interface{}) {
	s, ok := v.(string)
	if !ok || s == "" {
		panic(newCodecError("PAYLOAD_SCHEMA_MISMATCH", "source_id must be non-empty string"))
	}
	if len(s) > SourceIDMaxLen {
		panic(newCodecError("PAYLOAD_SCHEMA_MISMATCH",
			fmt.Sprintf("source_id exceeds %d chars", SourceIDMaxLen)))
	}
}

func validateRuleVersionTripletAllOrNone(payload map[string]interface{}) {
	_, hasEpoch := payload["rule_version_epoch"]
	_, hasRev := payload["rule_version_revision"]
	_, hasCs := payload["rule_version_checksum"]
	if (hasEpoch || hasRev || hasCs) && !(hasEpoch && hasRev && hasCs) {
		panic(newCodecError("PAYLOAD_SCHEMA_MISMATCH",
			"3 rule_version_* fields must be all present or all omitted (成组可选, 协议 §5.2)"))
	}
	if hasEpoch && hasRev && hasCs {
		validateCommonRuleVersionTriplet(payload)
	}
}

func validatePayloadRuleSourceActivated(payload map[string]interface{}) {
	required := []string{
		"source_id", "rule_version_epoch", "rule_version_revision", "rule_version_checksum",
	}
	if !sameKeys(payload, required) {
		panic(newCodecError("PAYLOAD_SCHEMA_MISMATCH",
			fmt.Sprintf("RuleSourceActivatedPayload must have %v, got %v",
				required, keysOf(payload))))
	}
	validateSourceID(payload["source_id"])
	validateCommonRuleVersionTriplet(payload)
}

func validatePayloadRuleSourceHealth(payload map[string]interface{}) {
	required := map[string]bool{
		"source_id":    true,
		"health_class": true,
		"reason_class": true,
	}
	allowed := map[string]bool{
		"source_id":             true,
		"health_class":          true,
		"reason_class":          true,
		"rule_version_epoch":    true,
		"rule_version_revision": true,
		"rule_version_checksum": true,
		"reason_message":        true,
	}
	for k := range payload {
		if !allowed[k] {
			panic(newCodecError("PAYLOAD_SCHEMA_MISMATCH",
				fmt.Sprintf("RuleSourceHealthPayload must have %v, got %v",
					keysOfBool(allowed), keysOf(payload))))
		}
	}
	for k := range required {
		if _, ok := payload[k]; !ok {
			panic(newCodecError("PAYLOAD_SCHEMA_MISMATCH",
				fmt.Sprintf("RuleSourceHealthPayload missing required field %q", k)))
		}
	}
	validateSourceID(payload["source_id"])
	hc, ok := payload["health_class"].(string)
	if !ok || !healthClasses[hc] {
		panic(newCodecError("PAYLOAD_SCHEMA_MISMATCH",
			"health_class must be one of STALE/DEGRADED/DISCONNECTED, got "+asString(payload["health_class"])))
	}
	rc, ok := payload["reason_class"].(string)
	if !ok || !reasonClasses[rc] {
		panic(newCodecError("PAYLOAD_SCHEMA_MISMATCH",
			"reason_class must be one of ReasonClass enum, got "+asString(payload["reason_class"])))
	}
	validateRuleVersionTripletAllOrNone(payload)
	if msg, ok := payload["reason_message"]; ok {
		ms, ok := msg.(string)
		if !ok {
			panic(newCodecError("PAYLOAD_SCHEMA_MISMATCH", "reason_message must be string"))
		}
		if len(ms) > ReasonMessageMaxLen {
			panic(newCodecError("PAYLOAD_SCHEMA_MISMATCH",
				fmt.Sprintf("reason_message exceeds %d bytes (脱敏 reason 上限, 协议 §5.2)",
					ReasonMessageMaxLen)))
		}
	}
}

func validatePayloadRuleExec(payload map[string]interface{}) {
	required := []string{
		"source_id", "rule_id",
		"rule_version_epoch", "rule_version_revision", "rule_version_checksum",
		"exec_result", "failure_class",
	}
	if !sameKeys(payload, required) {
		panic(newCodecError("PAYLOAD_SCHEMA_MISMATCH",
			fmt.Sprintf("RuleExecPayload must have %v, got %v",
				required, keysOf(payload))))
	}
	validateSourceID(payload["source_id"])
	ruleID, ok := payload["rule_id"].(string)
	if !ok || ruleID == "" {
		panic(newCodecError("PAYLOAD_SCHEMA_MISMATCH", "rule_id must be non-empty string"))
	}
	if len(ruleID) > RuleIDMaxLen {
		panic(newCodecError("PAYLOAD_SCHEMA_MISMATCH",
			fmt.Sprintf("rule_id exceeds %d chars", RuleIDMaxLen)))
	}
	validateCommonRuleVersionTriplet(payload)
	er, ok := payload["exec_result"].(string)
	if !ok || !execResults[er] {
		panic(newCodecError("PAYLOAD_SCHEMA_MISMATCH",
			"exec_result must be one of APPLIED/BLOCKED/FAILED, got "+asString(payload["exec_result"])))
	}
	fc := payload["failure_class"]
	if er == "FAILED" {
		if fc == nil {
			panic(newCodecError("PAYLOAD_SCHEMA_MISMATCH",
				"exec_result=FAILED requires failure_class not None (协议 §5.3)"))
		}
		fcs, ok := fc.(string)
		if !ok {
			panic(newCodecError("PAYLOAD_SCHEMA_MISMATCH",
				"failure_class must be string when exec_result=FAILED"))
		}
		if !reasonClasses[fcs] {
			panic(newCodecError("PAYLOAD_SCHEMA_MISMATCH",
				"failure_class must be ReasonClass enum, got "+asString(fc)))
		}
	} else {
		if fc != nil {
			panic(newCodecError("PAYLOAD_SCHEMA_MISMATCH",
				fmt.Sprintf("exec_result=%s requires failure_class=None (协议 §5.3)", er)))
		}
	}
}

func validatePayload(eventKind string, payload map[string]interface{}) {
	if !eventKinds[eventKind] {
		panic(newCodecError("UNKNOWN_EVENT_KIND",
			fmt.Sprintf("unknown event_kind: %q", eventKind)))
	}
	switch eventKind {
	case "RULE_SOURCE_ACTIVATED":
		validatePayloadRuleSourceActivated(payload)
	case "RULE_SOURCE_STALE", "RULE_SOURCE_DEGRADED":
		validatePayloadRuleSourceHealth(payload)
	case "RULE_APPLIED", "RULE_BLOCKED", "RULE_FAILED":
		validatePayloadRuleExec(payload)
	}
}

func validateEnvelopeDict(obj map[string]interface{}) {
	if missing := missingFields(obj, envelopeRequiredFields); len(missing) > 0 {
		panic(newCodecError("MALFORMED_ENVELOPE",
			"missing required fields: "+fmt.Sprintf("%v", missing)))
	}
	if unknown := extraFields(obj, envelopeRequiredFields); len(unknown) > 0 {
		panic(newCodecError("MALFORMED_ENVELOPE",
			"unknown fields not allowed (received_at 不再是 ingress 字段, "+
				"协议 BUG 收口后 7 字段): "+fmt.Sprintf("%v", unknown)))
	}
	validateProtocolVersion(obj)
	ek, ok := obj["event_kind"].(string)
	if !ok || !eventKinds[ek] {
		panic(newCodecError("UNKNOWN_EVENT_KIND",
			fmt.Sprintf("unknown event_kind: %v", obj["event_kind"])))
	}
	validateUUID("instance_id", obj["instance_id"])
	validateInt64("startup_epoch", obj["startup_epoch"])
	validateInt64("sequence", obj["sequence"])
	validateISO8601UTCMicro("captured_at", obj["captured_at"])
	ep, ok := obj["event_payload"].(map[string]interface{})
	if !ok {
		panic(newCodecError("MALFORMED_ENVELOPE", "event_payload must be a JSON object"))
	}
	validatePayload(ek, ep)
}

func DecodeEnvelope(raw []byte) (obj map[string]interface{}, err error) {
	if len(raw) > EnvelopeMaxSizeBytes {
		return nil, newCodecError("ENVELOPE_TOO_LARGE",
			fmt.Sprintf("envelope exceeds %d bytes (actual: %d)",
				EnvelopeMaxSizeBytes, len(raw)))
	}
	decoded := map[string]interface{}{}
	if uerr := json.Unmarshal(raw, &decoded); uerr != nil {
		return nil, newCodecError("MALFORMED_ENVELOPE", "invalid JSON: "+uerr.Error())
	}
	defer func() {
		if r := recover(); r != nil {
			if ce, ok := r.(*CodecError); ok {
				err = ce
			} else {
				err = newCodecError("MALFORMED_ENVELOPE", fmt.Sprintf("unexpected: %v", r))
			}
		}
	}()
	validateEnvelopeDict(decoded)
	return decoded, nil
}

func EncodeEnvelope(obj map[string]interface{}) (raw []byte, err error) {
	defer func() {
		if r := recover(); r != nil {
			if ce, ok := r.(*CodecError); ok {
				err = ce
			} else {
				err = newCodecError("MALFORMED_ENVELOPE", fmt.Sprintf("unexpected: %v", r))
			}
		}
	}()
	validateEnvelopeDict(obj)
	kind := obj["event_kind"].(string)
	ep := obj["event_payload"].(map[string]interface{})
	out := map[string]interface{}{
		"protocol_version": obj["protocol_version"],
		"event_kind":       kind,
		"event_payload":    canonicalPayload(kind, ep),
		"instance_id":      obj["instance_id"],
		"startup_epoch":    int64(obj["startup_epoch"].(float64)),
		"sequence":         int64(obj["sequence"].(float64)),
		"captured_at":      obj["captured_at"],
	}
	raw, err = json.Marshal(out)
	if err != nil {
		return nil, newCodecError("MALFORMED_ENVELOPE", "encode failed: "+err.Error())
	}
	if len(raw) > EnvelopeMaxSizeBytes {
		return nil, newCodecError("ENVELOPE_TOO_LARGE",
			fmt.Sprintf("envelope exceeds %d bytes (actual: %d)",
				EnvelopeMaxSizeBytes, len(raw)))
	}
	return raw, nil
}

func canonicalPayload(kind string, payload map[string]interface{}) map[string]interface{} {
	out := make(map[string]interface{}, len(payload))
	switch kind {
	case "RULE_SOURCE_ACTIVATED":
		if v, ok := payload["source_id"]; ok {
			out["source_id"] = v
		}
		if v, ok := payload["rule_version_epoch"]; ok {
			out["rule_version_epoch"] = int64(v.(float64))
		}
		if v, ok := payload["rule_version_revision"]; ok {
			out["rule_version_revision"] = int64(v.(float64))
		}
		if v, ok := payload["rule_version_checksum"]; ok {
			out["rule_version_checksum"] = v
		}
	case "RULE_SOURCE_STALE", "RULE_SOURCE_DEGRADED":
		if v, ok := payload["source_id"]; ok {
			out["source_id"] = v
		}
		if v, ok := payload["health_class"]; ok {
			out["health_class"] = v
		}
		if v, ok := payload["reason_class"]; ok {
			out["reason_class"] = v
		}
		if v, ok := payload["reason_message"]; ok {
			out["reason_message"] = v
		}
		if v, ok := payload["rule_version_epoch"]; ok {
			out["rule_version_epoch"] = int64(v.(float64))
		}
		if v, ok := payload["rule_version_revision"]; ok {
			out["rule_version_revision"] = int64(v.(float64))
		}
		if v, ok := payload["rule_version_checksum"]; ok {
			out["rule_version_checksum"] = v
		}
	case "RULE_APPLIED", "RULE_BLOCKED", "RULE_FAILED":
		if v, ok := payload["source_id"]; ok {
			out["source_id"] = v
		}
		if v, ok := payload["rule_id"]; ok {
			out["rule_id"] = v
		}
		if v, ok := payload["rule_version_epoch"]; ok {
			out["rule_version_epoch"] = int64(v.(float64))
		}
		if v, ok := payload["rule_version_revision"]; ok {
			out["rule_version_revision"] = int64(v.(float64))
		}
		if v, ok := payload["rule_version_checksum"]; ok {
			out["rule_version_checksum"] = v
		}
		if v, ok := payload["exec_result"]; ok {
			out["exec_result"] = v
		}
		if v, ok := payload["failure_class"]; ok {
			out["failure_class"] = v
		}
	}
	return out
}

func validateBatchDict(obj map[string]interface{}) {
	if missing := missingFields(obj, batchRequiredFields); len(missing) > 0 {
		panic(newCodecError("MALFORMED_ENVELOPE",
			"batch missing required fields: "+fmt.Sprintf("%v", missing)))
	}
	if unknown := extraFields(obj, batchRequiredFields); len(unknown) > 0 {
		panic(newCodecError("MALFORMED_ENVELOPE",
			"batch unknown fields not allowed: "+fmt.Sprintf("%v", unknown)))
	}
	validateProtocolVersion(obj)
	validateUUID("instance_id", obj["instance_id"])
	validateInt64("startup_epoch", obj["startup_epoch"])
	validateUUID("batch_id", obj["batch_id"])
	validateISO8601UTCMicro("sent_at", obj["sent_at"])
	events, ok := obj["events"].([]interface{})
	if !ok {
		panic(newCodecError("MALFORMED_ENVELOPE", "events must be a JSON array"))
	}
	if len(events) < 1 || len(events) > BatchMaxEvents {
		panic(newCodecError("MALFORMED_ENVELOPE",
			fmt.Sprintf("events.length must be in [1, %d], got %d",
				BatchMaxEvents, len(events))))
	}
	for i, ev := range events {
		evMap, ok := ev.(map[string]interface{})
		if !ok {
			panic(newCodecError("MALFORMED_ENVELOPE",
				fmt.Sprintf("events[%d] must be a JSON object", i)))
		}
		if evMap["protocol_version"] != obj["protocol_version"] {
			panic(newCodecError("MALFORMED_ENVELOPE",
				fmt.Sprintf("events[%d].protocol_version != batch.protocol_version (禁止混装, 协议 §7.2)", i)))
		}
		if evMap["instance_id"] != obj["instance_id"] {
			panic(newCodecError("MALFORMED_ENVELOPE",
				fmt.Sprintf("events[%d].instance_id != batch.instance_id (禁止混装, 协议 §7.2)", i)))
		}
		if compareInt64(evMap["startup_epoch"], obj["startup_epoch"]) != 0 {
			panic(newCodecError("MALFORMED_ENVELOPE",
				fmt.Sprintf("events[%d].startup_epoch != batch.startup_epoch (禁止混装, 协议 §7.2)", i)))
		}
		evRaw, err := json.Marshal(evMap)
		if err != nil {
			panic(newCodecError("MALFORMED_ENVELOPE",
				fmt.Sprintf("events[%d] not encodable: %s", i, err.Error())))
		}
		if len(evRaw) > EnvelopeMaxSizeBytes {
			panic(newCodecError("ENVELOPE_TOO_LARGE",
				fmt.Sprintf("events[%d] exceeds %d bytes (actual: %d)",
					i, EnvelopeMaxSizeBytes, len(evRaw))))
		}
	}
	validateInt64("dropped_count", obj["dropped_count"])
}

func DecodeBatch(raw []byte) (obj map[string]interface{}, err error) {
	if len(raw) > BatchMaxSizeBytes {
		return nil, newCodecError("BATCH_TOO_LARGE",
			fmt.Sprintf("batch exceeds %d bytes (actual: %d)",
				BatchMaxSizeBytes, len(raw)))
	}
	decoded := map[string]interface{}{}
	if uerr := json.Unmarshal(raw, &decoded); uerr != nil {
		return nil, newCodecError("MALFORMED_ENVELOPE", "invalid JSON: "+uerr.Error())
	}
	defer func() {
		if r := recover(); r != nil {
			if ce, ok := r.(*CodecError); ok {
				err = ce
			} else {
				err = newCodecError("MALFORMED_ENVELOPE", fmt.Sprintf("unexpected: %v", r))
			}
		}
	}()
	validateBatchDict(decoded)
	return decoded, nil
}

func EncodeBatch(obj map[string]interface{}) (raw []byte, err error) {
	defer func() {
		if r := recover(); r != nil {
			if ce, ok := r.(*CodecError); ok {
				err = ce
			} else {
				err = newCodecError("MALFORMED_ENVELOPE", fmt.Sprintf("unexpected: %v", r))
			}
		}
	}()
	validateBatchDict(obj)
	eventsRaw, _ := obj["events"].([]interface{})
	eventsOut := make([]interface{}, 0, len(eventsRaw))
	for _, ev := range eventsRaw {
		evMap, ok := ev.(map[string]interface{})
		if !ok {
			panic(newCodecError("MALFORMED_ENVELOPE", "events[i] not a JSON object"))
		}
		kind, _ := evMap["event_kind"].(string)
		ep, _ := evMap["event_payload"].(map[string]interface{})
		eventsOut = append(eventsOut, map[string]interface{}{
			"protocol_version": evMap["protocol_version"],
			"event_kind":       kind,
			"event_payload":    canonicalPayload(kind, ep),
			"instance_id":      evMap["instance_id"],
			"startup_epoch":    int64(evMap["startup_epoch"].(float64)),
			"sequence":         int64(evMap["sequence"].(float64)),
			"captured_at":      evMap["captured_at"],
		})
	}
	out := map[string]interface{}{
		"protocol_version": obj["protocol_version"],
		"instance_id":      obj["instance_id"],
		"startup_epoch":    int64(obj["startup_epoch"].(float64)),
		"batch_id":         obj["batch_id"],
		"sent_at":          obj["sent_at"],
		"events":           eventsOut,
		"dropped_count":    int64(obj["dropped_count"].(float64)),
	}
	raw, err = json.Marshal(out)
	if err != nil {
		return nil, newCodecError("MALFORMED_ENVELOPE", "encode failed: "+err.Error())
	}
	if len(raw) > BatchMaxSizeBytes {
		return nil, newCodecError("BATCH_TOO_LARGE",
			fmt.Sprintf("batch exceeds %d bytes (actual: %d)",
				BatchMaxSizeBytes, len(raw)))
	}
	return raw, nil
}

func validateAckDict(obj map[string]interface{}) {
	if missing := missingFields(obj, ackRequiredFields); len(missing) > 0 {
		panic(newCodecError("MALFORMED_ENVELOPE",
			"ack missing required fields: "+fmt.Sprintf("%v", missing)))
	}
	if unknown := extraFields(obj, ackRequiredFields); len(unknown) > 0 {
		panic(newCodecError("MALFORMED_ENVELOPE",
			"ack unknown fields not allowed: "+fmt.Sprintf("%v", unknown)))
	}
	validateProtocolVersion(obj)
	validateUUID("batch_id", obj["batch_id"])
	validateISO8601UTCMicro("received_at", obj["received_at"])
	seqs, ok := obj["ack_sequences"].([]interface{})
	if !ok || len(seqs) != 1 {
		panic(newCodecError("MALFORMED_ENVELOPE",
			"ack_sequences must be a JSON array of length 1"))
	}
	seq, ok := seqs[0].(map[string]interface{})
	if !ok {
		panic(newCodecError("MALFORMED_ENVELOPE",
			"ack_sequences[0] must be a JSON object"))
	}
	validateUUID("ack_sequences[0].instance_id", seq["instance_id"])
	validateInt64("ack_sequences[0].startup_epoch", seq["startup_epoch"])
	validateInt64("ack_sequences[0].max_contiguous_sequence", seq["max_contiguous_sequence"])
	validateInt64("duplicate_count", obj["duplicate_count"])
}

func DecodeAck(raw []byte) (obj map[string]interface{}, err error) {
	decoded := map[string]interface{}{}
	if uerr := json.Unmarshal(raw, &decoded); uerr != nil {
		return nil, newCodecError("MALFORMED_ENVELOPE", "invalid JSON: "+uerr.Error())
	}
	defer func() {
		if r := recover(); r != nil {
			if ce, ok := r.(*CodecError); ok {
				err = ce
			} else {
				err = newCodecError("MALFORMED_ENVELOPE", fmt.Sprintf("unexpected: %v", r))
			}
		}
	}()
	validateAckDict(decoded)
	return decoded, nil
}

func EncodeAck(obj map[string]interface{}) (raw []byte, err error) {
	defer func() {
		if r := recover(); r != nil {
			if ce, ok := r.(*CodecError); ok {
				err = ce
			} else {
				err = newCodecError("MALFORMED_ENVELOPE", fmt.Sprintf("unexpected: %v", r))
			}
		}
	}()
	validateAckDict(obj)
	seqs, _ := obj["ack_sequences"].([]interface{})
	seq, _ := seqs[0].(map[string]interface{})
	out := map[string]interface{}{
		"protocol_version": obj["protocol_version"],
		"batch_id":         obj["batch_id"],
		"received_at":      obj["received_at"],
		"ack_sequences": []interface{}{
			map[string]interface{}{
				"instance_id":             seq["instance_id"],
				"startup_epoch":           int64(seq["startup_epoch"].(float64)),
				"max_contiguous_sequence": int64(seq["max_contiguous_sequence"].(float64)),
			},
		},
		"duplicate_count": int64(obj["duplicate_count"].(float64)),
	}
	raw, err = json.Marshal(out)
	if err != nil {
		return nil, newCodecError("MALFORMED_ENVELOPE", "encode failed: "+err.Error())
	}
	return raw, nil
}

func validateErrorDict(obj map[string]interface{}) {
	if missing := missingFields(obj, errorRequiredFields); len(missing) > 0 {
		panic(newCodecError("MALFORMED_ENVELOPE",
			"error missing required fields: "+fmt.Sprintf("%v", missing)))
	}
	if unknown := extraFields(obj, errorRequiredFields); len(unknown) > 0 {
		panic(newCodecError("MALFORMED_ENVELOPE",
			"error unknown fields not allowed: "+fmt.Sprintf("%v", unknown)))
	}
	validateProtocolVersion(obj)
	ec, ok := obj["error_code"].(string)
	if !ok || !errorCodes[ec] {
		panic(newCodecError("MALFORMED_ENVELOPE",
			"unknown error_code: "+asString(obj["error_code"])))
	}
	msg, ok := obj["message"].(string)
	if !ok {
		panic(newCodecError("MALFORMED_ENVELOPE", "message must be string"))
	}
	if len(msg) > ErrorMessageMaxLen {
		panic(newCodecError("MALFORMED_ENVELOPE",
			fmt.Sprintf("message exceeds %d bytes", ErrorMessageMaxLen)))
	}
	d, ok := obj["details"]
	if !ok {
		panic(newCodecError("MALFORMED_ENVELOPE", "details must be present (null or object)"))
	}
	if d != nil {
		if _, ok := d.(map[string]interface{}); !ok {
			panic(newCodecError("MALFORMED_ENVELOPE", "details must be a JSON object or null"))
		}
	}
}

func DecodeErrorEnvelope(raw []byte) (obj map[string]interface{}, err error) {
	decoded := map[string]interface{}{}
	if uerr := json.Unmarshal(raw, &decoded); uerr != nil {
		return nil, newCodecError("MALFORMED_ENVELOPE", "invalid JSON: "+uerr.Error())
	}
	defer func() {
		if r := recover(); r != nil {
			if ce, ok := r.(*CodecError); ok {
				err = ce
			} else {
				err = newCodecError("MALFORMED_ENVELOPE", fmt.Sprintf("unexpected: %v", r))
			}
		}
	}()
	validateErrorDict(decoded)
	return decoded, nil
}

func EncodeErrorEnvelope(obj map[string]interface{}) (raw []byte, err error) {
	defer func() {
		if r := recover(); r != nil {
			if ce, ok := r.(*CodecError); ok {
				err = ce
			} else {
				err = newCodecError("MALFORMED_ENVELOPE", fmt.Sprintf("unexpected: %v", r))
			}
		}
	}()
	validateErrorDict(obj)
	d := obj["details"]
	if d == nil {
		out := map[string]interface{}{
			"protocol_version": obj["protocol_version"],
			"error_code":       obj["error_code"],
			"message":          obj["message"],
			"details":          nil,
		}
		raw, err = json.Marshal(out)
		return
	}
	dm := d.(map[string]interface{})
	detailsOut := make(map[string]interface{}, 2)
	if v, ok := dm["field"]; ok {
		detailsOut["field"] = v
	}
	if v, ok := dm["got_type"]; ok {
		detailsOut["got_type"] = v
	}
	out := map[string]interface{}{
		"protocol_version": obj["protocol_version"],
		"error_code":       obj["error_code"],
		"message":          obj["message"],
		"details":          detailsOut,
	}
	raw, err = json.Marshal(out)
	return
}

func sameKeys(m map[string]interface{}, required []string) bool {
	if len(m) != len(required) {
		return false
	}
	have := make(map[string]bool, len(m))
	for k := range m {
		have[k] = true
	}
	for _, r := range required {
		if !have[r] {
			return false
		}
	}
	return true
}

func keysOf(m map[string]interface{}) []string {
	out := make([]string, 0, len(m))
	for k := range m {
		out = append(out, k)
	}
	sort.Strings(out)
	return out
}

func keysOfBool(m map[string]bool) []string {
	out := make([]string, 0, len(m))
	for k := range m {
		out = append(out, k)
	}
	sort.Strings(out)
	return out
}

func missingFields(obj map[string]interface{}, required map[string]bool) []string {
	missing := make([]string, 0)
	for k := range required {
		if _, ok := obj[k]; !ok {
			missing = append(missing, k)
		}
	}
	sort.Strings(missing)
	return missing
}

func extraFields(obj map[string]interface{}, required map[string]bool) []string {
	extra := make([]string, 0)
	for k := range obj {
		if !required[k] {
			extra = append(extra, k)
		}
	}
	sort.Strings(extra)
	return extra
}

func asString(v interface{}) string {
	if v == nil {
		return "null"
	}
	if s, ok := v.(string); ok {
		return s
	}
	return fmt.Sprintf("%v", v)
}

func compareInt64(a, b interface{}) int {
	af, aok := a.(float64)
	bf, bok := b.(float64)
	if !aok || !bok {
		return -1
	}
	if int64(af) < int64(bf) {
		return -1
	}
	if int64(af) > int64(bf) {
		return 1
	}
	return 0
}

func errIsCode(err error, code string) bool {
	if err == nil {
		return false
	}
	var ce *CodecError
	if errors.As(err, &ce) {
		return ce.Code == code
	}
	return false
}

package main

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"sync/atomic"
	"unicode/utf8"

	"github.com/alibaba/sentinel-golang/core/flow"
)

type goFlowRuleV1 struct {
	Resource               string      `json:"resource"`
	Threshold              json.Number `json:"threshold"`
	StatIntervalInMs       uint32      `json:"statIntervalInMs"`
	TokenCalculateStrategy uint32      `json:"tokenCalculateStrategy"`
	ControlBehavior        uint32      `json:"controlBehavior"`
	RelationStrategy       uint32      `json:"relationStrategy"`
	RefResource            string      `json:"refResource"`
}

type appliedGoSnapshot struct {
	RuleCount            int
	SourceBytesSHA256    string
	CanonicalRulesSHA256 string
	MemberFingerprints   []string
	ManagedPublication   *goManagedPublicationProvenance
}

type goManagedPublicationProvenance struct {
	BindingID       string
	PublicationID   string
	TargetVersionID string
	Sequence        int64
	PayloadSHA256   string
	RulePayload     string
}

var activeGoRuleSnapshot atomic.Pointer[appliedGoSnapshot]

func decodeGoFlowRuleV1(content string) ([]*flow.Rule, appliedGoSnapshot, error) {
	if content == "" || len([]byte(content)) > 65_536 || !utf8.ValidString(content) {
		return nil, appliedGoSnapshot{}, errors.New("rule snapshot is empty or oversized")
	}
	if !hasUniqueJSONKeys([]byte(content)) {
		return nil, appliedGoSnapshot{}, errors.New("rule snapshot has duplicate fields or invalid JSON")
	}
	decoder := json.NewDecoder(bytes.NewBufferString(content))
	decoder.DisallowUnknownFields()
	decoder.UseNumber()
	var candidates []goFlowRuleV1
	if err := decoder.Decode(&candidates); err != nil {
		return nil, appliedGoSnapshot{}, errors.New("rule snapshot is invalid")
	}
	var trailing any
	if err := decoder.Decode(&trailing); err != io.EOF {
		return nil, appliedGoSnapshot{}, errors.New("rule snapshot has trailing data")
	}
	rules := make([]*flow.Rule, 0, len(candidates))
	resources := make(map[string]struct{}, len(candidates))
	fingerprints := make([]string, 0, len(candidates))
	for _, candidate := range candidates {
		threshold, err := normalizedGoThreshold(candidate.Threshold)
		if strings.TrimSpace(candidate.Resource) == "" || candidate.Resource != strings.TrimSpace(candidate.Resource) ||
			!utf8.ValidString(candidate.Resource) || len([]byte(candidate.Resource)) > 200 ||
			candidate.StatIntervalInMs != 1000 ||
			candidate.TokenCalculateStrategy != uint32(flow.Direct) ||
			candidate.ControlBehavior != uint32(flow.Reject) || candidate.RelationStrategy != uint32(flow.CurrentResource) ||
			candidate.RefResource != "" || err != nil {
			return nil, appliedGoSnapshot{}, errors.New("rule snapshot exceeds the supported Go flow profile")
		}
		if _, exists := resources[candidate.Resource]; exists {
			return nil, appliedGoSnapshot{}, errors.New("rule snapshot contains duplicate resources")
		}
		resources[candidate.Resource] = struct{}{}
		value, _ := strconv.ParseFloat(threshold, 64)
		fingerprints = append(fingerprints, goFlowMemberFingerprint(candidate.Resource, threshold))
		rules = append(rules, &flow.Rule{
			Resource:               candidate.Resource,
			Threshold:              value,
			StatIntervalInMs:       candidate.StatIntervalInMs,
			TokenCalculateStrategy: flow.Direct,
			ControlBehavior:        flow.Reject,
			RelationStrategy:       flow.CurrentResource,
		})
	}
	digest := sha256.Sum256([]byte(content))
	sort.Strings(fingerprints)
	canonical := "sentinel-flow-snapshot-v1\n" + strings.Join(fingerprints, "\n")
	if len(fingerprints) > 0 {
		canonical += "\n"
	}
	canonicalDigest := sha256.Sum256([]byte(canonical))
	return rules, appliedGoSnapshot{
		RuleCount: len(rules), SourceBytesSHA256: hex.EncodeToString(digest[:]),
		CanonicalRulesSHA256: hex.EncodeToString(canonicalDigest[:]), MemberFingerprints: fingerprints,
	}, nil
}

func normalizedGoThreshold(number json.Number) (string, error) {
	if number == "" {
		return "", errors.New("threshold is required")
	}
	raw := number.String()
	if !goRawThresholdPattern.MatchString(raw) {
		return "", errors.New("threshold must use plain decimal notation")
	}
	if strings.Contains(raw, ".") {
		raw = strings.TrimRight(raw, "0")
		raw = strings.TrimSuffix(raw, ".")
	}
	value, err := strconv.ParseFloat(raw, 64)
	if err != nil || math.IsNaN(value) || math.IsInf(value, 0) || value <= 0 || value > 1_000_000_000 {
		return "", errors.New("threshold is outside the supported range")
	}
	normalized := strconv.FormatFloat(value, 'f', -1, 64)
	if !goThresholdPattern.MatchString(normalized) {
		return "", errors.New("threshold precision is unsupported")
	}
	return normalized, nil
}

var goThresholdPattern = regexp.MustCompile(`^(?:0|[1-9][0-9]*)(?:\.[0-9]{1,6})?$`)
var goRawThresholdPattern = regexp.MustCompile(`^(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$`)

func goFlowMemberFingerprint(resource, threshold string) string {
	resourceLength := len([]byte(resource))
	canonical := "sentinel-flow-member-v1\n" + strconv.Itoa(resourceLength) + ":" + resource + "\n" +
		strconv.Itoa(len(threshold)) + ":" + threshold + "\n"
	digest := sha256.Sum256([]byte(canonical))
	return hex.EncodeToString(digest[:])
}

func applyGoFlowSnapshot(content string) (appliedGoSnapshot, error) {
	rules, snapshot, err := decodeGoFlowRuleV1(content)
	if err != nil {
		return appliedGoSnapshot{}, fmt.Errorf("decode/apply flow snapshot: %w", err)
	}
	if _, err := flow.LoadRules(rules); err != nil {
		return appliedGoSnapshot{}, errors.New("official Sentinel Go rejected the flow snapshot")
	}
	activeGoRuleSnapshot.Store(&snapshot)
	return snapshot, nil
}

func applyGoManagedFlowSnapshot(content, expectedBindingID, expectedProfileID string) (appliedGoSnapshot, error) {
	envelope, err := decodeManagedRuleEnvelopeV1(content, expectedBindingID, expectedProfileID)
	if err != nil {
		return appliedGoSnapshot{}, fmt.Errorf("decode managed flow envelope: %w", err)
	}
	sequence, _ := strconv.ParseInt(envelope.PublicationSequence.String(), 10, 64)
	current := activeGoRuleSnapshot.Load()
	if current != nil && current.ManagedPublication != nil {
		previous := current.ManagedPublication
		if sequence > previous.Sequence && envelope.PublicationID == previous.PublicationID {
			return appliedGoSnapshot{}, errors.New("managed publication id cannot be reused")
		}
		if sequence < previous.Sequence {
			return appliedGoSnapshot{}, errors.New("managed publication sequence is stale")
		}
		if sequence == previous.Sequence {
			if envelope.BindingID == previous.BindingID && envelope.PublicationID == previous.PublicationID &&
				envelope.TargetVersionID == previous.TargetVersionID && envelope.PayloadSHA256 == previous.PayloadSHA256 &&
				envelope.RulePayload == previous.RulePayload {
				return *current, nil
			}
			return appliedGoSnapshot{}, errors.New("managed publication sequence conflicts")
		}
	}
	rules, snapshot, err := decodeGoFlowRuleV1(envelope.RulePayload)
	if err != nil {
		return appliedGoSnapshot{}, fmt.Errorf("decode managed flow payload: %w", err)
	}
	if _, err := flow.LoadRules(rules); err != nil {
		return appliedGoSnapshot{}, errors.New("official Sentinel Go rejected the managed flow snapshot")
	}
	snapshot.ManagedPublication = &goManagedPublicationProvenance{
		BindingID: envelope.BindingID, PublicationID: envelope.PublicationID,
		TargetVersionID: envelope.TargetVersionID, Sequence: sequence,
		PayloadSHA256: envelope.PayloadSHA256, RulePayload: envelope.RulePayload,
	}
	sourceDigest := sha256.Sum256([]byte(content))
	snapshot.SourceBytesSHA256 = hex.EncodeToString(sourceDigest[:])
	activeGoRuleSnapshot.Store(&snapshot)
	return snapshot, nil
}

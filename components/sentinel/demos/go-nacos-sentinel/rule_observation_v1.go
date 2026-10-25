package main

import (
	"bytes"
	"encoding/json"
	"errors"
	"io"
	"log"
	"net/http"
	"regexp"
	"strings"
	"sync"
	"time"
)

const ruleObservationV1Protocol = "atlas-richie.sentinel.rule-load-observation/v1"

var ruleObservationIDPattern = regexp.MustCompile(`^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$`)

type observationMember struct {
	RuleKind          string `json:"rule_kind"`
	FingerprintSHA256 string `json:"fingerprint_sha256"`
}

type observationSnapshot struct {
	SourceRevision       *string             `json:"source_revision"`
	SourceBytesSHA256    *string             `json:"source_bytes_sha256"`
	CanonicalRulesSHA256 string              `json:"canonical_rules_sha256"`
	MembershipComplete   bool                `json:"membership_complete"`
	Members              []observationMember `json:"members"`
}

type observationAttempt struct {
	SourceRevision       *string `json:"source_revision"`
	SourceBytesSHA256    *string `json:"source_bytes_sha256"`
	CanonicalRulesSHA256 *string `json:"canonical_rules_sha256"`
	FailureReason        string  `json:"failure_reason"`
}

type observationEvent struct {
	ProtocolVersion string               `json:"protocol_version"`
	ObservationID   string               `json:"observation_id"`
	ProcessEpoch    string               `json:"process_epoch"`
	Sequence        uint64               `json:"sequence"`
	BindingID       string               `json:"binding_id"`
	ProfileID       string               `json:"profile_id"`
	EventKind       string               `json:"event_kind"`
	ActiveSnapshot  *observationSnapshot `json:"active_snapshot"`
	Attempt         *observationAttempt  `json:"attempt"`
	ObservedAt      string               `json:"observed_at"`
}

type ruleObservationNegotiation struct {
	ProtocolVersion    string   `json:"protocol_version"`
	Boundary           string   `json:"boundary"`
	RuntimeVersion     string   `json:"runtime_version"`
	CollectorSupported []string `json:"collector_supported"`
	Compatibility      string   `json:"compatibility"`
	ObservedAt         string   `json:"observed_at"`
}

type ruleObservationReporter struct {
	mu                    sync.Mutex
	client                *http.Client
	baseURL               string
	epoch                 string
	bindingID             string
	profileID             string
	sequence              uint64
	latest                *appliedGoSnapshot
	failure               string
	eventPending          bool
	pendingBody           []byte
	pendingKind           string
	pendingFailure        string
	pendingSnapshotDigest string
	compatible            bool
	logf                  func(string, ...any)
}

func newRuleObservationReporterFromEnvironment(capture *metricsCapture, bindingID, profileID string, logf func(string, ...any)) (*ruleObservationReporter, error) {
	if strings.TrimSpace(bindingID) == "" {
		return nil, nil
	}
	if capture == nil || !ruleObservationIDPattern.MatchString(capture.epoch) ||
		!wireIdentifierPattern.MatchString(bindingID) || !wireIdentifierPattern.MatchString(profileID) {
		return nil, errors.New("rule observation identity is invalid")
	}
	metrics, err := newMetricsReporterFromEnvironment(capture, logf)
	if err != nil || metrics == nil {
		return nil, errors.New("rule observations require an enrolled Metrics V2 transport")
	}
	return &ruleObservationReporter{
		client: metrics.client, baseURL: strings.TrimSuffix(metrics.url, "/api/reporting/v2/snapshots"),
		epoch: capture.epoch, bindingID: bindingID, profileID: profileID,
		logf: logf,
	}, nil
}

func (reporter *ruleObservationReporter) start(initial *appliedGoSnapshot) {
	reporter.mu.Lock()
	reporter.latest = initial
	reporter.eventPending = initial != nil
	reporter.mu.Unlock()
	go func() {
		ticker := time.NewTicker(30 * time.Second)
		defer ticker.Stop()
		for range ticker.C {
			reporter.sendNext()
		}
	}()
	go reporter.sendNext()
}

func (reporter *ruleObservationReporter) applied(snapshot appliedGoSnapshot) {
	reporter.mu.Lock()
	reporter.latest = &snapshot
	reporter.failure = ""
	reporter.eventPending = true
	reporter.mu.Unlock()
}

func (reporter *ruleObservationReporter) failed(reason string) {
	switch reason {
	case "source_unavailable", "decode_rejected", "profile_unsupported", "validation_rejected", "apply_failed":
	default:
		return
	}
	reporter.mu.Lock()
	reporter.failure = reason
	reporter.eventPending = true
	reporter.mu.Unlock()
}

func (reporter *ruleObservationReporter) sendNext() {
	reporter.mu.Lock()
	defer reporter.mu.Unlock()
	if !reporter.compatible && !reporter.negotiateLocked() {
		return
	}
	if len(reporter.pendingBody) == 0 {
		event, err := reporter.nextEventLocked()
		if err != nil {
			return
		}
		reporter.pendingBody, err = json.Marshal(event)
		if err != nil || len(reporter.pendingBody) > 512*1024 {
			reporter.pendingBody = nil
			return
		}
		reporter.pendingKind = event.EventKind
		if event.Attempt != nil {
			reporter.pendingFailure = event.Attempt.FailureReason
		}
		if event.ActiveSnapshot != nil {
			reporter.pendingSnapshotDigest = event.ActiveSnapshot.CanonicalRulesSHA256
		}
	}
	request, err := http.NewRequest(http.MethodPost, reporter.baseURL+"/api/reporting/v1/rule-load-observations", bytes.NewReader(reporter.pendingBody))
	if err != nil {
		return
	}
	request.Header.Set("Content-Type", "application/json")
	request.Header.Set("Accept", "application/json")
	response, err := reporter.client.Do(request)
	if err != nil {
		return
	}
	io.Copy(io.Discard, response.Body)
	response.Body.Close()
	if response.StatusCode != http.StatusNoContent {
		logf := reporter.logf
		if logf == nil {
			logf = log.Printf
		}
		logf("Rule Observation Collector rejected event; response_status=%d; exact event retained for retry", response.StatusCode)
		return
	}
	reporter.pendingBody = nil
	if reporter.pendingKind == "snapshot_failed" && reporter.failure == reporter.pendingFailure {
		reporter.failure = ""
		reporter.eventPending = false
	} else if reporter.pendingKind == "snapshot_applied" && reporter.failure == "" &&
		reporter.latest != nil && reporter.latest.CanonicalRulesSHA256 == reporter.pendingSnapshotDigest {
		reporter.eventPending = false
	}
	reporter.pendingKind = ""
	reporter.pendingFailure = ""
	reporter.pendingSnapshotDigest = ""
}

func (reporter *ruleObservationReporter) negotiateLocked() bool {
	body, err := json.Marshal(map[string]string{"protocol_version": ruleObservationV1Protocol})
	if err != nil {
		return false
	}
	request, err := http.NewRequest(http.MethodPost, reporter.baseURL+"/api/reporting/v1/protocol-negotiations/rule-load-observation", bytes.NewReader(body))
	if err != nil {
		return false
	}
	request.Header.Set("Content-Type", "application/json")
	response, err := reporter.client.Do(request)
	if err != nil {
		return false
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		return false
	}
	decoder := json.NewDecoder(response.Body)
	decoder.DisallowUnknownFields()
	var negotiation ruleObservationNegotiation
	if decoder.Decode(&negotiation) != nil || decoder.Decode(new(any)) != io.EOF ||
		negotiation.ProtocolVersion != "atlas-richie.protocol-negotiation/v1" ||
		negotiation.Boundary != "rule-load-observation" || negotiation.Compatibility != "compatible" {
		return false
	}
	for _, version := range negotiation.CollectorSupported {
		if version == ruleObservationV1Protocol {
			reporter.compatible = true
			return true
		}
	}
	return false
}

func (reporter *ruleObservationReporter) nextEventLocked() (observationEvent, error) {
	if reporter.sequence >= 9_007_199_254_740_991 {
		return observationEvent{}, errors.New("rule observation sequence exhausted")
	}
	reporter.sequence++
	id, err := randomUUIDv4()
	if err != nil {
		return observationEvent{}, err
	}
	event := observationEvent{
		ProtocolVersion: ruleObservationV1Protocol, ObservationID: id, ProcessEpoch: reporter.epoch,
		Sequence: reporter.sequence, BindingID: reporter.bindingID, ProfileID: reporter.profileID,
		EventKind: "heartbeat", ObservedAt: time.Now().UTC().Truncate(time.Millisecond).Format("2006-01-02T15:04:05.000Z"),
	}
	if reporter.latest != nil {
		members := make([]observationMember, 0, len(reporter.latest.MemberFingerprints))
		for _, fingerprint := range reporter.latest.MemberFingerprints {
			members = append(members, observationMember{RuleKind: "flow", FingerprintSHA256: fingerprint})
		}
		event.ActiveSnapshot = &observationSnapshot{
			SourceBytesSHA256:    &reporter.latest.SourceBytesSHA256,
			CanonicalRulesSHA256: reporter.latest.CanonicalRulesSHA256,
			MembershipComplete:   true, Members: members,
		}
	}
	if reporter.failure != "" {
		event.EventKind = "snapshot_failed"
		event.Attempt = &observationAttempt{FailureReason: reporter.failure}
	} else if reporter.eventPending {
		event.EventKind = "snapshot_applied"
	}
	return event, nil
}

var wireIdentifierPattern = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$`)

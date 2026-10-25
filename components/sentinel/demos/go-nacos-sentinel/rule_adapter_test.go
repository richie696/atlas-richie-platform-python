package main

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"

	"github.com/alibaba/sentinel-golang/core/flow"
)

func TestGoRuleAdapterAppliesSupportedSnapshotAndReportsRawDigest(t *testing.T) {
	fixtureBytes, err := os.ReadFile("../../../../foundation/contracts/tests/cross_lang/rule_profile_v1/fixtures/equivalent_flow_snapshots.json")
	if err != nil {
		t.Fatal(err)
	}
	var fixture struct {
		GoSnapshot           string `json:"goSnapshot"`
		MemberFingerprint    string `json:"memberFingerprint"`
		CanonicalRulesSHA256 string `json:"canonicalRulesSha256"`
	}
	if err := json.Unmarshal(fixtureBytes, &fixture); err != nil {
		t.Fatal(err)
	}
	content := fixture.GoSnapshot
	snapshot, err := applyGoFlowSnapshot(content)
	if err != nil {
		t.Fatal(err)
	}
	if snapshot.RuleCount != 1 || len(snapshot.SourceBytesSHA256) != 64 {
		t.Fatalf("unexpected applied snapshot: %#v", snapshot)
	}
	if snapshot.CanonicalRulesSHA256 != fixture.CanonicalRulesSHA256 ||
		len(snapshot.MemberFingerprints) != 1 || snapshot.MemberFingerprints[0] != fixture.MemberFingerprint {
		t.Fatalf("Go profile fingerprints differ from shared V1 vector: %#v", snapshot)
	}
	rules := flow.GetRules()
	if len(rules) != 1 || rules[0].Resource != "GET /api/hello" || rules[0].Threshold != 3 {
		t.Fatalf("official Sentinel manager did not receive rule: %#v", rules)
	}
}

func TestGoManagedFlowApplicationPreservesLastKnownGoodAndProvenance(t *testing.T) {
	payload := `[{"resource":"GET /api/hello","threshold":3,"statIntervalInMs":1000}]`
	accepted, err := applyGoManagedFlowSnapshot(goManagedEnvelopeJSON(t, "publication-2", 2, payload), "binding-01", "sentinel-go-v1")
	if err != nil {
		t.Fatal(err)
	}
	if accepted.ManagedPublication == nil || accepted.ManagedPublication.Sequence != 2 ||
		accepted.ManagedPublication.PublicationID != "publication-2" {
		t.Fatalf("managed provenance missing: %#v", accepted)
	}
	if accepted.SourceBytesSHA256 == accepted.ManagedPublication.PayloadSHA256 {
		t.Fatal("outer envelope source checksum was conflated with target payload checksum")
	}

	replayed, err := applyGoManagedFlowSnapshot(goManagedEnvelopeJSON(t, "publication-2", 2, payload), "binding-01", "sentinel-go-v1")
	if err != nil || replayed.ManagedPublication.PublicationID != "publication-2" {
		t.Fatalf("exact managed replay was not idempotent: %#v, %v", replayed, err)
	}
	for _, candidate := range []string{
		goManagedEnvelopeJSON(t, "publication-1", 1, payload),
		goManagedEnvelopeJSON(t, "publication-conflict", 2, payload),
		goManagedEnvelopeJSON(t, "publication-2", 3, payload),
		goManagedEnvelopeJSON(t, "publication-3", 3, `[{"resource":"GET /api/hello","threshold":0,"statIntervalInMs":1000}]`),
	} {
		if _, err := applyGoManagedFlowSnapshot(candidate, "binding-01", "sentinel-go-v1"); err == nil {
			t.Fatalf("invalid or stale managed candidate accepted: %s", candidate)
		}
		current := activeGoRuleSnapshot.Load()
		if current == nil || current.ManagedPublication == nil || current.ManagedPublication.PublicationID != "publication-2" {
			t.Fatal("rejected managed candidate replaced last-known-good provenance")
		}
	}
	if rules := flow.GetRules(); len(rules) != 1 || rules[0].Threshold != 3 {
		t.Fatalf("rejected managed candidate replaced last-known-good rules: %#v", rules)
	}
}

func TestGoManagedReceiptIsExactTupleAndBoundedLocalEnqueue(t *testing.T) {
	reporter := &rulePublicationReceiptReporter{
		epoch: "f1a4d8b2-9a26-4c5d-a8b7-12e7a5c7d3a1",
		queue: make(chan []byte, 1),
		logf:  func(string, ...any) {},
	}
	snapshot := appliedGoSnapshot{ManagedPublication: &goManagedPublicationProvenance{
		BindingID: "binding-01", PublicationID: "publication-42", TargetVersionID: "version-42",
		Sequence: 42, PayloadSHA256: strings.Repeat("a", 64), RulePayload: "[]",
	}}
	if !reporter.applied(snapshot) {
		t.Fatal("receipt should fit in the bounded queue")
	}
	var receipt map[string]any
	if err := json.Unmarshal(<-reporter.queue, &receipt); err != nil {
		t.Fatal(err)
	}
	if receipt["protocol_version"] != rulePublicationReceiptV1Protocol ||
		receipt["receipt_id"] == "" || receipt["process_epoch"] != reporter.epoch ||
		receipt["sequence"] != float64(1) || receipt["binding_id"] != "binding-01" ||
		receipt["publication_id"] != "publication-42" || receipt["target_version_id"] != "version-42" ||
		receipt["target_payload_sha256"] != strings.Repeat("a", 64) || receipt["state"] != "applied" ||
		receipt["reason"] != nil || receipt["source_revision"] != nil {
		t.Fatalf("unexpected Rule Publication Receipt V1 payload: %#v", receipt)
	}
	if !reporter.applied(snapshot) {
		t.Fatal("second receipt should fit in the bounded queue")
	}
	if reporter.applied(snapshot) {
		t.Fatal("queue-full apply must be visible and must not block")
	}
}

func TestGoManagedReceiptTransportRetriesByteIdenticallyUntilDurableAck(t *testing.T) {
	var received [][]byte
	attempt := 0
	server := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		payload, err := io.ReadAll(request.Body)
		if err != nil {
			t.Fatal(err)
		}
		received = append(received, payload)
		attempt++
		if attempt == 1 {
			writer.WriteHeader(http.StatusServiceUnavailable)
			return
		}
		writer.WriteHeader(http.StatusNoContent)
	}))
	defer server.Close()
	body := []byte(`{"receipt_id":"test","sequence":1}`)
	reporter := &rulePublicationReceiptReporter{client: server.Client(), endpoint: server.URL}
	if reporter.sendExact(body) {
		t.Fatal("503 must not be treated as durable ACK")
	}
	if !reporter.sendExact(body) {
		t.Fatal("204 must acknowledge the exact retried receipt")
	}
	if len(received) != 2 || string(received[0]) != string(body) || string(received[1]) != string(body) {
		t.Fatalf("retry bytes changed: %q", received)
	}
}

func TestGoManagedReceiptConcurrentAdmissionsPreserveSequenceOrder(t *testing.T) {
	const count = 64
	reporter := &rulePublicationReceiptReporter{
		epoch: "f1a4d8b2-9a26-4c5d-a8b7-12e7a5c7d3a1",
		queue: make(chan []byte, count),
		logf:  func(string, ...any) {},
	}
	snapshot := appliedGoSnapshot{ManagedPublication: &goManagedPublicationProvenance{
		BindingID: "binding-01", PublicationID: "publication-42", TargetVersionID: "version-42",
		Sequence: 42, PayloadSHA256: strings.Repeat("a", 64), RulePayload: "[]",
	}}
	var group sync.WaitGroup
	for range count {
		group.Add(1)
		go func() {
			defer group.Done()
			if !reporter.applied(snapshot) {
				t.Error("concurrent receipt should fit in bounded queue")
			}
		}()
	}
	group.Wait()
	for expected := 1; expected <= count; expected++ {
		var receipt struct {
			Sequence int `json:"sequence"`
		}
		if err := json.Unmarshal(<-reporter.queue, &receipt); err != nil {
			t.Fatal(err)
		}
		if receipt.Sequence != expected {
			t.Fatalf("receipt sequence order changed: expected=%d actual=%d", expected, receipt.Sequence)
		}
	}
}

func goManagedEnvelopeJSON(t *testing.T, publicationID string, sequence int64, payload string) string {
	t.Helper()
	digest := sha256.Sum256([]byte(payload))
	content, err := json.Marshal(map[string]any{
		"protocol_version": managedRulePublicationProtocolV1,
		"binding_id":       "binding-01", "publication_id": publicationID,
		"target_version_id": publicationID + "-version", "publication_sequence": sequence,
		"rule_kind": "flow", "profile_id": "sentinel-go-v1",
		"payload_sha256": hex.EncodeToString(digest[:]), "rule_payload": payload,
	})
	if err != nil {
		t.Fatal(err)
	}
	return string(content)
}

func TestGoManagedRuleEnvelopeSharedFixtures(t *testing.T) {
	fixtureDir := "../../../../foundation/contracts/tests/rules/managed_publication_v1/fixtures"
	for _, name := range []string{"valid_empty_rules.json", "valid_utf8_rules.json"} {
		t.Run(name, func(t *testing.T) {
			content, err := os.ReadFile(filepath.Join(fixtureDir, name))
			if err != nil {
				t.Fatal(err)
			}
			envelope, err := decodeManagedRuleEnvelopeV1(string(content), "binding-0"+map[string]string{
				"valid_empty_rules.json": "1", "valid_utf8_rules.json": "2",
			}[name], "sentinel-nacos-flow-v1")
			if err != nil {
				t.Fatal(err)
			}
			if envelope.RuleKind != "flow" || len(envelope.PayloadSHA256) != 64 || envelope.RulePayload == "" {
				t.Fatalf("unexpected decoded envelope: %#v", envelope)
			}
		})
	}
}

func TestGoManagedRuleEnvelopeRejectsInvalidSharedFixtures(t *testing.T) {
	fixtureDir := "../../../../foundation/contracts/tests/rules/managed_publication_v1/fixtures"
	entries, err := os.ReadDir(fixtureDir)
	if err != nil {
		t.Fatal(err)
	}
	for _, entry := range entries {
		if !strings.HasPrefix(entry.Name(), "invalid_") {
			continue
		}
		t.Run(entry.Name(), func(t *testing.T) {
			content, readErr := os.ReadFile(filepath.Join(fixtureDir, entry.Name()))
			if readErr != nil {
				t.Fatal(readErr)
			}
			if _, decodeErr := decodeManagedRuleEnvelopeV1(string(content), "binding-01", "sentinel-nacos-flow-v1"); decodeErr == nil {
				t.Fatalf("invalid shared fixture accepted: %s", entry.Name())
			}
		})
	}
}

func TestGoRuleAdapterRejectsUnknownDuplicateAndUnsupportedSemantics(t *testing.T) {
	valid := `[{"resource":"GET /api/hello","threshold":3,"statIntervalInMs":1000}]`
	if _, err := applyGoFlowSnapshot(valid); err != nil {
		t.Fatal(err)
	}
	active := activeGoRuleSnapshot.Load()
	candidates := []string{
		`[{"resource":"GET /api/hello","threshold":3,"statIntervalInMs":1000,"unknown":true}]`,
		`[{"resource":"GET /api/hello","threshold":3,"threshold":4,"statIntervalInMs":1000}]`,
		`[{"resource":"GET /api/hello","threshold":3,"statIntervalInMs":1000,"tokenCalculateStrategy":1}]`,
		`[{"resource":"GET /api/hello","threshold":3,"statIntervalInMs":1000,"relationStrategy":1}]`,
	}
	for _, content := range candidates {
		if _, err := applyGoFlowSnapshot(content); err == nil {
			t.Fatalf("unsupported snapshot accepted: %s", content)
		}
		if activeGoRuleSnapshot.Load() != active {
			t.Fatal("invalid candidate replaced last-known-good snapshot")
		}
	}
	if rules := flow.GetRules(); len(rules) != 1 || rules[0].Threshold != 3 {
		t.Fatalf("invalid candidate replaced official Sentinel rules: %#v", rules)
	}
}

func TestGoRuleAdapterAllowsExplicitEmptySnapshot(t *testing.T) {
	if _, err := applyGoFlowSnapshot(`[{"resource":"GET /api/hello","threshold":3,"statIntervalInMs":1000}]`); err != nil {
		t.Fatal(err)
	}
	if _, err := applyGoFlowSnapshot(`[]`); err != nil {
		t.Fatal(err)
	}
	if len(flow.GetRules()) != 0 {
		t.Fatalf("explicit empty snapshot did not clear official rules: %#v", flow.GetRules())
	}
}

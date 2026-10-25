package main

import (
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"regexp"
	"strings"
	"testing"
	"time"
)

var utcMicros = regexp.MustCompile(`^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z$`)

func TestMetricsSnapshotUsesFrozenV2Semantics(t *testing.T) {
	capture, err := newMetricsCapture("go-worker-test")
	if err != nil {
		t.Fatal(err)
	}
	capture.record(true, true, false, true, 5*time.Millisecond)
	capture.record(true, false, true, false, 250*time.Millisecond)
	body, err := capture.snapshot()
	if err != nil {
		t.Fatal(err)
	}
	var snapshot metricsSnapshot
	if err := json.Unmarshal(body, &snapshot); err != nil {
		t.Fatal(err)
	}
	if snapshot.ProtocolVersion != metricsV2Protocol || snapshot.ReporterID != "go-worker-test" ||
		!utcMicros.MatchString(snapshot.CapturedAt) || snapshot.Sequence != 1 || snapshot.CaptureElapsedNS == "" {
		t.Fatalf("snapshot identity or time contract mismatch: %#v", snapshot)
	}
	if got := counterValue(snapshot, "http_requests_completed_total"); got != 2 {
		t.Fatalf("completed HTTP count = %d, want 2", got)
	}
	if got := counterValue(snapshot, "sentinel_entries_admitted_total"); got != 1 {
		t.Fatalf("admitted count = %d, want 1", got)
	}
	if got := counterValue(snapshot, "sentinel_entries_blocked_total"); got != 1 {
		t.Fatalf("blocked count = %d, want 1", got)
	}
	if len(snapshot.Histograms) != 1 || snapshot.Histograms[0].SampleCount != 2 ||
		snapshot.Histograms[0].TotalNS != "255000000" || len(snapshot.Histograms[0].BucketCounts) != 13 {
		t.Fatalf("HTTP duration histogram mismatch: %#v", snapshot.Histograms)
	}
	if snapshot.Gauges[0].Quality != "unavailable" || snapshot.Gauges[0].Value != nil {
		t.Fatalf("unsupported process gauge must stay unavailable: %#v", snapshot.Gauges[0])
	}
}

func TestMetricsCaptureDoesNotCountFailedHTTPWriteAsCompleted(t *testing.T) {
	capture, err := newMetricsCapture("go-worker-test")
	if err != nil {
		t.Fatal(err)
	}
	capture.record(false, true, false, false, 20*time.Millisecond)
	body, err := capture.snapshot()
	if err != nil {
		t.Fatal(err)
	}
	var snapshot metricsSnapshot
	if err := json.Unmarshal(body, &snapshot); err != nil {
		t.Fatal(err)
	}
	if got := counterValue(snapshot, "http_requests_completed_total"); got != 0 {
		t.Fatalf("failed response counted as completed: %d", got)
	}
	if got := counterValue(snapshot, "sentinel_entries_admitted_total"); got != 1 {
		t.Fatalf("Sentinel admission fact lost: %d", got)
	}
	if len(snapshot.Histograms) != 1 || snapshot.Histograms[0].SampleCount != 0 ||
		snapshot.Histograms[0].TotalNS != "0" || snapshot.Histograms[0].MinNS != nil ||
		snapshot.Histograms[0].MaxNS != nil {
		t.Fatalf("failed response must preserve an empty RT histogram schema: %#v", snapshot.Histograms)
	}
	for _, bucketCount := range snapshot.Histograms[0].BucketCounts {
		if bucketCount != 0 {
			t.Fatalf("failed response added an RT sample: %#v", snapshot.Histograms[0])
		}
	}
}

func TestMetricsSequenceAdvancesForEachSnapshot(t *testing.T) {
	capture, err := newMetricsCapture("go-worker-test")
	if err != nil {
		t.Fatal(err)
	}
	first, err := capture.snapshot()
	if err != nil {
		t.Fatal(err)
	}
	second, err := capture.snapshot()
	if err != nil {
		t.Fatal(err)
	}
	var a, b metricsSnapshot
	if json.Unmarshal(first, &a) != nil || json.Unmarshal(second, &b) != nil || a.Sequence != 1 || b.Sequence != 2 {
		t.Fatalf("snapshot sequences do not increase: %d, %d", a.Sequence, b.Sequence)
	}
	if len(a.Histograms) != 1 || a.Histograms[0].Name != "http_request_duration" ||
		a.Histograms[0].SampleCount != 0 || a.Histograms[0].TotalNS != "0" ||
		a.Histograms[0].MinNS != nil || a.Histograms[0].MaxNS != nil || len(a.Histograms[0].BucketCounts) != 13 {
		t.Fatalf("initial snapshot must declare the empty RT histogram schema: %#v", a.Histograms)
	}
}

func TestMetricsReceiptParserRejectsDuplicateJSONFields(t *testing.T) {
	if !hasUniqueJSONKeys([]byte(`{"receipt":{"seq":1,"name":"ok"}}`)) {
		t.Fatal("valid nested JSON rejected")
	}
	if hasUniqueJSONKeys([]byte(`{"sequence":1,"sequence":2}`)) {
		t.Fatal("duplicate receipt field accepted")
	}
	if hasUniqueJSONKeys([]byte(`{"receipt":{"name":"a","name":"b"}}`)) {
		t.Fatal("duplicate nested receipt field accepted")
	}
}

func TestMetricsReporterLogsRejectedStatusWithoutSnapshotData(t *testing.T) {
	var messages []string
	server := httptest.NewTLSServer(http.HandlerFunc(func(writer http.ResponseWriter, _ *http.Request) {
		writer.WriteHeader(http.StatusConflict)
	}))
	defer server.Close()
	body := []byte(`{"protocol_version":"atlas-richie.metrics/v2","reporter_id":"private-reporter","startup_epoch":"f1a4d8b2-9a26-4c5d-a8b7-12e7a5c7d3a1","sequence":1}`)
	reporter := &metricsReporter{
		url: server.URL, client: server.Client(),
		logf: func(format string, args ...any) { messages = append(messages, fmt.Sprintf(format, args...)) },
	}

	if reporter.sendExact(body) {
		t.Fatal("409 must not be treated as a durable ACK")
	}
	if len(messages) != 1 || messages[0] != "Metrics V2 durable ACK rejected; response_status=409; exact snapshot retained for retry" {
		t.Fatalf("expected a stable redacted status message, got %#v", messages)
	}
	if strings.Contains(messages[0], "private-reporter") || strings.Contains(messages[0], string(body)) {
		t.Fatal("rejection log must not contain reporter identity or snapshot data")
	}
}

func counterValue(snapshot metricsSnapshot, name string) uint64 {
	for _, counter := range snapshot.Counters {
		if counter.Name == name {
			return counter.Value
		}
	}
	return 0
}

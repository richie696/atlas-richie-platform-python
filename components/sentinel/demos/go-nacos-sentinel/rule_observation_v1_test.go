package main

import (
	"bytes"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"
)

func TestRuleObservationRejectedStatusIsRedactedAndRetriesExactEvent(t *testing.T) {
	var status atomic.Int32
	status.Store(http.StatusConflict)
	var received [][]byte
	server := httptest.NewTLSServer(http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		body, err := io.ReadAll(request.Body)
		if err != nil {
			t.Errorf("read observation request: %v", err)
		}
		received = append(received, body)
		writer.WriteHeader(int(status.Load()))
	}))
	defer server.Close()

	var messages []string
	reporter := &ruleObservationReporter{
		client: server.Client(), baseURL: server.URL,
		epoch:     "f1a4d8b2-9a26-4c5d-a8b7-12e7a5c7d3a1",
		bindingID: "go-binding", profileID: "sentinel-go-v1", compatible: true,
		latest: &appliedGoSnapshot{
			SourceBytesSHA256:    strings.Repeat("a", 64),
			CanonicalRulesSHA256: strings.Repeat("b", 64),
			MemberFingerprints:   []string{strings.Repeat("c", 64)},
		},
		eventPending: true,
		logf:         func(format string, args ...any) { messages = append(messages, fmt.Sprintf(format, args...)) },
	}

	reporter.sendNext()
	if len(reporter.pendingBody) == 0 {
		t.Fatal("rejected observation must remain queued for exact retry")
	}
	if len(messages) != 1 || messages[0] != "Rule Observation Collector rejected event; response_status=409; exact event retained for retry" {
		t.Fatalf("expected a redacted stable rejection status, got %#v", messages)
	}
	if strings.Contains(messages[0], "go-binding") || strings.Contains(messages[0], string(reporter.pendingBody)) {
		t.Fatal("rejection log must not contain binding identity or observation payload")
	}
	firstBody := append([]byte(nil), reporter.pendingBody...)

	status.Store(http.StatusNoContent)
	reporter.sendNext()
	if len(reporter.pendingBody) != 0 || len(received) != 2 || !bytes.Equal(received[0], received[1]) || !bytes.Equal(received[0], firstBody) {
		t.Fatal("retry must resend the exact pending event and clear it only after durable ACK")
	}
}

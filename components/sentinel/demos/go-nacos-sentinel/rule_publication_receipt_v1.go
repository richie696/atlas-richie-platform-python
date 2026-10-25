package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"log"
	"net/http"
	"strings"
	"sync"
	"time"
)

const rulePublicationReceiptV1Protocol = "atlas-richie.sentinel.rule-publication-receipt/v1"

type rulePublicationReceiptReporter struct {
	mu       sync.Mutex
	client   *http.Client
	endpoint string
	epoch    string
	sequence uint64
	queue    chan []byte
	logf     func(string, ...any)
}

func newRulePublicationReceiptReporter(metrics *metricsReporter, capture *metricsCapture, logf func(string, ...any)) (*rulePublicationReceiptReporter, error) {
	if metrics == nil || capture == nil || metrics.client == nil || !ruleObservationIDPattern.MatchString(capture.epoch) {
		return nil, errors.New("managed receipt reporting requires the enrolled Metrics V2 mTLS identity")
	}
	base := strings.TrimSuffix(metrics.url, "/api/reporting/v2/snapshots")
	if base == metrics.url {
		return nil, errors.New("Metrics V2 Collector endpoint is invalid")
	}
	return &rulePublicationReceiptReporter{
		client: metrics.client, endpoint: base + "/api/reporting/v1/rule-publication-receipts",
		epoch: capture.epoch, queue: make(chan []byte, 128), logf: logf,
	}, nil
}

// applied queues immutable receipt bytes without waiting for Collector I/O.
func (reporter *rulePublicationReceiptReporter) applied(snapshot appliedGoSnapshot) bool {
	if snapshot.ManagedPublication == nil {
		return true
	}
	receiptID, err := randomUUIDv4()
	if err != nil {
		return false
	}
	reporter.mu.Lock()
	if reporter.sequence >= 9_007_199_254_740_991 {
		reporter.mu.Unlock()
		return false
	}
	reporter.sequence++
	sequence := reporter.sequence
	publication := snapshot.ManagedPublication
	body, err := json.Marshal(map[string]any{
		"protocol_version": rulePublicationReceiptV1Protocol,
		"receipt_id":       receiptID, "process_epoch": reporter.epoch, "sequence": sequence,
		"binding_id": publication.BindingID, "publication_id": publication.PublicationID,
		"target_version_id": publication.TargetVersionID, "target_payload_sha256": publication.PayloadSHA256,
		"state": "applied", "reason": nil, "source_revision": nil,
		"observed_at": time.Now().UTC().Truncate(time.Millisecond).Format("2006-01-02T15:04:05.000Z"),
	})
	if err != nil {
		reporter.mu.Unlock()
		return false
	}
	select {
	case reporter.queue <- body:
		reporter.mu.Unlock()
		return true
	default:
		reporter.mu.Unlock()
		reporter.logf("Rule Publication Receipt queue full; receipt not retained")
		return false
	}
}

func (reporter *rulePublicationReceiptReporter) run(ctx context.Context) {
	for {
		select {
		case <-ctx.Done():
			return
		case body := <-reporter.queue:
			for {
				if reporter.sendExact(body) {
					break
				}
				timer := time.NewTimer(time.Second)
				select {
				case <-ctx.Done():
					timer.Stop()
					return
				case <-timer.C:
				}
			}
		}
	}
}

func (reporter *rulePublicationReceiptReporter) sendExact(body []byte) bool {
	request, err := http.NewRequest(http.MethodPost, reporter.endpoint, bytes.NewReader(body))
	if err != nil {
		return false
	}
	request.Header.Set("Content-Type", "application/json")
	response, err := reporter.client.Do(request)
	if err != nil {
		reporter.logf("Rule Publication Receipt transport unavailable; exact receipt retained for retry")
		return false
	}
	if response.Body != nil {
		response.Body.Close()
	}
	if response.StatusCode != http.StatusNoContent {
		logf := reporter.logf
		if logf == nil {
			logf = log.Printf
		}
		logf("Rule Publication Receipt Collector rejected event; response_status=%d; exact receipt retained for retry", response.StatusCode)
		return false
	}
	return true
}

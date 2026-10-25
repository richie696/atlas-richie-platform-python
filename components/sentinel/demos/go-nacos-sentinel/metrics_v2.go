package main

import (
	"bytes"
	"context"
	"crypto/rand"
	"crypto/sha256"
	"crypto/tls"
	"crypto/x509"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"regexp"
	"strings"
	"sync"
	"time"
)

const metricsV2Protocol = "atlas-richie.metrics/v2"

var httpDurationBoundaries = []int64{
	1_000_000, 5_000_000, 10_000_000, 25_000_000, 50_000_000, 100_000_000,
	250_000_000, 500_000_000, 1_000_000_000, 2_000_000_000, 5_000_000_000, 10_000_000_000,
}

var receiptTimePattern = regexp.MustCompile(`^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z$`)

type metricsCapture struct {
	mu         sync.Mutex
	started    time.Time
	completed  uint64
	admitted   uint64
	blocked    uint64
	business   uint64
	count      uint64
	totalNanos uint64
	minNanos   uint64
	maxNanos   uint64
	buckets    [13]uint64
	sequence   uint64
	epoch      string
	reporterID string
}

type metricCounter struct {
	Name  string `json:"name"`
	Value uint64 `json:"value"`
}

type metricHistogram struct {
	Name         string   `json:"name"`
	BoundariesNS []int64  `json:"boundaries_ns"`
	BucketCounts []uint64 `json:"bucket_counts"`
	SampleCount  uint64   `json:"sample_count"`
	TotalNS      string   `json:"total_ns"`
	MinNS        *uint64  `json:"min_ns"`
	MaxNS        *uint64  `json:"max_ns"`
}

type metricGauge struct {
	Name    string   `json:"name"`
	Value   *float64 `json:"value"`
	Quality string   `json:"quality"`
}

type metricsSnapshot struct {
	ProtocolVersion  string            `json:"protocol_version"`
	ReporterID       string            `json:"reporter_id"`
	StartupEpoch     string            `json:"startup_epoch"`
	Sequence         uint64            `json:"sequence"`
	CapturedAt       string            `json:"captured_at"`
	CaptureElapsedNS string            `json:"capture_elapsed_ns"`
	Counters         []metricCounter   `json:"counters"`
	Histograms       []metricHistogram `json:"histograms"`
	Gauges           []metricGauge     `json:"gauges"`
}

func newMetricsCapture(reporterID string) (*metricsCapture, error) {
	if strings.TrimSpace(reporterID) == "" || len(reporterID) > 200 || reporterID != strings.TrimSpace(reporterID) {
		return nil, errors.New("reporter identity is invalid")
	}
	epoch, err := randomUUIDv4()
	if err != nil {
		return nil, errors.New("process epoch could not be created")
	}
	return &metricsCapture{started: time.Now(), minNanos: ^uint64(0), epoch: epoch, reporterID: reporterID}, nil
}

// record performs only bounded in-process aggregation; it never does network I/O.
func (capture *metricsCapture) record(completed, admitted, blocked, business bool, elapsed time.Duration) {
	if capture == nil || elapsed < 0 {
		return
	}
	capture.mu.Lock()
	defer capture.mu.Unlock()
	if admitted {
		capture.admitted++
	}
	if blocked {
		capture.blocked++
	}
	if !completed {
		return
	}
	capture.completed++
	if business {
		capture.business++
	}
	nanos := uint64(elapsed.Nanoseconds())
	capture.count++
	capture.totalNanos += nanos
	if nanos < capture.minNanos {
		capture.minNanos = nanos
	}
	if nanos > capture.maxNanos {
		capture.maxNanos = nanos
	}
	index := 0
	for index < len(httpDurationBoundaries) && int64(nanos) > httpDurationBoundaries[index] {
		index++
	}
	capture.buckets[index]++
}

func (capture *metricsCapture) snapshot() ([]byte, error) {
	capture.mu.Lock()
	defer capture.mu.Unlock()
	if capture.sequence >= 9_007_199_254_740_991 {
		return nil, errors.New("metrics sequence exhausted")
	}
	if capture.completed > 9_007_199_254_740_991 || capture.admitted > 9_007_199_254_740_991 ||
		capture.blocked > 9_007_199_254_740_991 || capture.business > 9_007_199_254_740_991 ||
		capture.count > 9_007_199_254_740_991 {
		return nil, errors.New("metrics counter exhausted")
	}
	capture.sequence++
	elapsed := time.Since(capture.started).Nanoseconds()
	if elapsed < 0 {
		return nil, errors.New("monotonic capture time regressed")
	}
	snapshot := metricsSnapshot{
		ProtocolVersion:  metricsV2Protocol,
		ReporterID:       capture.reporterID,
		StartupEpoch:     capture.epoch,
		Sequence:         capture.sequence,
		CapturedAt:       time.Now().UTC().Format("2006-01-02T15:04:05.000000Z"),
		CaptureElapsedNS: fmt.Sprintf("%d", elapsed),
		Counters: []metricCounter{
			{Name: "http_requests_completed_total", Value: capture.completed},
			{Name: "sentinel_entries_admitted_total", Value: capture.admitted},
			{Name: "sentinel_entries_blocked_total", Value: capture.blocked},
			{Name: "business_transactions_completed_total", Value: capture.business},
		},
		Gauges: []metricGauge{
			{Name: "process_cpu_ratio", Quality: "unavailable"},
			{Name: "process_rss_bytes", Quality: "unavailable"},
			{Name: "process_memory_ratio", Quality: "unavailable"},
		},
	}
	var minValue, maxValue *uint64
	if capture.count > 0 {
		min := capture.minNanos
		max := capture.maxNanos
		minValue = &min
		maxValue = &max
	}
	buckets := make([]uint64, len(capture.buckets))
	copy(buckets, capture.buckets[:])
	boundaries := make([]int64, len(httpDurationBoundaries))
	copy(boundaries, httpDurationBoundaries)
	snapshot.Histograms = []metricHistogram{{
		Name: "http_request_duration", BoundariesNS: boundaries, BucketCounts: buckets,
		SampleCount: capture.count, TotalNS: fmt.Sprintf("%d", capture.totalNanos),
		MinNS: minValue, MaxNS: maxValue,
	}}
	body, err := json.Marshal(snapshot)
	if err != nil || len(body) > 65_536 {
		return nil, errors.New("metrics snapshot encoding failed")
	}
	return body, nil
}

type metricsReceipt struct {
	ProtocolVersion string `json:"protocol_version"`
	ReporterID      string `json:"reporter_id"`
	StartupEpoch    string `json:"startup_epoch"`
	Sequence        uint64 `json:"sequence"`
	BodySHA256      string `json:"body_sha256"`
	ReceivedAt      string `json:"received_at"`
}

type metricsReporter struct {
	url      string
	client   *http.Client
	capture  *metricsCapture
	interval time.Duration
	logf     func(string, ...any)
}

func newMetricsReporterFromEnvironment(capture *metricsCapture, logf func(string, ...any)) (*metricsReporter, error) {
	collectorURL := strings.TrimSpace(os.Getenv("METRICS_COLLECTOR_URL"))
	if collectorURL == "" {
		return nil, nil
	}
	parsed, err := url.Parse(collectorURL)
	if err != nil || parsed.Scheme != "https" || parsed.Host == "" || parsed.User != nil || parsed.RawQuery != "" || parsed.Fragment != "" || (parsed.Path != "" && parsed.Path != "/") {
		return nil, errors.New("Metrics V2 Collector URL must be an HTTPS origin")
	}
	clientCert := strings.TrimSpace(os.Getenv("METRICS_CLIENT_CERT"))
	clientKey := strings.TrimSpace(os.Getenv("METRICS_CLIENT_KEY"))
	caPath := strings.TrimSpace(os.Getenv("METRICS_COLLECTOR_CA"))
	if clientCert == "" || clientKey == "" || caPath == "" {
		return nil, errors.New("Metrics V2 client TLS configuration is incomplete")
	}
	cert, err := tls.LoadX509KeyPair(clientCert, clientKey)
	if err != nil {
		return nil, errors.New("Metrics V2 client certificate configuration is invalid")
	}
	caPEM, err := os.ReadFile(caPath)
	if err != nil {
		return nil, errors.New("Metrics V2 Collector CA is unavailable")
	}
	roots := x509.NewCertPool()
	if !roots.AppendCertsFromPEM(caPEM) {
		return nil, errors.New("Metrics V2 Collector CA is invalid")
	}
	transport := &http.Transport{TLSClientConfig: &tls.Config{
		MinVersion: tls.VersionTLS12, Certificates: []tls.Certificate{cert}, RootCAs: roots,
	}}
	client := &http.Client{Transport: transport, Timeout: 5 * time.Second,
		CheckRedirect: func(_ *http.Request, _ []*http.Request) error { return http.ErrUseLastResponse }}
	return &metricsReporter{url: strings.TrimRight(collectorURL, "/") + "/api/reporting/v2/snapshots",
		client: client, capture: capture, interval: time.Second, logf: logf}, nil
}

func (reporter *metricsReporter) run(ctx context.Context) {
	ticker := time.NewTicker(reporter.interval)
	defer ticker.Stop()
	var inFlight []byte
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			if inFlight == nil {
				body, err := reporter.capture.snapshot()
				if err != nil {
					reporter.logf("Metrics V2 snapshot unavailable")
					continue
				}
				inFlight = body
			}
			if reporter.sendExact(inFlight) {
				inFlight = nil
			}
		}
	}
}

func (reporter *metricsReporter) sendExact(body []byte) bool {
	digest := sha256.Sum256(body)
	var expected metricsSnapshot
	if json.Unmarshal(body, &expected) != nil {
		reporter.logf("Metrics V2 snapshot rejected before transport")
		return false
	}
	request, err := http.NewRequest(http.MethodPost, reporter.url, bytes.NewReader(body))
	if err != nil {
		reporter.logf("Metrics V2 request unavailable")
		return false
	}
	request.Header.Set("Content-Type", "application/json")
	request.Header.Set("Accept", "application/json")
	response, err := reporter.client.Do(request)
	if err != nil {
		reporter.logf("Metrics V2 transport unavailable; exact snapshot retained for retry")
		return false
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		reporter.logf("Metrics V2 durable ACK rejected; response_status=%d; exact snapshot retained for retry", response.StatusCode)
		return false
	}
	receiptBody, err := io.ReadAll(io.LimitReader(response.Body, 65_537))
	if err != nil || len(receiptBody) > 65_536 || !hasUniqueJSONKeys(receiptBody) {
		reporter.logf("Metrics V2 durable ACK malformed; exact snapshot retained for retry")
		return false
	}
	decoder := json.NewDecoder(bytes.NewReader(receiptBody))
	decoder.DisallowUnknownFields()
	var receipt metricsReceipt
	if decoder.Decode(&receipt) != nil || receipt.ProtocolVersion != metricsV2Protocol ||
		receipt.ReporterID != expected.ReporterID || receipt.StartupEpoch != expected.StartupEpoch ||
		receipt.Sequence != expected.Sequence || receipt.BodySHA256 != hex.EncodeToString(digest[:]) ||
		!receiptTimePattern.MatchString(receipt.ReceivedAt) {
		reporter.logf("Metrics V2 durable ACK mismatch; exact snapshot retained for retry")
		return false
	}
	var trailing any
	if decoder.Decode(&trailing) != io.EOF {
		reporter.logf("Metrics V2 durable ACK malformed; exact snapshot retained for retry")
		return false
	}
	return true
}

func hasUniqueJSONKeys(body []byte) bool {
	decoder := json.NewDecoder(bytes.NewReader(body))
	decoder.UseNumber()
	if !walkJSONValue(decoder) {
		return false
	}
	_, err := decoder.Token()
	return err == io.EOF
}

func walkJSONValue(decoder *json.Decoder) bool {
	token, err := decoder.Token()
	if err != nil {
		return false
	}
	delimiter, isDelimiter := token.(json.Delim)
	if !isDelimiter {
		return true
	}
	switch delimiter {
	case '{':
		keys := make(map[string]struct{})
		for decoder.More() {
			keyToken, tokenErr := decoder.Token()
			if tokenErr != nil {
				return false
			}
			key, valid := keyToken.(string)
			if !valid {
				return false
			}
			if _, exists := keys[key]; exists {
				return false
			}
			keys[key] = struct{}{}
			if !walkJSONValue(decoder) {
				return false
			}
		}
		closing, closeErr := decoder.Token()
		return closeErr == nil && closing == json.Delim('}')
	case '[':
		for decoder.More() {
			if !walkJSONValue(decoder) {
				return false
			}
		}
		closing, closeErr := decoder.Token()
		return closeErr == nil && closing == json.Delim(']')
	default:
		return false
	}
}

func randomUUIDv4() (string, error) {
	var value [16]byte
	if _, err := rand.Read(value[:]); err != nil {
		return "", err
	}
	value[6] = (value[6] & 0x0f) | 0x40
	value[8] = (value[8] & 0x3f) | 0x80
	encoded := hex.EncodeToString(value[:])
	return encoded[:8] + "-" + encoded[8:12] + "-" + encoded[12:16] + "-" + encoded[16:20] + "-" + encoded[20:], nil
}

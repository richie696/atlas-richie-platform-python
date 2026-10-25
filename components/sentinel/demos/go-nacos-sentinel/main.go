package main

import (
	"context"
	"fmt"
	"log"
	"net"
	"net/http"
	"os"
	"strconv"
	"strings"
	"time"

	"github.com/alibaba/sentinel-golang/api"
	"github.com/alibaba/sentinel-golang/core/base"
)

const resource = "GET /api/hello"

func main() {
	if err := api.InitDefault(); err != nil {
		log.Fatalf("initialize Sentinel: %v", err)
	}

	ruleSource, err := newRuleSnapshotSourceFromEnvironment()
	if err != nil {
		log.Fatalf("initialize rule source: %v", err)
	}
	defer ruleSource.Close()
	dataID := setting("NACOS_DATA_ID", "sentinel-e2e-20261017-go-flow-rules.json")
	if strings.TrimSpace(os.Getenv("RULE_SOURCE_PROVIDER")) == "consul" {
		dataID = strings.TrimSpace(os.Getenv("CONSUL_KEY"))
	}
	sourceProfile := setting("RULE_SOURCE_PROFILE", "native-array-v1")
	ruleBindingID := strings.TrimSpace(os.Getenv("RULE_BINDING_ID"))
	decoderProfileID := setting("RULE_PROFILE_ID", "sentinel-go-v1")
	loadSnapshot := func(content string) (appliedGoSnapshot, error) {
		switch sourceProfile {
		case "native-array-v1":
			return applyGoFlowSnapshot(content)
		case "managed-envelope-v1":
			if ruleBindingID == "" {
				return appliedGoSnapshot{}, fmt.Errorf("managed rule profile requires RULE_BINDING_ID")
			}
			return applyGoManagedFlowSnapshot(content, ruleBindingID, decoderProfileID)
		default:
			return appliedGoSnapshot{}, fmt.Errorf("unsupported RULE_SOURCE_PROFILE")
		}
	}
	initial, err := ruleSource.Read()
	if err != nil {
		log.Fatalf("read initial rule snapshot: %v", err)
	}
	initialSnapshot, err := loadSnapshot(initial)
	if err != nil {
		log.Fatalf("initial rule snapshot rejected: %v", err)
	}
	// Match the verified Nacos 3 path: bounded polling avoids relying on a
	// gRPC listener stream that may not be compatible with every deployment.
	var observationReporter *ruleObservationReporter

	port := numberSetting("DEMO_PORT", 18082)
	bindHost := setting("DEMO_BIND_HOST", "127.0.0.1")
	var metrics *metricsCapture
	var metricsTransport *metricsReporter
	if strings.TrimSpace(os.Getenv("METRICS_COLLECTOR_URL")) != "" {
		reporterID := strings.TrimSpace(os.Getenv("METRICS_REPORTER_ID"))
		if reporterID == "" {
			log.Fatal("Metrics V2 reporter identity is required when reporting is enabled")
		}
		metrics, err = newMetricsCapture(reporterID)
		if err != nil {
			log.Fatalf("initialize Metrics V2 capture: %v", err)
		}
		var reporterErr error
		metricsTransport, reporterErr = newMetricsReporterFromEnvironment(metrics, log.Printf)
		if reporterErr != nil {
			log.Fatalf("initialize Metrics V2 transport: %v", reporterErr)
		}
		go metricsTransport.run(context.Background())
	}
	var publicationReceiptReporter *rulePublicationReceiptReporter
	if sourceProfile == "managed-envelope-v1" && metricsTransport != nil {
		publicationReceiptReporter, err = newRulePublicationReceiptReporter(metricsTransport, metrics, log.Printf)
		if err != nil {
			log.Fatalf("initialize Rule Publication Receipt V1 transport: %v", err)
		}
		go publicationReceiptReporter.run(context.Background())
		publicationReceiptReporter.applied(initialSnapshot)
	}
	if strings.TrimSpace(os.Getenv("RULE_BINDING_ID")) != "" {
		var reporterErr error
		observationReporter, reporterErr = newRuleObservationReporterFromEnvironment(
			metrics, strings.TrimSpace(os.Getenv("RULE_BINDING_ID")),
			setting("RULE_PROFILE_ID", "sentinel-go-v1"), log.Printf)
		if reporterErr != nil {
			log.Fatalf("initialize Rule Load Observation V1 transport: %v", reporterErr)
		}
		observationReporter.start(activeGoRuleSnapshot.Load())
	}
	go pollConfig(context.Background(), ruleSource, initial, loadSnapshot, func(snapshot appliedGoSnapshot) {
		if publicationReceiptReporter != nil {
			publicationReceiptReporter.applied(snapshot)
		}
		if observationReporter != nil {
			observationReporter.applied(snapshot)
		}
	}, func(reason string) {
		if observationReporter != nil {
			observationReporter.failed(reason)
		}
	}, initialSnapshot)
	mux := http.NewServeMux()
	mux.HandleFunc("GET /health", func(w http.ResponseWriter, _ *http.Request) { write(w, http.StatusOK, "ok\n") })
	mux.HandleFunc("GET /rules", func(w http.ResponseWriter, _ *http.Request) {
		snapshot := activeGoRuleSnapshot.Load()
		if snapshot == nil {
			write(w, http.StatusServiceUnavailable, "rules_loaded=false\n")
			return
		}
		managed := ""
		if snapshot.ManagedPublication != nil {
			managed = fmt.Sprintf("binding_id=%s\npublication_id=%s\ntarget_version_id=%s\npublication_sequence=%d\ntarget_payload_sha256=%s\n",
				snapshot.ManagedPublication.BindingID, snapshot.ManagedPublication.PublicationID,
				snapshot.ManagedPublication.TargetVersionID, snapshot.ManagedPublication.Sequence,
				snapshot.ManagedPublication.PayloadSHA256)
		}
		write(w, http.StatusOK, fmt.Sprintf("rules_loaded=true\nrule_count=%d\nsource_bytes_sha256=%s\ncanonical_rules_sha256=%s\n%s",
			snapshot.RuleCount, snapshot.SourceBytesSHA256, snapshot.CanonicalRulesSHA256, managed))
	})
	mux.HandleFunc("GET /api/hello", func(w http.ResponseWriter, request *http.Request) { handleHello(metrics, w, request) })
	mux.HandleFunc("GET /api/delay", func(w http.ResponseWriter, request *http.Request) { handleDelay(metrics, w, request) })
	server := &http.Server{Addr: net.JoinHostPort(bindHost, strconv.Itoa(port)), Handler: mux, ReadHeaderTimeout: 3 * time.Second}
	log.Printf("go-demo listening on %s; rule source key=%s", server.Addr, dataID)
	log.Fatal(server.ListenAndServe())
}

func pollConfig(ctx context.Context, source ruleSnapshotSource, initial string, loadSnapshot func(string) (appliedGoSnapshot, error), applied func(appliedGoSnapshot), failed func(string), initialSnapshot appliedGoSnapshot) {
	last := initial
	lastRejected := ""
	lastFailure := ""
	activeSnapshot := initialSnapshot
	ticker := time.NewTicker(time.Second)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			content, err := source.Read()
			if err != nil {
				if lastFailure != "source_unavailable" {
					log.Printf("rule source unavailable; retaining last-known-good rules")
				}
				lastFailure = "source_unavailable"
				failed("source_unavailable")
				continue
			}
			if content == lastRejected {
				continue
			}
			if content == last {
				if shouldReportGoSnapshotRecovery(content, last, lastRejected, lastFailure) {
					lastFailure = ""
					log.Printf("rule source recovered; retained active snapshot")
					applied(activeSnapshot)
				}
				continue
			}
			snapshot, err := loadSnapshot(content)
			if err != nil {
				log.Printf("polled rule update rejected: invalid_rules")
				lastRejected = content
				lastFailure = "decode_rejected"
				failed("decode_rejected")
				continue
			}
			last = content
			lastRejected = ""
			lastFailure = ""
			activeSnapshot = snapshot
			applied(snapshot)
			log.Printf("applied flow rules=%d source_bytes_sha256=%s", snapshot.RuleCount, snapshot.SourceBytesSHA256)
		}
	}
}

func shouldReportGoSnapshotRecovery(content, accepted, rejected, previousFailure string) bool {
	return content != "" && content == accepted && content != rejected && previousFailure != ""
}

func handleHello(metrics *metricsCapture, w http.ResponseWriter, _ *http.Request) {
	started := time.Now()
	entry, blockErr := api.Entry(resource, api.WithTrafficType(base.Inbound))
	if blockErr != nil {
		completed := write(w, http.StatusTooManyRequests, "blocked by Sentinel\n")
		metrics.record(completed, false, true, false, time.Since(started))
		return
	}
	defer entry.Exit()
	completed := write(w, http.StatusOK, "hello from Go Sentinel\n")
	metrics.record(completed, true, false, completed, time.Since(started))
}

func handleDelay(metrics *metricsCapture, w http.ResponseWriter, request *http.Request) {
	started := time.Now()
	delay, _ := strconv.Atoi(request.URL.Query().Get("ms"))
	if delay < 0 {
		delay = 0
	}
	if delay > 2000 {
		delay = 2000
	}
	time.Sleep(time.Duration(delay) * time.Millisecond)
	completed := write(w, http.StatusOK, fmt.Sprintf("delay_ms=%d\n", delay))
	metrics.record(completed, true, false, completed, time.Since(started))
}

func write(w http.ResponseWriter, status int, body string) bool {
	w.Header().Set("Content-Type", "text/plain; charset=utf-8")
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(status)
	_, err := w.Write([]byte(body))
	return err == nil
}

func setting(name string, fallback string) string {
	value := os.Getenv(name)
	if strings.TrimSpace(value) == "" {
		return fallback
	}
	return value
}

func numberSetting(name string, fallback int) int {
	value, err := strconv.Atoi(os.Getenv(name))
	if err != nil || value <= 0 {
		return fallback
	}
	return value
}

// Hello world web service: Atlas Richie Agent Reporting Protocol V1
// wire compatibility smoke test.
//
// Spins up a minimal HTTP/1.1 server (no third-party dependencies —
// Go stdlib only) that accepts a POST body containing the strict JSON
// envelope produced by the Python reporting codec at
// ``foundation/contracts/src/atlas_richie/contracts/reporting/v1/codec.py``.
//
// Endpoints:
//
//   GET  /healthz -> 200 {"status":"ok"}
//   POST /report  -> 200 with key_order echo, or 4xx with an error
//                    envelope. Body must contain the two wire marker
//                    fields ``protocol_version`` and ``event_kind``.
//
// Full wire semantics (FIFO, Ack, duplicate_count, batch atomicity,
// ...) are out of scope for hello world; this is purely a wire-format
// compatibility check driven by the Python cross-language contract
// tests in ``foundation/contracts/tests/cross_lang/test_go_hello.py``.
//
// Run: ``go run main.go -addr 127.0.0.1:18080`` then POST a 7-field
// envelope JSON to ``http://127.0.0.1:18080/report``.
package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"sort"
)

const (
	protocolVersion = "atlas-richie.reporting/v1"
)

var allowedEventKinds = map[string]bool{
	"RULE_SOURCE_ACTIVATED": true,
	"RULE_SOURCE_STALE":    true,
	"RULE_SOURCE_DEGRADED": true,
	"RULE_APPLIED":         true,
	"RULE_BLOCKED":         true,
	"RULE_FAILED":          true,
}

func main() {
	addr := flag.String("addr", "127.0.0.1:18080", "listen address (loopback only)")
	flag.Parse()

	mux := http.NewServeMux()
	mux.HandleFunc("/healthz", handleHealthz)
	mux.HandleFunc("/report", handleReport)

	log.Printf("cross_lang hello world listening on http://%s", *addr)
	if err := http.ListenAndServe(*addr, mux); err != nil {
		fmt.Fprintln(os.Stderr, "listen:", err)
		os.Exit(1)
	}
}

func handleHealthz(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(http.StatusOK)
	_, _ = io.WriteString(w, `{"status":"ok"}`)
}

func handleReport(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeError(w, http.StatusMethodNotAllowed, "METHOD_NOT_ALLOWED",
			"only POST is accepted on /report")
		return
	}
	defer r.Body.Close()

	body, err := io.ReadAll(r.Body)
	if err != nil {
		writeError(w, http.StatusBadRequest, "MALFORMED_ENVELOPE",
			"read body: "+err.Error())
		return
	}

	var obj map[string]interface{}
	if err := json.Unmarshal(body, &obj); err != nil {
		writeError(w, http.StatusBadRequest, "MALFORMED_ENVELOPE",
			"unmarshal: "+err.Error())
		return
	}

	pv, hasPV := obj["protocol_version"].(string)
	if !hasPV {
		writeError(w, http.StatusBadRequest, "PROTOCOL_VERSION_MISMATCH",
			"protocol_version must be a string")
		return
	}
	if pv != protocolVersion {
		writeError(w, http.StatusBadRequest, "PROTOCOL_VERSION_MISMATCH",
			fmt.Sprintf("protocol_version must equal %q, got %q",
				protocolVersion, pv))
		return
	}

	ek, hasEK := obj["event_kind"].(string)
	if !hasEK {
		writeError(w, http.StatusBadRequest, "MALFORMED_ENVELOPE",
			"event_kind must be a string")
		return
	}
	if !allowedEventKinds[ek] {
		writeError(w, http.StatusBadRequest, "UNKNOWN_EVENT_KIND",
			fmt.Sprintf("event_kind=%q not in V1 6 enums", ek))
		return
	}

	// Echo the observed wire keys in deterministic order so Python
	// contract tests can assert byte-for-byte wire preservation.
	keys := make([]string, 0, len(obj))
	for k := range obj {
		keys = append(keys, k)
	}
	sort.Strings(keys)

	out := map[string]interface{}{
		"status":           "ok",
		"fields_count":     len(obj),
		"protocol_version": pv,
		"event_kind":       ek,
		"key_order":        keys,
	}
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(http.StatusOK)
	_ = json.NewEncoder(w).Encode(out)
}

func writeError(w http.ResponseWriter, status int, code, msg string) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(map[string]interface{}{
		"protocol_version": protocolVersion,
		"error_code":       code,
		"message":          msg,
		"details":          nil,
	})
}

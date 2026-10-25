package metricsv2

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestSharedFixtures(t *testing.T) {
	manifest, err := os.ReadFile(filepath.Join("..", "fixture-rejections.json"))
	if err != nil {
		t.Fatal(err)
	}
	var expected map[string]string
	if err := json.Unmarshal(manifest, &expected); err != nil {
		t.Fatal(err)
	}
	invalidCount := 0
	fixtures := filepath.Join("..", "fixtures")
	entries, err := os.ReadDir(fixtures)
	if err != nil {
		t.Fatal(err)
	}
	validCount := 0
	for _, entry := range entries {
		name := entry.Name()
		if filepath.Ext(name) != ".json" {
			continue
		}
		t.Run(name, func(t *testing.T) {
			payload, err := os.ReadFile(filepath.Join(fixtures, name))
			if err != nil {
				t.Fatal(err)
			}
			if len(name) >= len("valid_") && name[:len("valid_")] == "valid_" {
				validCount++
				if err := ValidateSnapshot(payload); err != nil {
					t.Fatalf("valid fixture rejected: %v", err)
				}
				return
			}
			if len(name) >= len("invalid_") && name[:len("invalid_")] == "invalid_" {
				invalidCount++
				code, known := expected[name]
				if !known {
					t.Fatal("invalid fixture has no reviewed error code")
				}
				if err := ValidateSnapshot(payload); err == nil || err.Error() != code {
					t.Fatalf("expected %s, got %v", code, err)
				}
				return
			}
			t.Fatalf("fixture name has no valid/invalid class: %s", name)
		})
	}
	if invalidCount != len(expected) {
		t.Fatalf("reviewed %d invalid fixtures, exercised %d", len(expected), invalidCount)
	}
	if validCount == 0 {
		t.Fatal("no valid fixtures were exercised")
	}
}

func TestSharedReceiptFixtures(t *testing.T) {
	fixtures := filepath.Join("..", "fixtures", "receipts")
	entries, err := os.ReadDir(fixtures)
	if err != nil {
		t.Fatal(err)
	}
	for _, entry := range entries {
		name := entry.Name()
		if filepath.Ext(name) != ".json" {
			continue
		}
		t.Run(name, func(t *testing.T) {
			payload, err := os.ReadFile(filepath.Join(fixtures, name))
			if err != nil {
				t.Fatal(err)
			}
			err = ValidateReceipt(payload)
			if strings.HasPrefix(name, "valid_") && err != nil {
				t.Fatalf("valid receipt rejected: %v", err)
			}
			if strings.HasPrefix(name, "invalid_") && err == nil {
				t.Fatal("invalid receipt accepted")
			}
		})
	}
}

func TestNestedFieldFailuresUseRegisteredDiagnostics(t *testing.T) {
	for _, field := range []string{"counters", "histograms", "gauges"} {
		for _, mutation := range []string{"unknown", "missing"} {
			t.Run(field+"/"+mutation, func(t *testing.T) {
				payload, err := os.ReadFile(filepath.Join("..", "fixtures", "valid_full.json"))
				if err != nil {
					t.Fatal(err)
				}
				decoder := json.NewDecoder(strings.NewReader(string(payload)))
				decoder.UseNumber()
				var value map[string]any
				if err := decoder.Decode(&value); err != nil {
					t.Fatal(err)
				}
				record := value[field].([]any)[0].(map[string]any)
				if mutation == "unknown" {
					record["unapproved"] = true
				} else {
					delete(record, "name")
				}
				body, err := json.Marshal(value)
				if err != nil {
					t.Fatal(err)
				}
				expected := "invalid_" + strings.TrimSuffix(field, "s")
				if err := ValidateSnapshot(body); err == nil || err.Error() != expected {
					t.Fatalf("expected %s, got %v", expected, err)
				}
			})
		}
	}
}

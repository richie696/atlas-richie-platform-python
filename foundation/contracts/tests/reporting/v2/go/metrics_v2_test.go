package metricsv2

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestSharedFixtures(t *testing.T) {
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
				if err := ValidateSnapshot(payload); err == nil {
					t.Fatal("invalid fixture was accepted")
				}
				return
			}
			t.Fatalf("fixture name has no valid/invalid class: %s", name)
		})
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

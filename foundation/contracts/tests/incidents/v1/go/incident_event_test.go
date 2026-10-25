package incidentv1

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestSharedEventFixtures(t *testing.T) {
	fixtures := filepath.Join("..", "fixtures")
	entries, err := os.ReadDir(fixtures)
	if err != nil {
		t.Fatal(err)
	}
	valid := 0
	invalid := 0
	for _, entry := range entries {
		if entry.IsDir() || filepath.Ext(entry.Name()) != ".json" {
			continue
		}
		name := entry.Name()
		payload, readErr := os.ReadFile(filepath.Join(fixtures, name))
		if readErr != nil {
			t.Fatal(readErr)
		}
		t.Run(name, func(t *testing.T) {
			result := ValidateEvent(payload)
			if strings.HasPrefix(name, "invalid-") {
				invalid++
				if result == nil {
					t.Fatal("invalid event fixture was accepted")
				}
				return
			}
			if name != "resource-pressure.json" && name != "response-time.json" && name != "response-time-max-safe.json" {
				t.Fatalf("unclassified event fixture: %s", name)
			}
			valid++
			if result != nil {
				t.Fatalf("valid event fixture rejected: %v", result)
			}
		})
	}
	if valid != 3 || invalid < 1 {
		t.Fatalf("fixture corpus incomplete: valid=%d invalid=%d", valid, invalid)
	}
}

func TestSharedReceiptFixtures(t *testing.T) {
	fixtures := filepath.Join("..", "fixtures", "receipts")
	entries, err := os.ReadDir(fixtures)
	if err != nil {
		t.Fatal(err)
	}
	for _, entry := range entries {
		if entry.IsDir() || filepath.Ext(entry.Name()) != ".json" {
			continue
		}
		name := entry.Name()
		payload, readErr := os.ReadFile(filepath.Join(fixtures, name))
		if readErr != nil {
			t.Fatal(readErr)
		}
		err := ValidateReceipt(payload)
		if name == "valid.json" && err != nil {
			t.Fatalf("valid receipt rejected: %v", err)
		}
		if strings.HasPrefix(name, "invalid-") && err == nil {
			t.Fatal("invalid receipt fixture was accepted")
		}
	}
}

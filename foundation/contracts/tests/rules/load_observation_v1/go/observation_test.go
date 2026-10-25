package observationv1

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
	valid, invalid := 0, 0
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
			err := Validate(payload)
			if strings.HasPrefix(name, "valid_") {
				valid++
				if err != nil {
					t.Fatalf("valid fixture rejected: %v", err)
				}
			} else if strings.HasPrefix(name, "invalid_") {
				invalid++
				if err == nil {
					t.Fatal("invalid fixture accepted")
				}
			} else {
				t.Fatalf("unclassified fixture: %s", name)
			}
		})
	}
	if valid != 3 || invalid < 4 {
		t.Fatalf("fixture corpus incomplete: valid=%d invalid=%d", valid, invalid)
	}
}

func TestRejectDuplicateKeysAndTrailingValues(t *testing.T) {
	for _, payload := range [][]byte{
		[]byte(`{"x":1,"x":2}`),
		[]byte(`{} {}`),
		[]byte(`{"protocol_version":NaN}`),
		make([]byte, maxPayload+1),
	} {
		if err := Validate(payload); err == nil {
			t.Fatalf("invalid payload accepted: %s", payload)
		}
	}
}

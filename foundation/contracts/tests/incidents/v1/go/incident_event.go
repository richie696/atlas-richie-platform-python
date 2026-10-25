// Package incidentv1 validates the shared Incident Event V1 fixture corpus.
// This test utility is not a production SDK or transport.
package incidentv1

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math/big"
	"regexp"
	"strconv"
	"strings"
	"time"
)

const protocol = "atlas-richie.incident-events/v1"

var (
	uuidPattern      = regexp.MustCompile(`^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$`)
	timestampPattern = regexp.MustCompile(`^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z$`)
	digestPattern    = regexp.MustCompile(`^[0-9a-f]{64}$`)
)

// ValidateEvent accepts only the strict Incident Event V1 event contract.
func ValidateEvent(payload []byte) error {
	if len(payload) == 0 || len(payload) > 16*1024 {
		return errors.New("invalid_payload_size")
	}
	value, err := decodeUnique(payload)
	if err != nil {
		return err
	}
	root, ok := value.(map[string]any)
	if !ok || !exact(root, "protocol_version", "event_id", "process_epoch", "occurred_at", "severity", "fact") {
		return errors.New("invalid_event_fields")
	}
	if root["protocol_version"] != protocol {
		return errors.New("unsupported_protocol")
	}
	if !uuid(root["event_id"]) || !uuid(root["process_epoch"]) || !timestamp(root["occurred_at"]) {
		return errors.New("invalid_event_identity_or_time")
	}
	if !oneOf(root["severity"], "critical", "warning", "info") {
		return errors.New("invalid_severity")
	}
	fact, ok := root["fact"].(map[string]any)
	if !ok {
		return errors.New("invalid_fact")
	}
	switch fact["kind"] {
	case "resource_pressure":
		value, valueOK := numeric(fact["value"])
		threshold, thresholdOK := numeric(fact["threshold"])
		if !exact(fact, "kind", "metric", "value", "threshold") || !oneOf(fact["metric"], "cpu_ratio", "memory_ratio") || !valueOK || !thresholdOK || !ratio(value) || !ratio(threshold) || !breach(value, threshold) {
			return errors.New("invalid_resource_pressure_fact")
		}
	case "response_time":
		value, valueOK := numeric(fact["p95_ms"])
		threshold, thresholdOK := numeric(fact["threshold_ms"])
		if !exact(fact, "kind", "p95_ms", "threshold_ms") || !valueOK || !thresholdOK || !nonnegative(value) || !nonnegative(threshold) || !breach(value, threshold) {
			return errors.New("invalid_response_time_fact")
		}
	default:
		return errors.New("unsupported_fact_kind")
	}
	return nil
}

// ValidateReceipt accepts only a durable ACK bound to an event identity.
func ValidateReceipt(payload []byte) error {
	if len(payload) == 0 || len(payload) > 16*1024 {
		return errors.New("invalid_receipt_size")
	}
	value, err := decodeUnique(payload)
	if err != nil {
		return err
	}
	root, ok := value.(map[string]any)
	if !ok || !exact(root, "protocol_version", "event_id", "body_sha256", "received_at") {
		return errors.New("invalid_receipt_fields")
	}
	if root["protocol_version"] != protocol || !uuid(root["event_id"]) || !timestamp(root["received_at"]) {
		return errors.New("invalid_receipt_identity_or_time")
	}
	digest, ok := root["body_sha256"].(string)
	if !ok || !digestPattern.MatchString(digest) {
		return errors.New("invalid_receipt_digest")
	}
	return nil
}

func decodeUnique(payload []byte) (any, error) {
	decoder := json.NewDecoder(bytes.NewReader(payload))
	decoder.UseNumber()
	value, err := readValue(decoder)
	if err != nil {
		return nil, fmt.Errorf("invalid_json: %w", err)
	}
	if _, err = decoder.Token(); !errors.Is(err, io.EOF) {
		return nil, errors.New("invalid_trailing_json")
	}
	return value, nil
}

func readValue(decoder *json.Decoder) (any, error) {
	token, err := decoder.Token()
	if err != nil {
		return nil, err
	}
	delimiter, ok := token.(json.Delim)
	if !ok {
		return token, nil
	}
	switch delimiter {
	case '{':
		object := map[string]any{}
		for decoder.More() {
			keyToken, readErr := decoder.Token()
			if readErr != nil {
				return nil, readErr
			}
			key, keyOK := keyToken.(string)
			if !keyOK {
				return nil, errors.New("invalid_object_key")
			}
			if _, exists := object[key]; exists {
				return nil, errors.New("duplicate_json_key")
			}
			value, readErr := readValue(decoder)
			if readErr != nil {
				return nil, readErr
			}
			object[key] = value
		}
		_, err = decoder.Token()
		return object, err
	case '[':
		array := []any{}
		for decoder.More() {
			value, readErr := readValue(decoder)
			if readErr != nil {
				return nil, readErr
			}
			array = append(array, value)
		}
		_, err = decoder.Token()
		return array, err
	default:
		return nil, errors.New("invalid_json_delimiter")
	}
}

func exact(object map[string]any, fields ...string) bool {
	if len(object) != len(fields) {
		return false
	}
	for _, field := range fields {
		if _, ok := object[field]; !ok {
			return false
		}
	}
	return true
}

func uuid(value any) bool {
	text, ok := value.(string)
	return ok && uuidPattern.MatchString(text)
}

func timestamp(value any) bool {
	text, ok := value.(string)
	if !ok || !timestampPattern.MatchString(text) {
		return false
	}
	_, err := time.Parse("2006-01-02T15:04:05.000000Z", text)
	return err == nil
}

func oneOf(value any, choices ...string) bool {
	text, ok := value.(string)
	if !ok {
		return false
	}
	for _, choice := range choices {
		if text == choice {
			return true
		}
	}
	return false
}

type exactDecimal struct {
	sign      int
	digits    string
	magnitude *big.Int
}

type numericValue struct {
	projected float64
	exact     exactDecimal
}

func numeric(value any) (numericValue, bool) {
	number, ok := value.(json.Number)
	if !ok {
		return numericValue{}, false
	}
	exact, valid := parseExactDecimal(number.String())
	if !valid || exact.sign < 0 || compareExact(exact, mustExact("9007199254740991")) > 0 {
		return numericValue{}, false
	}
	parsed, err := strconv.ParseFloat(number.String(), 64)
	if err != nil && !strings.Contains(err.Error(), "value out of range") {
		return numericValue{}, false
	}
	return numericValue{projected: parsed, exact: exact}, true
}

func ratio(value numericValue) bool {
	return value.projected >= 0 && compareExact(value.exact, mustExact("1")) <= 0
}

func nonnegative(value numericValue) bool {
	return value.projected >= 0
}

func breach(value, threshold numericValue) bool {
	if compareExact(value.exact, threshold.exact) <= 0 {
		return false
	}
	return value.projected > threshold.projected
}

func parseExactDecimal(text string) (exactDecimal, bool) {
	negative := strings.HasPrefix(text, "-")
	unsigned := strings.TrimPrefix(strings.TrimPrefix(text, "-"), "+")
	parts := strings.FieldsFunc(unsigned, func(r rune) bool { return r == 'e' || r == 'E' })
	if len(parts) == 0 || len(parts) > 2 {
		return exactDecimal{}, false
	}
	exponent := new(big.Int)
	if len(parts) == 2 {
		if _, ok := exponent.SetString(parts[1], 10); !ok {
			return exactDecimal{}, false
		}
	}
	mantissaParts := strings.Split(parts[0], ".")
	if len(mantissaParts) > 2 {
		return exactDecimal{}, false
	}
	fractionDigits := 0
	if len(mantissaParts) == 2 {
		fractionDigits = len(mantissaParts[1])
	}
	digits := strings.Join(mantissaParts, "")
	if digits == "" {
		return exactDecimal{}, false
	}
	for _, digit := range digits {
		if digit < '0' || digit > '9' {
			return exactDecimal{}, false
		}
	}
	digits = strings.TrimLeft(digits, "0")
	if digits == "" {
		return exactDecimal{digits: "0", magnitude: new(big.Int)}, true
	}
	digits = strings.TrimRight(digits, "0")
	trailingZeros := len(strings.Join(mantissaParts, "")) - len(strings.TrimRight(strings.Join(mantissaParts, ""), "0"))
	exponent.Sub(exponent, big.NewInt(int64(fractionDigits)))
	exponent.Add(exponent, big.NewInt(int64(trailingZeros)))
	magnitude := new(big.Int).Add(exponent, big.NewInt(int64(len(digits))))
	sign := 1
	if negative {
		sign = -1
	}
	return exactDecimal{sign: sign, digits: digits, magnitude: magnitude}, true
}

func compareExact(left, right exactDecimal) int {
	if left.sign != right.sign {
		if left.sign < right.sign {
			return -1
		}
		return 1
	}
	if left.sign == 0 {
		return 0
	}
	comparison := left.magnitude.Cmp(right.magnitude)
	if comparison == 0 {
		length := len(left.digits)
		if len(right.digits) > length {
			length = len(right.digits)
		}
		comparison = strings.Compare(left.digits+strings.Repeat("0", length-len(left.digits)), right.digits+strings.Repeat("0", length-len(right.digits)))
	}
	if left.sign < 0 {
		return -comparison
	}
	return comparison
}

func mustExact(text string) exactDecimal {
	value, ok := parseExactDecimal(text)
	if !ok {
		panic("invalid exact-decimal constant")
	}
	return value
}

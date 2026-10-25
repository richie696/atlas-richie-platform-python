// Package metricsv2 validates the frozen shared Metrics V2 fixtures.
// It is a conformance validator, not a production transport or SDK.
package metricsv2

import (
	"bytes"
	"encoding/json"
	"errors"
	"io"
	"math"
	"math/big"
	"regexp"
	"strings"
	"time"
	"unicode/utf8"
)

const (
	protocolVersion  = "atlas-richie.metrics/v2"
	maxSafeInteger   = int64(9007199254740991)
	maxDecimalDigits = 38
	maxPayloadBytes  = 64 * 1024
	maxRecords       = 256
)

var timestampPattern = regexp.MustCompile(`^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z$`)
var uuidPattern = regexp.MustCompile(`^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$`)

var httpDurationBoundariesNs = []int64{
	1_000_000, 5_000_000, 10_000_000, 25_000_000, 50_000_000, 100_000_000,
	250_000_000, 500_000_000, 1_000_000_000, 2_000_000_000, 5_000_000_000, 10_000_000_000,
}

// ValidateSnapshot accepts only values that satisfy the frozen V2 snapshot.
func ValidateSnapshot(payload []byte) error {
	if len(payload) > maxPayloadBytes {
		return errors.New("payload_too_large")
	}
	if !utf8.Valid(payload) {
		return errors.New("invalid_json")
	}
	decoder := json.NewDecoder(bytes.NewReader(payload))
	decoder.UseNumber()
	value, err := decodeUniqueValue(decoder, payload)
	if err != nil {
		if err.Error() == "duplicate_json_key" {
			return err
		}
		return errors.New("invalid_json")
	}
	if _, err := decoder.Token(); !errors.Is(err, io.EOF) {
		return errors.New("invalid_json")
	}
	root, ok := value.(map[string]any)
	if !ok {
		return errors.New("invalid_snapshot_object")
	}
	version, ok := root["protocol_version"].(string)
	if !ok {
		return errors.New("invalid_protocol_version")
	}
	if version != protocolVersion {
		return errors.New("unsupported_protocol")
	}
	if exactFields(root, []string{"protocol_version", "reporter_id", "startup_epoch", "sequence", "captured_at", "capture_elapsed_ns", "counters", "histograms", "gauges"}) != nil {
		return errors.New("invalid_snapshot_fields")
	}

	counters, err := array(root["counters"])
	if err != nil {
		return err
	}
	histograms, err := array(root["histograms"])
	if err != nil {
		return err
	}
	gauges, err := array(root["gauges"])
	if err != nil {
		return err
	}
	seen := map[string]struct{}{}
	for _, item := range counters {
		counter, ok := item.(map[string]any)
		if !ok {
			return errors.New("invalid_counter_object")
		}
		if exactFields(counter, []string{"name", "value"}, []string{"resource"}) != nil {
			return errors.New("invalid_counter")
		}
		name, nameOK := counter["name"].(string)
		if !nameOK || !oneOf(name, "http_requests_completed_total", "sentinel_entries_admitted_total", "sentinel_entries_blocked_total", "business_transactions_completed_total") {
			return errors.New("invalid_counter_name")
		}
		if !safeInteger(counter["value"]) {
			return errors.New("invalid_counter_value")
		}
		resource := ""
		if raw, exists := counter["resource"]; exists {
			if !identifier(raw) {
				return errors.New("invalid_resource")
			}
			resource = raw.(string)
		}
		key := name + "\x00" + resource
		if _, exists := seen[key]; exists {
			return errors.New("duplicate_counter")
		}
		seen[key] = struct{}{}
	}
	seen = map[string]struct{}{}
	for _, item := range histograms {
		histogram, ok := item.(map[string]any)
		if !ok {
			return errors.New("invalid_histogram_object")
		}
		if exactFields(histogram, []string{"name", "boundaries_ns", "bucket_counts", "sample_count", "total_ns", "min_ns", "max_ns"}, []string{"resource"}) != nil {
			return errors.New("invalid_histogram")
		}
		rawBoundaries, err := array(histogram["boundaries_ns"])
		if err != nil {
			return err
		}
		if len(rawBoundaries) > 64 {
			return errors.New("too_many_histogram_boundaries")
		}
		boundaries, boundariesOK := intArray(rawBoundaries, true)
		if !boundariesOK {
			return errors.New("invalid_histogram_boundary")
		}
		if !equalInt64s(boundaries, httpDurationBoundariesNs) {
			return errors.New("invalid_histogram_boundaries")
		}
		name, nameOK := histogram["name"].(string)
		if !nameOK || name != "http_request_duration" {
			return errors.New("invalid_histogram_name")
		}
		rawBuckets, err := array(histogram["bucket_counts"])
		if err != nil {
			return err
		}
		buckets, bucketsOK := intArray(rawBuckets, false)
		if !bucketsOK {
			return errors.New("invalid_histogram_bucket_count")
		}
		sampleCount, sampleOK := integer(histogram["sample_count"])
		if !sampleOK {
			return errors.New("invalid_sample_count")
		}
		total, totalOK := decimalInteger(histogram["total_ns"])
		if !totalOK {
			return errors.New("invalid_histogram_total")
		}
		minimum, minOK := optionalInteger(histogram["min_ns"])
		if !minOK {
			return errors.New("invalid_histogram_minimum")
		}
		maximum, maxOK := optionalInteger(histogram["max_ns"])
		if !maxOK {
			return errors.New("invalid_histogram_maximum")
		}
		if len(buckets) != len(httpDurationBoundariesNs)+1 || !validHistogram(boundaries, buckets, sampleCount, total, minimum, maximum, histogram["min_ns"] != nil, histogram["max_ns"] != nil) {
			return errors.New("invalid_histogram")
		}

		resource := ""
		if raw, exists := histogram["resource"]; exists {
			if !identifier(raw) {
				return errors.New("invalid_resource")
			}
			resource = raw.(string)
		}
		key := name + "\x00" + resource
		if _, exists := seen[key]; exists {
			return errors.New("duplicate_histogram")
		}
		seen[key] = struct{}{}
	}
	seen = map[string]struct{}{}
	for _, item := range gauges {
		gauge, ok := item.(map[string]any)
		if !ok {
			return errors.New("invalid_gauge_object")
		}
		if exactFields(gauge, []string{"name", "value", "quality"}) != nil {
			return errors.New("invalid_gauge")
		}
		name, nameOK := gauge["name"].(string)
		if !nameOK || !oneOf(name, "process_cpu_ratio", "process_rss_bytes", "process_memory_ratio", "event_loop_lag_ns") {
			return errors.New("invalid_gauge_name")
		}
		quality, qualityOK := gauge["quality"].(string)
		if !qualityOK || !oneOf(quality, "available", "unavailable") {
			return errors.New("invalid_gauge_quality")
		}
		value := gauge["value"]
		if value != nil && !nonnegativeNumber(value) {
			return errors.New("invalid_gauge_value")
		}
		if quality == "unavailable" && value != nil || quality == "available" && value == nil {
			return errors.New("invalid_gauge")
		}

		if _, exists := seen[name]; exists {
			return errors.New("duplicate_gauge")
		}
		seen[name] = struct{}{}
	}
	if _, ok := root["reporter_id"].(string); !ok {
		return errors.New("invalid_reporter_id")
	}
	epoch, epochOK := root["startup_epoch"].(string)
	if !epochOK || !uuidPattern.MatchString(epoch) {
		return errors.New("invalid_startup_epoch")
	}
	if !positiveInteger(root["sequence"]) {
		return errors.New("invalid_sequence")
	}
	timestamp, ok := root["captured_at"].(string)
	if !ok || !timestampPattern.MatchString(timestamp) || strings.HasPrefix(timestamp, "0000-") {
		return errors.New("invalid_captured_at")
	}
	if _, err := time.Parse("2006-01-02T15:04:05.000000Z", timestamp); err != nil {
		return errors.New("invalid_captured_at")
	}
	if _, ok := decimalInteger(root["capture_elapsed_ns"]); !ok {
		return errors.New("invalid_capture_elapsed_ns")
	}
	if !identifier(root["reporter_id"]) {
		return errors.New("invalid_snapshot")
	}
	if len(counters)+len(histograms)+len(gauges) > maxRecords {
		return errors.New("too_many_records")
	}

	return nil
}

// ValidateReceipt accepts only the frozen durable Metrics V2 ACK value.
func ValidateReceipt(payload []byte) error {
	if len(payload) > maxPayloadBytes {
		return errors.New("receipt_too_large")
	}
	if !utf8.Valid(payload) {
		return errors.New("invalid_receipt_json")
	}
	decoder := json.NewDecoder(bytes.NewReader(payload))
	decoder.UseNumber()
	value, err := decodeUniqueValue(decoder, payload)
	if err != nil {
		if err.Error() == "duplicate_json_key" {
			return errors.New("duplicate_receipt_key")
		}
		return errors.New("invalid_receipt_json")
	}
	if _, err := decoder.Token(); !errors.Is(err, io.EOF) {
		return errors.New("invalid_receipt_json")
	}

	root, ok := value.(map[string]any)
	if !ok || exactFields(root, []string{"protocol_version", "reporter_id", "startup_epoch", "sequence", "body_sha256", "received_at"}) != nil {
		return errors.New("invalid_receipt_fields")
	}
	version, versionOK := root["protocol_version"].(string)
	if !versionOK || version != protocolVersion {
		return errors.New("unsupported_receipt_protocol")
	}
	epoch, epochOK := root["startup_epoch"].(string)
	if !epochOK {
		return errors.New("invalid_receipt_epoch")
	}
	if _, ok := root["sequence"].(json.Number); !ok {
		return errors.New("invalid_receipt_sequence")
	}
	receivedAt, receivedAtOK := root["received_at"].(string)
	if !receivedAtOK || !timestampPattern.MatchString(receivedAt) {
		return errors.New("invalid_receipt_time")
	}
	if _, err := time.Parse("2006-01-02T15:04:05.000000Z", receivedAt); err != nil || strings.HasPrefix(receivedAt, "0000-") {
		return errors.New("invalid_receipt")
	}
	digest, digestOK := root["body_sha256"].(string)
	if !identifier(root["reporter_id"]) || !uuidPattern.MatchString(epoch) || !positiveInteger(root["sequence"]) || !digestOK || !regexp.MustCompile(`^[0-9a-f]{64}$`).MatchString(digest) {
		return errors.New("invalid_receipt")
	}

	return nil
}

type invalidScalar struct{}

func decodeUniqueValue(decoder *json.Decoder, payload []byte) (any, error) {
	start := decoder.InputOffset()
	token, err := decoder.Token()
	if err != nil {
		return nil, errors.New("invalid_json")
	}
	if _, ok := token.(string); ok && hasUnpairedSurrogateEscape(payload[start:decoder.InputOffset()]) {
		return invalidScalar{}, nil
	}
	delimiter, ok := token.(json.Delim)
	if !ok {
		return token, nil
	}
	switch delimiter {
	case '{':
		result := map[string]any{}
		for decoder.More() {
			keyToken, err := decoder.Token()
			if err != nil {
				return nil, err
			}
			key, ok := keyToken.(string)
			if !ok {
				return nil, errors.New("invalid_object_key")
			}
			if _, exists := result[key]; exists {
				return nil, errors.New("duplicate_json_key")
			}
			value, err := decodeUniqueValue(decoder, payload)
			if err != nil {
				return nil, err
			}
			result[key] = value
		}
		_, err := decoder.Token()
		return result, err
	case '[':
		result := []any{}
		for decoder.More() {
			value, err := decodeUniqueValue(decoder, payload)
			if err != nil {
				return nil, err
			}
			result = append(result, value)
		}
		_, err := decoder.Token()
		return result, err
	default:
		return nil, errors.New("invalid_json_delimiter")
	}
}

func hasUnpairedSurrogateEscape(payload []byte) bool {
	inString := false
	for index := 0; index < len(payload); index++ {
		if !inString {
			if payload[index] == '"' {
				inString = true
			}
			continue
		}
		switch payload[index] {
		case '"':
			inString = false
		case '\\':
			if index+1 >= len(payload) {
				return true
			}
			if payload[index+1] != 'u' {
				index++
				continue
			}
			codeUnit, ok := parseCodeUnit(payload[index+2:])
			if !ok {
				return false // The JSON decoder reports malformed hex escapes.
			}
			if codeUnit >= 0xDC00 && codeUnit <= 0xDFFF {
				return true
			}
			if codeUnit >= 0xD800 && codeUnit <= 0xDBFF {
				lowStart := index + 6
				if lowStart+6 > len(payload) || payload[lowStart] != '\\' || payload[lowStart+1] != 'u' {
					return true
				}
				low, valid := parseCodeUnit(payload[lowStart+2:])
				if !valid || low < 0xDC00 || low > 0xDFFF {
					return true
				}
				index = lowStart + 5
			} else {
				index += 5
			}
		}
	}
	return false
}

func parseCodeUnit(value []byte) (uint16, bool) {
	if len(value) < 4 {
		return 0, false
	}
	var result uint16
	for _, character := range value[:4] {
		result <<= 4
		switch {
		case character >= '0' && character <= '9':
			result |= uint16(character - '0')
		case character >= 'a' && character <= 'f':
			result |= uint16(character-'a') + 10
		case character >= 'A' && character <= 'F':
			result |= uint16(character-'A') + 10
		default:
			return 0, false
		}
	}
	return result, true
}

func exactFields(value map[string]any, required []string, optional ...[]string) error {
	allowed := map[string]bool{}
	for _, key := range required {
		allowed[key] = true
		if _, ok := value[key]; !ok {
			return errors.New("missing_field")
		}
	}
	for _, keys := range optional {
		for _, key := range keys {
			allowed[key] = true
		}
	}
	for key := range value {
		if !allowed[key] {
			return errors.New("unknown_field")
		}
	}
	return nil
}

func array(value any) ([]any, error) {
	result, ok := value.([]any)
	if !ok {
		return nil, errors.New("invalid_array")
	}
	return result, nil
}

func identifier(value any) bool {
	text, ok := value.(string)
	return ok && len([]rune(text)) > 0 && len([]rune(text)) <= 200 && strings.TrimSpace(text) == text && strings.TrimSpace(text) != "" && !strings.ContainsAny(text, "\r\n")
}

func integer(value any) (int64, bool) {
	number, ok := value.(json.Number)
	if !ok {
		return 0, false
	}
	parsed, err := number.Int64()
	return parsed, err == nil && parsed >= 0 && parsed <= maxSafeInteger
}

func decimalInteger(value any) (*big.Int, bool) {
	text, ok := value.(string)
	if !ok || len(text) == 0 || len(text) > maxDecimalDigits || text[0] == '0' && len(text) > 1 {
		return nil, false
	}
	for _, character := range text {
		if character < '0' || character > '9' {
			return nil, false
		}
	}
	parsed, valid := new(big.Int).SetString(text, 10)
	return parsed, valid
}

func safeInteger(value any) bool {
	_, ok := integer(value)
	return ok
}

func positiveInteger(value any) bool {
	parsed, ok := integer(value)
	return ok && parsed > 0
}

func optionalInteger(value any) (int64, bool) {
	if value == nil {
		return 0, true
	}
	return integer(value)
}

func intArray(value any, positive bool) ([]int64, bool) {
	items, ok := value.([]any)
	if !ok {
		return nil, false
	}
	result := make([]int64, 0, len(items))
	for _, item := range items {
		parsed, valid := integer(item)
		if !valid || positive && parsed == 0 {
			return nil, false
		}
		result = append(result, parsed)
	}
	return result, true
}

func equalInt64s(left, right []int64) bool {
	if len(left) != len(right) {
		return false
	}
	for index, value := range left {
		if value != right[index] {
			return false
		}
	}
	return true
}

func validHistogram(boundaries, buckets []int64, sampleCount int64, total *big.Int, minimum, maximum int64, hasMinimum, hasMaximum bool) bool {
	for index := 1; index < len(boundaries); index++ {
		if boundaries[index] <= boundaries[index-1] {
			return false
		}
	}
	var sum int64
	for _, count := range buckets {
		if count > maxSafeInteger-sum {
			return false
		}
		sum += count
	}
	if sum != sampleCount {
		return false
	}
	if sampleCount == 0 {
		return total.Sign() == 0 && !hasMinimum && !hasMaximum
	}
	if !hasMinimum || !hasMaximum {
		return false
	}
	minimumTotal := new(big.Int).Mul(big.NewInt(minimum), big.NewInt(sampleCount))
	maximumTotal := new(big.Int).Mul(big.NewInt(maximum), big.NewInt(sampleCount))
	if minimum < 0 || maximum < minimum || total.Cmp(minimumTotal) < 0 || total.Cmp(maximumTotal) > 0 {
		return false
	}
	return true
}

func nonnegativeNumber(value any) bool {
	text, ok := value.(json.Number)
	if !ok {
		return false
	}
	if !strings.ContainsAny(text.String(), ".eE") {
		return safeInteger(text)
	}
	parsed, err := text.Float64()
	return err == nil && !math.IsNaN(parsed) && !math.IsInf(parsed, 0) && parsed >= 0 && parsed <= float64(maxSafeInteger)
}

func oneOf(value string, options ...string) bool {
	for _, option := range options {
		if value == option {
			return true
		}
	}
	return false
}

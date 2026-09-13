// main.go: Go CLI entry for the V1 reporting mock codec.
//
// Usage:
//
//	main -kind envelope < input.json > output.json
//	main -kind batch    < input.json > output.json
//	main -kind ack      < input.json > output.json
//	main -kind error    < input.json > output.json
//
// Reads JSON bytes from stdin, decodes + validates + re-encodes to stdout.
// On any validation error, prints a JSON error envelope to stdout and exits 1.
package main

import (
	"flag"
	"fmt"
	"io"
	"os"
)

func main() {
	kind := flag.String("kind", "envelope",
		"wire kind: envelope | batch | ack | error")
	flag.Parse()

	raw, err := io.ReadAll(os.Stdin)
	if err != nil {
		failAndExit("MALFORMED_ENVELOPE", "read stdin: "+err.Error())
	}

	var out []byte
	switch *kind {
	case "envelope":
		obj, err := DecodeEnvelope(raw)
		if err != nil {
			cerr := asCodecError(err)
			failAndExit(cerr.Code, cerr.Message)
		}
		out, err = EncodeEnvelope(obj)
		if err != nil {
			cerr := asCodecError(err)
			failAndExit(cerr.Code, cerr.Message)
		}
	case "batch":
		obj, err := DecodeBatch(raw)
		if err != nil {
			cerr := asCodecError(err)
			failAndExit(cerr.Code, cerr.Message)
		}
		out, err = EncodeBatch(obj)
		if err != nil {
			cerr := asCodecError(err)
			failAndExit(cerr.Code, cerr.Message)
		}
	case "ack":
		obj, err := DecodeAck(raw)
		if err != nil {
			cerr := asCodecError(err)
			failAndExit(cerr.Code, cerr.Message)
		}
		out, err = EncodeAck(obj)
		if err != nil {
			cerr := asCodecError(err)
			failAndExit(cerr.Code, cerr.Message)
		}
	case "error":
		obj, err := DecodeErrorEnvelope(raw)
		if err != nil {
			cerr := asCodecError(err)
			failAndExit(cerr.Code, cerr.Message)
		}
		out, err = EncodeErrorEnvelope(obj)
		if err != nil {
			cerr := asCodecError(err)
			failAndExit(cerr.Code, cerr.Message)
		}
	default:
		failAndExit("MALFORMED_ENVELOPE",
			fmt.Sprintf("unknown -kind=%q (expect envelope|batch|ack|error)", *kind))
	}

	if _, err := os.Stdout.Write(out); err != nil {
		fmt.Fprintln(os.Stderr, "write stdout:", err)
		os.Exit(2)
	}
	if _, err := os.Stdout.Write([]byte("\n")); err != nil {
		fmt.Fprintln(os.Stderr, "write newline:", err)
		os.Exit(2)
	}
}

func failAndExit(code, msg string) {
	obj := map[string]interface{}{
		"protocol_version": ProtocolVersion,
		"error_code":       code,
		"message":          msg,
		"details":          nil,
	}
	raw, err := EncodeErrorEnvelope(obj)
	if err != nil {
		raw = []byte(fmt.Sprintf(
			`{"protocol_version":%q,"error_code":%q,"message":%q,"details":null}`,
			ProtocolVersion, code, msg))
	}
	os.Stdout.Write(raw)
	os.Stdout.Write([]byte("\n"))
	os.Exit(1)
}

func asCodecError(err error) *CodecError {
	if err == nil {
		return nil
	}
	if ce, ok := err.(*CodecError); ok {
		return ce
	}
	return newCodecError("MALFORMED_ENVELOPE", err.Error())
}

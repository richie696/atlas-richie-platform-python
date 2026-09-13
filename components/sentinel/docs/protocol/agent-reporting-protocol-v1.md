# Atlas Richie Agent Reporting Envelope Schema (V1)

> **Protocol**: `atlas-richie-agent-reporting`
> **Version**: 1.0
> **Status**: Standards Track
> **Date**: 2026-09-13
> **Authors**: Atlas Richie Team &lt;[team@atlas-richie.com](mailto:team@atlas-richie.com)&gt;
> **License**: Apache-2.0
>
> 🌐 **Languages**: [English (this file)](./agent-reporting-protocol-v1.md) · [中文](./事件上报协议-v1.md)

---

## Abstract

This document specifies the **Atlas Richie Agent Reporting Envelope
Schema V1** (wire identifier: `atlas-richie.reporting/v1`), the
event envelope schema shared by all Reporter → Collector traffic.
The schema is the inner data structure of the Atlas Richie Reporting
Protocol V1 (see [`reporting-protocol-v1.md`](./reporting-protocol-v1.md) for the
outer transport, authentication, and batching). It is designed for
cross-language interoperability and uses JSON over UTF-8.

A Reporter emits events describing source activation, source health,
and rule-execution outcomes. A Collector receives them, deduplicates
by `(instance_id, startup_epoch, sequence)`, and feeds downstream
metrics and audit consumers.

## Status of This Memo

This document specifies an Atlas Richie Standards Track schema. It
is intended for cross-language SDK implementation. Distribution of
this memo is unlimited.

## Copyright Notice

Copyright © 2026 Atlas Richie. This document is distributed under the
Apache License, Version 2.0.

## Table of Contents

1. [Introduction](#1-introduction)
   1.1. [Background](#11-background)
   1.2. [Scope](#12-scope)
2. [Conventions](#2-conventions)
3. [Envelope Schema](#3-envelope-schema)
   3.1. [Complete Envelope](#31-complete-envelope)
   3.2. [Field Definitions](#32-field-definitions)
   3.3. [Serialization](#33-serialization)
   3.4. [Size Limits](#34-size-limits)
4. [Event Kind Enumeration](#4-event-kind-enumeration)
   4.1. [V1 Event Kinds](#41-v1-event-kinds)
   4.2. [Category Rules](#42-category-rules)
5. [Event Payload Schemas](#5-event-payload-schemas)
   5.1. [`RuleSourceActivatedPayload`](#51-rulesourceactivatedpayload)
   5.2. [`RuleSourceHealthPayload`](#52-rulesourcehealthpayload)
   5.3. [`RuleExecPayload`](#53-ruleexecpayload)
6. [Error Codes](#6-error-codes)
7. [Security Considerations](#7-security-considerations)
8. [IANA Considerations](#8-iana-considerations)
9. [Compatibility Matrix](#9-compatibility-matrix)
10. [Cross-Language Contract Tests](#10-cross-language-contract-tests)
11. [Future Work](#11-future-work)
[Appendix A. Examples](#appendix-a-examples)
[Appendix B. Sign-off](#appendix-b-sign-off)
[Version History](#version-history)
[Author's Address](#authors-address)

---

## 1. Introduction

### 1.1. Background

A Reporter observes Sentinel runtime events (rule application,
source activation, health changes) and ships them to a Collector
for aggregation, auditing, and dashboarding. Because the Reporter
and Collector MAY be implemented in different languages, the
schema on the wire MUST be self-describing and language-neutral.

The schema defined here is the inner event envelope. The outer
transport (HTTP/1.1 + JSON over TCP), authentication, batching,
sequence, deduplication, and ack semantics are specified separately
in [`reporting-protocol-v1.md`](./reporting-protocol-v1.md).

### 1.2. Scope

This document covers the V1 envelope schema only. It does NOT
specify:

- The transport layer (see `reporting-protocol-v1.md` §2).
- The authentication mechanism (see `reporting-protocol-v1.md` §4).
- The batch format (see `reporting-protocol-v1.md` §7).
- The Collector's internal state model.

## 2. Conventions

The key words "**MUST**", "**MUST NOT**", "**REQUIRED**", "**SHALL**",
"**SHALL NOT**", "**SHOULD**", "**SHOULD NOT**", "**RECOMMENDED**",
"**MAY**", and "**OPTIONAL**" in this document are to be interpreted
as described in [RFC 2119](https://www.rfc-editor.org/rfc/rfc2119).

- `int64` denotes a 64-bit signed integer.
- `string` denotes a UTF-8 sequence.
- `UUID` denotes a 128-bit identifier formatted as 8-4-4-4-12 lowercase
  hexadecimal, per [RFC 4122](https://www.rfc-editor.org/rfc/rfc4122).
- `ISO 8601 UTC microsecond` denotes the format
  `YYYY-MM-DDTHH:MM:SS.ffffffZ`, e.g. `2026-09-13T10:00:00.123456Z`.
- A `sha256:` string is the literal prefix followed by 64 lowercase
  hexadecimal characters.

## 3. Envelope Schema

### 3.1. Complete Envelope

```json
{
  "protocol_version": "atlas-richie.reporting/v1",
  "event_kind": "RULE_SOURCE_ACTIVATED",
  "event_payload": {
    "source_id": "nacos-prod",
    "rule_version_epoch": 1726000000,
    "rule_version_revision": 0,
    "rule_version_checksum": "sha256:abc123..."
  },
  "instance_id": "550e8400-e29b-41d4-a716-446655440000",
  "startup_epoch": 0,
  "sequence": 1,
  "captured_at": "2026-09-13T10:00:00.123456Z",
  "received_at": "2026-09-13T10:00:00.456789Z"
}
```

### 3.2. Field Definitions

| Field              | Type   | Required | Constraint                                                                              | Written by |
| ------------------ | ------ | -------- | --------------------------------------------------------------------------------------- | ---------- |
| `protocol_version` | string | YES      | MUST equal `"atlas-richie.reporting/v1"`.                                              | Reporter   |
| `event_kind`       | string | YES      | One of six V1 values; see §4.                                                           | Reporter   |
| `event_payload`    | object | YES      | Per-kind frozen schema; see §5.                                                        | Reporter   |
| `instance_id`      | string | YES      | UUID. Stable across the lifetime of one Reporter process.                              | Reporter   |
| `startup_epoch`    | int64  | YES      | Monotonic; resets only at process restart.                                              | Reporter   |
| `sequence`         | int64  | YES      | Monotonically increasing per `(instance_id, startup_epoch)`. Starts at 1.               | Reporter   |
| `captured_at`      | string | YES      | ISO 8601 UTC microsecond. **Diagnostic only**, not authoritative.                       | Reporter   |
| `received_at`      | string | YES      | ISO 8601 UTC microsecond. The **only** server-authoritative time field.                  | Collector  |

### 3.3. Serialization

- All strings MUST be UTF-8 with no leading or trailing whitespace.
- Integer fields MUST be JSON numbers without a decimal point.
- Floating-point fields MUST NOT appear in V1.
- Boolean fields use JSON `true` / `false`.
- Time fields use ISO 8601 UTC with microsecond precision, terminated
  by the literal `Z`. No timezone offset is permitted.
- UUIDs use lowercase hexadecimal, 8-4-4-4-12.
- Object field order is **not** guaranteed. Consumers MUST parse by
  key, not by position.

### 3.4. Size Limits

A single envelope MUST NOT exceed **16 KB** serialized. The Collector
MUST return an `ENVELOPE_TOO_LARGE` error if an envelope exceeds the
limit; the Reporter MUST apply its overflow policy and MUST NOT
retransmit the rejected envelope.

## 4. Event Kind Enumeration

### 4.1. V1 Event Kinds

Six event kinds are defined. The set is frozen for V1; new kinds
require V1.1 minor release and an ADR (see §9).

| `event_kind`              | Category      | Purpose                                                       | Payload schema               |
| ------------------------- | ------------- | ------------------------------------------------------------- | ---------------------------- |
| `RULE_SOURCE_ACTIVATED`   | source-switch | A new `source_id` and version becomes active.                  | `RuleSourceActivatedPayload` |
| `RULE_SOURCE_STALE`       | health        | Source state changes to stale (last-known-good still valid).  | `RuleSourceHealthPayload`    |
| `RULE_SOURCE_DEGRADED`    | health        | Source state worsens (degraded or disconnected).                | `RuleSourceHealthPayload`    |
| `RULE_APPLIED`            | biz-exec      | A rule was successfully applied to the Engine.                | `RuleExecPayload`            |
| `RULE_BLOCKED`            | biz-exec      | A rule blocked a request.                                     | `RuleExecPayload`            |
| `RULE_FAILED`             | biz-exec      | Rule application failed (codec / type / state error).         | `RuleExecPayload`            |

### 4.2. Category Rules

- **Source-switch events** (`RULE_SOURCE_ACTIVATED`) are emitted when
  a new source / version enters the active set. The payload MUST
  include `source_id` and the complete `rule_version_*` triple
  (epoch, revision, checksum).
- **Health events** (`RULE_SOURCE_STALE`, `RULE_SOURCE_DEGRADED`) are
  emitted when the source state changes without a source switch. The
  payload MUST include `source_id` and a `health_class` string.
- **Business-execution events** (`RULE_APPLIED`, `RULE_BLOCKED`,
  `RULE_FAILED`) are emitted on each rule application. The payload
  MUST include `source_id`, `rule_id`, and the execution result.

A health event MUST NOT be used in place of a source-switch event.
Source switches always go through `RULE_SOURCE_ACTIVATED`.

## 5. Event Payload Schemas

### 5.1. `RuleSourceActivatedPayload`

```json
{
  "source_id": "nacos-prod",
  "rule_version_epoch": 1726000000,
  "rule_version_revision": 0,
  "rule_version_checksum": "sha256:abc123..."
}
```

| Field                   | Type   | Required | Constraint                                            |
| ----------------------- | ------ | -------- | ----------------------------------------------------- |
| `source_id`             | string | YES      | `RuleSource.source_id`, ≤ 256 characters.             |
| `rule_version_epoch`    | int64  | YES      | ≥ 0; monotonically increasing.                         |
| `rule_version_revision` | int64  | YES      | ≥ 0; monotonic within the same epoch.                 |
| `rule_version_checksum` | string | YES      | `sha256:` followed by 64 lowercase hex characters.     |

### 5.2. `RuleSourceHealthPayload`

```json
{
  "source_id": "nacos-prod",
  "rule_version_epoch": 1726000000,
  "rule_version_revision": 0,
  "rule_version_checksum": "sha256:abc123...",
  "health_class": "STALE",
  "reason_class": "EMPTY_DATA_ID",
  "reason_message": "nacos data_id returned empty content"
}
```

| Field                   | Type   | Required | Constraint                                                                                                       |
| ----------------------- | ------ | -------- | ---------------------------------------------------------------------------------------------------------------- |
| `source_id`             | string | YES      | As §5.1.                                                                                                          |
| `rule_version_epoch`    | int64  | YES      | As §5.1.                                                                                                          |
| `rule_version_revision` | int64  | YES      | As §5.1.                                                                                                          |
| `rule_version_checksum` | string | YES      | As §5.1.                                                                                                          |
| `health_class`         | string | YES      | One of: `STALE`, `DEGRADED`, `DISCONNECTED`.                                                                      |
| `reason_class`         | string | YES      | A stable error class, e.g. `EMPTY_DATA_ID`, `NETWORK_TIMEOUT`, `AUTH_FAILED`, `DECODE_FAILED`.                  |
| `reason_message`       | string | NO       | Sanitized reason, ≤ 64 bytes. MUST NOT contain raw exceptions, stack traces, frame locals, or user data.        |

### 5.3. `RuleExecPayload`

```json
{
  "source_id": "nacos-prod",
  "rule_id": "flow:/api/v1/users",
  "rule_version_epoch": 1726000000,
  "rule_version_revision": 0,
  "rule_version_checksum": "sha256:abc123...",
  "exec_result": "BLOCKED",
  "failure_class": null
}
```

| Field                   | Type   | Required               | Constraint                                                                                              |
| ----------------------- | ------ | ---------------------- | ------------------------------------------------------------------------------------------------------- |
| `source_id`             | string | YES                    | As §5.1.                                                                                                |
| `rule_id`               | string | YES                    | ≤ 256 characters.                                                                                      |
| `rule_version_epoch`    | int64  | YES                    | As §5.1.                                                                                                |
| `rule_version_revision` | int64  | YES                    | As §5.1.                                                                                                |
| `rule_version_checksum` | string | YES                    | As §5.1.                                                                                                |
| `exec_result`           | string | YES                    | One of: `APPLIED`, `BLOCKED`, `FAILED`.                                                                 |
| `failure_class`         | string | YES if `exec_result=FAILED` | Stable error class. MUST NOT contain raw exceptions.                                                |

## 6. Error Codes

Nine error codes are defined. The behavior of each is specified
fully in [`reporting-protocol-v1.md` §5](./reporting-protocol-v1.md#5-error-codes);
this section merely lists them for completeness.

- `PROTOCOL_VERSION_MISMATCH`
- `MALFORMED_ENVELOPE`
- `UNKNOWN_EVENT_KIND`
- `PAYLOAD_SCHEMA_MISMATCH`
- `INSTANCE_ID_EMPTY`
- `SEQUENCE_NOT_MONOTONIC`
- `SEQUENCE_GAP`
- `STALE_EPOCH`
- `BATCH_TOO_LARGE`
- `AUTH_FAILED`

## 7. Security Considerations

- **Data boundary**: only Sentinel runtime state, source-activation
  facts, and reporter drop counters MAY be transmitted. Business
  request / response bodies, user identifiers, credentials, raw
  exception text, stack traces, frame locals, and complete rule
  bodies MUST NOT appear in any field.
- **Failure class**: when `exec_result=FAILED` or a health event is
  emitted, only a stable failure class string is allowed. Raw
  exception messages are forbidden.
- **Reason message length**: `reason_message` is capped at 64 bytes
  to bound diagnostic leakage.
- **Authentication**: the outer transport applies
  `X-Atlas-Cluster-Reporting-Token` (see `reporting-protocol-v1.md` §4).
  This schema does not redefine authentication.

## 8. IANA Considerations

This document requests no IANA actions.

## 9. Compatibility Matrix

| Change Type                                       | V1-breaking? | Path                                | Constraint                                                  |
| ------------------------------------------------- | ------------ | ----------------------------------- | ----------------------------------------------------------- |
| Add optional field in envelope                    | NO           | V1.1 minor + ADR                    | Old consumers ignore unknown fields.                        |
| Add optional field in `event_payload`             | NO           | V1.1 minor + ADR                    | Old consumers ignore unknown fields.                        |
| Add new `event_kind`                              | NO           | V1.1 minor + ADR                    | Old consumers skip unknown kinds.                           |
| Change `event_kind` string value                  | YES          | V2 major + independent ADR         | Old enum values are not revived.                            |
| Change `event_payload` field semantics            | YES          | V2 major + independent ADR         | Cross-language SDKs MUST update.                            |
| Remove an envelope field                          | YES          | V2 major + independent ADR         | Old consumers break immediately.                            |
| Change time-field semantics                       | YES          | V2 major + independent ADR         | Cross-language timezone serialization.                      |
| Change `protocol_version` string                  | YES          | V2 major + independent ADR         | Routing layer breaks immediately.                           |
| Change size limit (> 16 KB)                      | YES          | V2 major + independent ADR         | Cross-language SDKs MUST adjust buffers.                    |

After V1 freeze, no V1-breaking change MAY be merged silently. All
such changes require V2, a new ADR, and 5-owner sign-off.

## 10. Cross-Language Contract Tests

The following contract tests MUST pass for every cross-language SDK
of this schema:

| Test                                      | Description                                                                                |
| ----------------------------------------- | ------------------------------------------------------------------------------------------ |
| `python_serialize_roundtrip`             | Python envelope serialize → JSON → deserialize; all field values identical.                |
| `python_payload_schema_per_kind`         | Each of the six `event_kind` payloads round-trips; field order is irrelevant (key-based).    |
| `python_time_iso8601_utc`                 | `captured_at`, `received_at` use microsecond precision; cross-language strftime templates agree. |
| `python_protocol_version_constant`        | Any value other than `"atlas-richie.reporting/v1"` raises `PROTOCOL_VERSION_MISMATCH`.        |
| `python_malformed_envelope`               | Missing / wrong-type fields raise `MALFORMED_ENVELOPE`; the envelope is dropped, not silently accepted. |
| `go_mock_decode`                          | A Go SDK mock decodes the same spec; field names and types match exactly.                    |
| `java_mock_decode`                        | A Java SDK mock decodes the same spec; field names and types match exactly.                  |

## 11. Future Work

- Add `priority` and `tenant` fields (V1.1 candidate).
- Add per-rule `latency_ns` to `RuleExecPayload` (V1.1 candidate).
- Add `ENVELOPE_TOO_LARGE` to outer transport error codes
  (already declared here; documented in
  [`reporting-protocol-v1.md` §5](./reporting-protocol-v1.md#5-error-codes)).

## Appendix A. Examples

### A.1. Source-activation event

```json
{
  "protocol_version": "atlas-richie.reporting/v1",
  "event_kind": "RULE_SOURCE_ACTIVATED",
  "event_payload": {
    "source_id": "nacos-prod",
    "rule_version_epoch": 1726000000,
    "rule_version_revision": 0,
    "rule_version_checksum": "sha256:abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789"
  },
  "instance_id": "550e8400-e29b-41d4-a716-446655440000",
  "startup_epoch": 0,
  "sequence": 1,
  "captured_at": "2026-09-13T10:00:00.123456Z",
  "received_at": "2026-09-13T10:00:00.124000Z"
}
```

### A.2. Rule-blocked event

```json
{
  "protocol_version": "atlas-richie.reporting/v1",
  "event_kind": "RULE_BLOCKED",
  "event_payload": {
    "source_id": "nacos-prod",
    "rule_id": "flow:/api/v1/users",
    "rule_version_epoch": 1726000000,
    "rule_version_revision": 0,
    "rule_version_checksum": "sha256:abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789",
    "exec_result": "BLOCKED",
    "failure_class": null
  },
  "instance_id": "550e8400-e29b-41d4-a716-446655440000",
  "startup_epoch": 0,
  "sequence": 2,
  "captured_at": "2026-09-13T10:00:01.500000Z",
  "received_at": "2026-09-13T10:00:01.501000Z"
}
```

## Appendix B. Sign-off

This V1 schema was frozen under 5-owner sign-off. The sign-off
record is maintained at
[`docs/protocol/envelope-schema-freeze-record-v1.md`](./envelope-schema-freeze-record-v1.md).
Subsequent revisions require a new sign-off cycle and the changes
listed in §9.

## Version History

| Version | Date       | Authors                       | Changes        |
| ------- | ---------- | ----------------------------- | -------------- |
| 1.0     | 2026-09-13 | Atlas Richie Team / Mavis    | Initial V1.0 frozen release. |

## Author's Address

Atlas Richie Team
[team@atlas-richie.com](mailto:team@atlas-richie.com)

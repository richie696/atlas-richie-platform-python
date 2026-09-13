# Atlas Richie Reporting Protocol (V1)

> **Protocol**: `atlas-richie-reporting`
> **Version**: 1.0
> **Status**: Standards Track
> **Date**: 2026-09-13
> **Authors**: Atlas Richie Team &lt;[team@atlas-richie.com](mailto:team@atlas-richie.com)&gt;
> **License**: Apache-2.0
>
> 🌐 **Languages**: [English (this file)](./reporting-protocol-02-transport-v1.md) · [中文](./上报协议-02-transport-v1.md)

---

## Abstract

This document specifies the **Atlas Richie Reporting Protocol V1**
(wire identifier: `atlas-richie.reporting/v1`), the parent protocol
that transports Sentinel runtime events from Reporters to a
Collector. The protocol covers the transport (HTTP/1.1 + JSON),
authentication (shared secret), version negotiation, error codes,
batch format, sequence and deduplication keys, ack semantics, stale
generation behavior, and cardinality limits.

The on-the-wire envelope schema itself is specified in a companion
document, [`reporting-protocol-01-envelope-v1.md`](./reporting-protocol-01-envelope-v1.md).
The companion document is the schema only; this document is the
protocol.

## Status of This Memo

This document specifies an Atlas Richie Standards Track protocol.
Implementation is encouraged. Distribution of this memo is unlimited.

## Copyright Notice

Copyright © 2026 Atlas Richie. This document is distributed under the
Apache License, Version 2.0.

## Table of Contents

1. [Introduction](#1-introduction)
   1.1. [Background](#11-background)
   1.2. [Relationship to Companion Documents](#12-relationship-to-companion-documents)
2. [Data Boundary](#2-data-boundary)
3. [Transport](#3-transport)
4. [Version Negotiation](#4-version-negotiation)
5. [Authentication](#5-authentication)
6. [Error Codes](#6-error-codes)
7. [Batch Format](#7-batch-format)
8. [Sequence and Deduplication](#8-sequence-and-deduplication)
9. [Ack Semantics](#9-ack-semantics)
10. [Stale Generation Behavior](#10-stale-generation-behavior)
11. [Backpressure and Overflow Policy](#11-backpressure-and-overflow-policy)
12. [Cardinality and Dropped Statistics](#12-cardinality-and-dropped-statistics)
13. [Security Considerations](#13-security-considerations)
14. [IANA Considerations](#14-iana-considerations)
15. [Compatibility Matrix](#15-compatibility-matrix)
16. [Cross-Language Contract Tests](#16-cross-language-contract-tests)
17. [Future Work](#17-future-work)
[Appendix A. Examples](#appendix-a-examples)
[Appendix B. Sign-off](#appendix-b-sign-off)
[Version History](#version-history)
[Author's Address](#authors-address)

---

## 1. Introduction

### 1.1. Background

A Reporter observes Sentinel runtime events and ships them to a
Collector for aggregation, auditing, and dashboarding. Because the
Reporter and Collector MAY be implemented in different languages and
deployed across process boundaries, the protocol MUST be
self-describing, language-neutral, and independent of any
third-party dependencies.

This document specifies the protocol that wraps the inner envelope
schema. The inner schema is specified in
[`reporting-protocol-01-envelope-v1.md`](./reporting-protocol-01-envelope-v1.md).

### 1.2. Relationship to Companion Documents

| Document                                           | Scope                                                |
| -------------------------------------------------- | ---------------------------------------------------- |
| `reporting-protocol-01-envelope-v1.md` (this family) | Inner envelope schema (8 fields, 6 event kinds).     |
| `reporting-protocol-02-transport-v1.md` (this document) | Outer transport, auth, version, error codes, batch. |
| `reporting-protocol-03-freeze-record-v1.md` (sign-off) | Family-level 5-owner sign-off record.               |
| `cluster-token-protocol-v1.md` (sibling)          | The Atlas Richie Cluster Token Protocol (admission).  |

## 2. Data Boundary

The protocol MUST NOT carry any of the following:

- Business request or response bodies.
- User identifiers, authentication material, credentials, or tokens.
- Arbitrary log messages, stack traces, or frame locals.
- Complete rule bodies.
- Raw exception messages (only stable error classes are allowed).
- Private SDK or third-party internal fields.

The protocol MAY carry:

- Sentinel runtime state: pass / block / RT / failure classification
  / circuit state.
- Source activation: active `source_id` and rule version (epoch,
  revision, checksum).
- Reporter drop counters (queue full, collector failure, retransmit,
  reorder, instance restart).
- Stable error class plus a sanitized reason (≤ 64 bytes).

## 3. Transport

### 3.1. Choice

The transport is HTTP/1.1 with JSON over TCP. This choice is
consistent with the Atlas Richie Cluster Token Protocol V1 (see
[`cluster-token-protocol-v1.md`](./cluster-token-protocol-v1.md)) and avoids introducing
any third-party dependency.

### 3.2. Wire Format

```http
POST /reporting/v1/events HTTP/1.1
Host: <collector_host>
X-Atlas-Cluster-Reporting-Token: <shared_secret>
Content-Type: application/json; charset=utf-8
Content-Length: <bytes>
Connection: close

<batch_json_body>
```

### 3.3. Response

The Collector returns either `200 OK` plus an ack envelope
(see §9) or an HTTP error plus an error envelope (see §6).

### 3.4. Size Limits

- A single batch MUST NOT exceed **64 KB** serialized.
- A single envelope MUST NOT exceed **16 KB** serialized
  (see [`reporting-protocol-01-envelope-v1.md` §3.4](./reporting-protocol-01-envelope-v1.md#34-size-limits)).
- A batch MUST contain at most 256 envelopes.
- Exceeding a limit returns the appropriate error code (§6).

### 3.5. Transport-Level Decisions

| Decision            | Choice                   | Rationale                                                     |
| ------------------- | ------------------------ | ------------------------------------------------------------- |
| HTTP/1.1 vs HTTP/2  | HTTP/1.1                 | Consistent with sibling protocols.                            |
| TLS                 | 1.0 plaintext (loopback) | V1 simplification. Production uses loopback. mTLS is V1.1.    |
| Keep-alive          | Not supported            | V1 simplification. Single batch per connection.               |
| Connection pool     | Not supported            | V1 simplification.                                           |
| Compression         | Not supported            | V1 simplification. Size limits suffice.                       |

## 4. Version Negotiation

### 4.1. Version String

The constant version string is `"atlas-richie.reporting/v1"`. The
Reporter writes this into every batch's `protocol_version` field. The
Collector validates it; a mismatch returns `PROTOCOL_VERSION_MISMATCH`
and the Reporter MUST NOT retry.

### 4.2. Bump Policy

| Bump type   | Path                                      | Example                                  |
| ----------- | ----------------------------------------- | ---------------------------------------- |
| Major (v1 → v2) | Independent ADR + 5-owner sign-off     | Adding new transport semantics.          |
| Minor (v1 → v1.1) | 5-owner sign-off + compatibility matrix | Adding an optional field or `event_kind`. |
| Patch (v1.0.0 → v1.0.1) | Single owner sign-off        | Typo fix, doc clarification, no wire change. |

### 4.3. Major Mismatch Behavior

- The protocol MUST NOT silently ignore unknown fields.
- The protocol MUST NOT speculatively downcast unknown kinds.
- The Collector returns `PROTOCOL_VERSION_MISMATCH` plus the list of
  supported major versions.
- Retry is futile; the Reporter should be upgraded.

### 4.4. Minor Mismatch Behavior

- An old consumer receiving a new optional field ignores it.
- An old consumer receiving a new `event_kind` MUST return
  `UNKNOWN_EVENT_KIND` for that single envelope, not the whole batch.

### 4.5. Version Support in V1

- Reporter: emits only `v1`.
- Collector: accepts only `v1`.
- V1.1 may add multi-version Collector support (`v1` and `v1.1`).

## 5. Authentication

### 5.1. V1 Mechanism: Shared Secret

V1 uses a shared secret transmitted in the
`X-Atlas-Cluster-Reporting-Token` HTTP header. The secret is
configured at Reporter startup and paired with the Collector
configuration. V1 accepts that the channel is plaintext; production
deployments MUST restrict this to loopback.

A missing or wrong secret returns `AUTH_FAILED` (HTTP 401).

### 5.2. Future Authentication

| Phase | Mechanism                                          | Status         |
| ----- | -------------------------------------------------- | -------------- |
| 1.0   | Shared secret + plaintext header                   | This document. |
| 1.1   | Mutual TLS (client certificate + bidirectional)    | Reserved.      |
| 1.2   | OAuth client credentials                           | Reserved.      |

### 5.3. Instance Identity Binding

The Reporter is configured with an `instance_id` (UUID v4) and a
`startup_epoch` (int64, monotonic). These are independent of the
`ClientIdentity` used by the Cluster Token Protocol — the two
identity namespaces MUST NOT be mixed.

The Collector uses `(instance_id, startup_epoch)` to associate events
across Reporter sessions.

### 5.4. Credential Security Constraints

- Credentials MUST NOT appear in any event payload.
- Credentials MUST NOT appear in any log line.
- Credentials MUST NOT appear in any Dashboard response.
- Credentials MUST NOT appear in any error message or exception chain.
- Credentials appear ONLY in the HTTP request header.

### 5.5. Credential Rotation

V1 reads the shared secret once at startup. There is no in-process
rotation. V1.1 will provide a credential provider abstraction. If
rotation fails, the Reporter treats the situation as a network outage
and applies the bounded-backoff and overflow policy (§11).

## 6. Error Codes

Ten error codes are defined. The Collector returns one of them when
it cannot accept a batch.

| Error code                  | HTTP | Trigger                                              | Reporter behaviour                          |
| --------------------------- | ---- | ---------------------------------------------------- | ------------------------------------------- |
| `PROTOCOL_VERSION_MISMATCH` | 400  | `protocol_version` ≠ `"atlas-richie.reporting/v1"`.  | MUST NOT retry. Upgrade the SDK.            |
| `MALFORMED_ENVELOPE`        | 400  | Batch or envelope missing a required field, or type mismatch. | MUST NOT retry. Log error.                 |
| `UNKNOWN_EVENT_KIND`        | 400  | `event_kind` is not in the V1 enumeration.           | Drop the offending envelope. Continue.      |
| `PAYLOAD_SCHEMA_MISMATCH`   | 400  | Per-kind payload schema mismatch.                    | Drop the offending envelope. Continue.      |
| `INSTANCE_ID_EMPTY`         | 400  | `instance_id` is the empty string.                   | MUST NOT retry. Fix the Reporter.           |
| `SEQUENCE_NOT_MONOTONIC`    | 200  | `sequence` is not monotonic per `(instance_id, startup_epoch)`. | Acknowledge. Flag for monitoring.    |
| `SEQUENCE_GAP`              | 200  | `sequence` has a gap.                                | Acknowledge. Flag for monitoring.           |
| `STALE_EPOCH`               | 200  | `startup_epoch` is older than the Collector's latest known. | Silently drop. Do not retry.         |
| `BATCH_TOO_LARGE`           | 413  | The batch exceeds 64 KB.                             | Split and retry with smaller batches.       |
| `AUTH_FAILED`               | 401  | `X-Atlas-Cluster-Reporting-Token` is missing or wrong. | MUST NOT retry. Fix the configuration.   |

The wire format of an error envelope is:

```json
{
  "protocol_version": "atlas-richie.reporting/v1",
  "error_code": "MALFORMED_ENVELOPE",
  "message": "field 'sequence' must be int64, got string",
  "details": {
    "field": "sequence",
    "got_type": "string"
  }
}
```

V1 does not introduce additional error codes. New codes require
V1.1 minor release and an ADR.

## 7. Batch Format

### 7.1. Batch Envelope

```json
{
  "protocol_version": "atlas-richie.reporting/v1",
  "instance_id": "550e8400-e29b-41d4-a716-446655440000",
  "startup_epoch": 0,
  "batch_id": "550e8400-e29b-41d4-a716-446655440001",
  "sent_at": "2026-09-13T10:00:00.123456Z",
  "events": [
    { /* event envelope 1, see reporting-protocol-01-envelope-v1.md §3 */ },
    { /* event envelope 2 */ }
  ],
  "dropped_count": 0
}
```

### 7.2. Batch Field Definitions

| Field              | Type   | Required | Constraint                                                |
| ------------------ | ------ | -------- | --------------------------------------------------------- |
| `protocol_version` | string | YES      | As §4.1.                                                 |
| `instance_id`      | string | YES      | UUID v4. As §5.3.                                        |
| `startup_epoch`    | int64  | YES      | As §5.3.                                                 |
| `batch_id`         | string | YES      | UUID v4. Per-batch unique. NOT used for deduplication.    |
| `sent_at`         | string | YES      | ISO 8601 UTC microsecond.                                |
| `events`           | array  | YES      | 1 ≤ length ≤ 256 envelopes.                              |
| `dropped_count`    | int64  | YES      | ≥ 0. Number of events the Reporter dropped within this batch. |

### 7.3. Size Limits

- `events.length` ≤ 256; if exceeded, split into multiple batches.
- Serialized batch ≤ 64 KB; if exceeded, return `BATCH_TOO_LARGE`.
- Single envelope ≤ 16 KB (see
  [`reporting-protocol-01-envelope-v1.md` §3.4](./reporting-protocol-01-envelope-v1.md#34-size-limits)).

## 8. Sequence and Deduplication

### 8.1. Sequence Semantics

- `sequence` is monotonically increasing per
  `(instance_id, startup_epoch)`.
- Sequence starts at **1** (not 0).
- After process restart (new `startup_epoch`), sequence restarts at 1.

### 8.2. Deduplication Key

The unique deduplication key is the triple
`(instance_id, startup_epoch, sequence)`.

The Reporter maintains a counter per
`(instance_id, startup_epoch)`. The Collector maintains a
`(instance_id, startup_epoch) → max_sequence_seen` map.

A repeated batch or repeated envelope is detected by `sequence` and
is not double-counted in metrics.

### 8.3. Sequence Out-of-Order and Gaps

V1 explicitly does NOT enforce strict monotonicity or strict
contiguity. A `SEQUENCE_NOT_MONOTONIC` or `SEQUENCE_GAP` is reported
in the ack but does not cause rejection. This is because the
Reporter MAY emit events from concurrent slot-chain stages, where
strict ordering cannot be guaranteed.

## 9. Ack Semantics

### 9.1. Ack Envelope

```json
{
  "protocol_version": "atlas-richie.reporting/v1",
  "batch_id": "550e8400-e29b-41d4-a716-446655440001",
  "received_at": "2026-09-13T10:00:00.456789Z",
  "ack_sequences": [
    {
      "instance_id": "550e8400-e29b-41d4-a716-446655440000",
      "startup_epoch": 0,
      "max_contiguous_sequence": 100
    }
  ],
  "dropped_count": 0
}
```

### 9.2. Ack Field Definitions

| Field                | Type   | Required | Constraint                                                |
| -------------------- | ------ | -------- | --------------------------------------------------------- |
| `protocol_version`   | string | YES      | As §4.1.                                                 |
| `batch_id`           | string | YES      | The `batch_id` from the corresponding batch.              |
| `received_at`        | string | YES      | ISO 8601 UTC microsecond. The server-authoritative time.  |
| `ack_sequences`      | array  | YES      | 1 ≤ length.                                              |
| `dropped_count`      | int64  | YES      | Number of envelopes the Collector dropped (dedup / stale). |

### 9.3. Ack Interpretation

`max_contiguous_sequence` is the largest contiguous sequence the
Collector has accepted for the given `(instance_id, startup_epoch)`.
The Reporter compares this against its own last-sent `sequence`:

- Equal: all events have been accepted.
- Less: there is a gap or out-of-order event. The Reporter MUST NOT
  retransmit; out-of-order and gap handling are the Collector's
  responsibility (see §8.3).

### 9.4. No Per-Event Ack

V1 supports only batch-level acks. Per-event acks are a V1.1 candidate
intended for low-latency monitoring.

## 10. Stale Generation Behavior

### 10.1. Detection

The Collector considers an event stale when
`event.startup_epoch < max_epoch_seen_for(event.instance_id)`.

### 10.2. Behavior: Silently Drop

- The Collector MUST NOT raise an exception or return an error.
- The Collector MUST NOT include the event in `ack_sequences` (so the
  Reporter does not block on its `max_contiguous_sequence`).
- The Collector MUST NOT include the event in metrics (it MUST NOT
  pollute the new generation's data).
- The Collector increments a per-side `dropped_count` for monitoring.

This is consistent with the Cluster Token Protocol's
`STALE_EPOCH` fence (see [`cluster-token-protocol-v1.md` §3.1](./cluster-token-protocol-v1.md#31-three-core-invariants)).

### 10.3. Rationale

Stale events are an expected race after a Reporter restart. Silent
dropping avoids log noise. The fence is mandatory: a late event
from a previous generation MUST NOT influence a new generation.

## 11. Backpressure and Overflow Policy

### 11.1. Bounded Queue

The Reporter maintains an in-process queue of at most 4096 events
(V1 simplification). When the queue is full, the overflow policy
applies.

### 11.2. Overflow Policy

1. Increment `dropped_count` by the number of dropped events.
2. Every 1 second, emit a `RULE_SOURCE_DEGRADED` event whose payload
   contains the dropped-count delta for that window.
3. In-flight batches are not interrupted.
4. The Reporter MUST NOT block protected request paths. A
   `queue.put_nowait` failure results in drop, never a wait.

### 11.3. Backoff and Deadline

- A single batch send deadline is **5 seconds** (consistent with the
  Cluster Token Client V1).
- On transient failure (5xx, network), retry up to 3 times with
  exponential backoff of 50 ms / 200 ms / 1 s.
- On 4xx or `AUTH_FAILED`, do not retry (Client-side bug or
  misconfiguration).

### 11.4. Graceful Shutdown

On shutdown, the Reporter waits up to 5 seconds for in-flight batches
to complete. Any pending events that cannot be flushed in time are
dropped (counted in `dropped_count`). V1 does not guarantee
at-least-once delivery during shutdown.

### 11.5. Reporter Independence

The Reporter's internal event loop is independent of the Engine's
event loop. The Reporter runs its own `asyncio.new_event_loop()` per
batch send, consistent with the Cluster Token Client V1.

## 12. Cardinality and Dropped Statistics

### 12.1. Cardinality Quotas

| Dimension                 | V1 limit            | Overflow behaviour                                |
| ------------------------- | ------------------ | ------------------------------------------------- |
| Unique `instance_id`      | 1                  | N/A                                               |
| `startup_epoch` per `instance_id` | unbounded | N/A                                              |
| Unique `source_id`        | ≤ 8                | Drop, increment `source_cardinality_exceeded`.    |
| Unique `rule_id` per source | ≤ 256             | Drop, increment `rule_cardinality_exceeded`.      |
| Unique `event_kind`       | 6 (V1 frozen)      | Drop, increment `event_kind_unknown`.             |

### 12.2. Dropped Stats

Each batch contains:

- `dropped_count`: number of envelopes the Reporter dropped within
  this batch.

Each ack contains:

- `dropped_count`: number of envelopes the Collector dropped within
  this batch (deduplication, stale epoch, or cardinality).

### 12.3. Cardinality Monitoring

Every 1 second, the Reporter MAY emit a `RULE_SOURCE_DEGRADED` event
whose payload includes the high-water mark of any cardinality
dimension. V1 does not define a separate cardinality event.

### 12.4. Cardinality Configuration

V1 hardcodes the limits. V1.1 will make them configurable on the
Collector side.

## 13. Security Considerations

- **Data boundary**: see §2. The protocol MUST NOT carry business
  data, credentials, raw exceptions, or PII.
- **Authentication**: see §5. V1 uses a shared secret over plaintext.
  Production deployments MUST restrict to loopback. mTLS is V1.1.
- **Credential handling**: see §5.4. The secret appears only in the
  HTTP request header.
- **Authorisation**: cardinality quotas (§12) bound the memory and
  CPU consumption of the Collector.
- **Reception ordering**: V1 does not provide a confidentiality
  guarantee. Operators MUST use TLS for any non-loopback deployment.

## 14. IANA Considerations

This document requests no IANA actions.

## 15. Compatibility Matrix

| Change Type                                       | V1-breaking? | Path                                | Constraint                                                  |
| ------------------------------------------------- | ------------ | ----------------------------------- | ----------------------------------------------------------- |
| Add optional field in batch envelope              | NO           | V1.1 minor + ADR                    | Old consumers ignore unknown fields.                        |
| Add optional field in event envelope              | NO           | V1.1 minor + ADR                    | Old consumers ignore unknown fields.                        |
| Add new `event_kind`                              | NO           | V1.1 minor + ADR                    | Old consumers skip unknown kinds.                           |
| Add new error code                                | NO           | V1.1 minor + ADR                    | Old consumers treat as generic failure.                     |
| Change `event_kind` string value                  | YES          | V2 major + independent ADR         | Old enum values are not revived.                            |
| Change `ack_sequences` semantics                  | YES          | V2 major + independent ADR         | Cross-language SDKs MUST update.                            |
| Remove a batch envelope field                     | YES          | V2 major + independent ADR         | Old consumers break immediately.                            |
| Change size limit (> 64 KB)                       | YES          | V2 major + independent ADR         | Cross-language SDKs MUST adjust buffers.                    |
| Change `protocol_version` string                  | YES          | V2 major + independent ADR         | Routing layer breaks immediately.                           |

After V1 freeze, no V1-breaking change MAY be merged silently. All
such changes require V2, a new ADR, and 5-owner sign-off.

## 16. Cross-Language Contract Tests

| Test                                      | Description                                                                                |
| ----------------------------------------- | ------------------------------------------------------------------------------------------ |
| `python_serialize_roundtrip`             | Python batch serialize → JSON → deserialize; all field values identical.                    |
| `python_batch_serialize_roundtrip`        | Batch envelopes preserve the order of the `events` array.                                   |
| `python_payload_schema_per_kind`         | Each of the six `event_kind` payloads round-trips; field order is irrelevant.               |
| `python_time_iso8601_utc`                 | `captured_at`, `received_at`, `sent_at` use microsecond precision.                            |
| `python_protocol_version_constant`        | Any value other than `"atlas-richie.reporting/v1"` raises `PROTOCOL_VERSION_MISMATCH`.        |
| `python_malformed_envelope`               | Missing / wrong-type fields raise `MALFORMED_ENVELOPE`; the offending envelope is dropped.   |
| `python_sequence_dedup`                  | A repeated `sequence` does not double-count.                                                |
| `python_stale_epoch_drop`                | A stale-generation envelope is silently dropped; `dropped_count` is incremented.              |
| `python_ack_envelope_schema`             | Ack envelope fields and `max_contiguous_sequence` are correctly populated.                   |
| `go_mock_decode`                          | A Go SDK mock decodes the same spec; field names and types match exactly.                    |
| `java_mock_decode`                        | A Java SDK mock decodes the same spec; field names and types match exactly.                  |

## 17. Future Work

- mTLS authentication (V1.1).
- Per-event ack semantics (V1.1).
- Configurable cardinality quotas (V1.1).
- Distributed idempotency cache for multi-process Servers
  (e.g. shared Redis; V1.1).
- Add a `tenant` field to the envelope (V1.1 candidate).

## Appendix A. Examples

### A.1. Successful Batch Ack

```http
POST /reporting/v1/events HTTP/1.1
Host: collector.internal
X-Atlas-Cluster-Reporting-Token: ********
Content-Type: application/json; charset=utf-8
Content-Length: 1024
Connection: close

{
  "protocol_version": "atlas-richie.reporting/v1",
  "instance_id": "550e8400-e29b-41d4-a716-446655440000",
  "startup_epoch": 0,
  "batch_id": "550e8400-e29b-41d4-a716-446655440001",
  "sent_at": "2026-09-13T10:00:00.123456Z",
  "events": [
    {
      "protocol_version": "atlas-richie.reporting/v1",
      "event_kind": "RULE_APPLIED",
      "event_payload": {
        "source_id": "nacos-prod",
        "rule_id": "flow:/api/v1/users",
        "rule_version_epoch": 1726000000,
        "rule_version_revision": 0,
        "rule_version_checksum": "sha256:abc...",
        "exec_result": "APPLIED",
        "failure_class": null
      },
      "instance_id": "550e8400-e29b-41d4-a716-446655440000",
      "startup_epoch": 0,
      "sequence": 1,
      "captured_at": "2026-09-13T10:00:00.100000Z",
      "received_at": "2026-09-13T10:00:00.100000Z"
    }
  ],
  "dropped_count": 0
}
```

```http
HTTP/1.1 200 OK
Content-Type: application/json; charset=utf-8
Content-Length: 312
Connection: close

{
  "protocol_version": "atlas-richie.reporting/v1",
  "batch_id": "550e8400-e29b-41d4-a716-446655440001",
  "received_at": "2026-09-13T10:00:00.456789Z",
  "ack_sequences": [
    {
      "instance_id": "550e8400-e29b-41d4-a716-446655440000",
      "startup_epoch": 0,
      "max_contiguous_sequence": 1
    }
  ],
  "dropped_count": 0
}
```

## Appendix B. Sign-off

This V1 specification was frozen under 5-owner sign-off. The
family-level 5-owner sign-off record is maintained in
[`reporting-protocol-03-freeze-record-v1.md`](./reporting-protocol-03-freeze-record-v1.md).
Subsequent revisions require a new sign-off cycle and the changes
listed in §15.

## Version History

| Version | Date       | Authors                       | Changes        |
| ------- | ---------- | ----------------------------- | -------------- |
| 1.0     | 2026-09-13 | Atlas Richie Team / Mavis    | Initial V1.0 frozen release. |

## Author's Address

Atlas Richie Team
[team@atlas-richie.com](mailto:team@atlas-richie.com)

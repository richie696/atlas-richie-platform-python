# Atlas Richie Reporting Protocol (V1)

> **Protocol**: `atlas-richie-agent-reporting`
> **Version**: 1.0 (Frozen)
> **Status**: Frozen — 5-owner sign-off complete (2026-09-13)
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

This document is a pending transport draft. It MUST NOT be implemented as a
released Standards Track contract until its freeze record contains all required
signatures. Distribution of this memo is unlimited.

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
| `reporting-protocol-01-envelope-v1.md` (this family) | Inner ingress envelope schema (7 fields, 6 event kinds). |
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

This V1 event family MAY carry:

- Defined rule-execution outcomes: `APPLIED` / `BLOCKED` / `FAILED`, plus a
  constrained failure classification.
- Source activation: active `source_id` and rule version (epoch,
  revision, checksum).
- Reporter drop counters (only events dropped by queue, cardinality, or
  shutdown policy before sequence allocation).
- Stable error class plus a sanitized reason (≤ 64 bytes).

V1 does **not** define raw RT, circuit-state, or generic metrics fields. They
need dedicated per-kind schemas, privacy/cardinality review, and V2; they MUST
NOT be inserted through a broad payload.

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
X-Atlas-Reporting-Token: <shared_secret>
Content-Type: application/json; charset=utf-8
Content-Length: <bytes>
Connection: close

<batch_json_body>
```

### 3.3. Response

The Collector returns either `200 OK` plus an ack envelope
(see §9) or an HTTP error plus an error envelope (see §6).

### 3.4. Size Limits

- A single batch MUST NOT exceed **64 KiB** measured as UTF-8 JSON bytes.
- A single envelope MUST NOT exceed **16 KiB** measured as UTF-8 JSON bytes
  (see [`reporting-protocol-01-envelope-v1.md` §3.4](./reporting-protocol-01-envelope-v1.md#34-size-limits)).
- A batch MUST contain at most 256 envelopes.
- Exceeding a limit returns the appropriate error code (§6).

### 3.5. Transport-Level Decisions

| Decision            | Choice                   | Rationale                                                     |
| ------------------- | ------------------------ | ------------------------------------------------------------- |
| HTTP/1.1 vs HTTP/2  | HTTP/1.1                 | Consistent with sibling protocols.                            |
| TLS                 | Not supported; loopback only | A V1 Collector MUST bind only loopback and fail startup for a non-loopback bind. mTLS requires V2. |
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
| Major (v1 → v2) | Independent ADR + 5-owner sign-off | Adding transport, enumeration, or error semantics. |
| Minor (V1 spec revision) | 5-owner sign-off + compatibility matrix | Only safely ignorable optional fields; the wire string remains `v1`. |
| Patch (v1.0.0 → v1.0.1) | Single owner sign-off        | Typo fix, doc clarification, no wire change. |

### 4.3. Major Mismatch Behavior

- On a major mismatch, the Collector MUST NOT partially parse, silently
  downgrade, or use unknown fields as semantic input.
- The protocol MUST NOT speculatively downcast unknown kinds.
- The Collector returns `PROTOCOL_VERSION_MISMATCH` plus the list of
  supported major versions.
- Retry is futile; the Reporter should be upgraded.

### 4.4. Minor Revision Behavior

- The V1 wire string identifies the major only; a V1.x revision MUST NOT
  change it.
- Old consumers MUST ignore unknown optional fields.
- `event_kind`, error codes, existing field semantics, and Ack semantics are
  not optional extension points; a change to any of them requires V2.

### 4.5. Version Support in V1

- Reporter: emits only `v1`.
- Collector: accepts only `v1`.
- V1.x has no second wire string; the Collector still accepts only `v1`.

## 5. Authentication

### 5.1. V1 Mechanism: Shared Secret

V1 uses a shared secret transmitted in the `X-Atlas-Reporting-Token` HTTP
header. The secret is configured at Reporter startup and paired with Collector
configuration. V1 permits plaintext loopback transport only; a Collector MUST
reject a non-loopback bind configuration rather than leaving this boundary to
an operational convention.

A missing or wrong secret returns `AUTH_FAILED` (HTTP 401).

### 5.2. Future Authentication

| Phase | Mechanism                                          | Status         |
| ----- | -------------------------------------------------- | -------------- |
| 1.0   | Shared secret + plaintext header                   | This document. |
| V2    | Mutual TLS (client certificate + bidirectional)    | Reserved.      |
| V2 or later major | OAuth client credentials                   | Reserved.      |

### 5.3. Instance Identity Binding

The Reporter has an `instance_id` (UUID v4) that remains stable across restarts
and a persisted `startup_epoch` (int64) that strictly increases for every
restart and is never reused. The persistence medium is explicit Reporter
configuration; a Reporter that cannot uphold this invariant MUST refuse to
start. These identifiers are independent of the `ClientIdentity` used by the
Cluster Token Protocol — the two identity namespaces MUST NOT be mixed.

The Collector uses `(instance_id, startup_epoch)` to associate events
across Reporter sessions.

### 5.4. Credential Security Constraints

- Credentials MUST NOT appear in any event payload.
- Credentials MUST NOT appear in any log line.
- Credentials MUST NOT appear in any Dashboard response.
- Credentials MUST NOT appear in any error message or exception chain.
- Credentials appear ONLY in the HTTP request header.

### 5.5. Credential Rotation

V1 reads the shared secret once at startup. There is no in-process rotation.
Any transport that supports credential rotation requires V2. If credentials are
unavailable, the Reporter treats the situation as a network outage and applies
the bounded-backoff and overflow policy (§11).

## 6. Error Codes

Eleven error codes are defined. Apart from a successful Ack for an exact retry,
all validation rejects the **entire batch atomically**; V1 has no per-event
disposition.

| Error code                  | HTTP | Trigger                                              | Reporter behaviour                          |
| --------------------------- | ---- | ---------------------------------------------------- | ------------------------------------------- |
| `PROTOCOL_VERSION_MISMATCH` | 400  | `protocol_version` ≠ `"atlas-richie.reporting/v1"`.  | MUST NOT retry. Upgrade the SDK.            |
| `MALFORMED_ENVELOPE`        | 400  | Batch or envelope missing a required field, or type mismatch. | MUST NOT retry. Log error.                 |
| `UNKNOWN_EVENT_KIND`        | 400  | Any `event_kind` is not in the V1 enumeration.       | Drop the entire batch; repair or remove the event and rebuild it. |
| `PAYLOAD_SCHEMA_MISMATCH`   | 400  | Any per-kind payload schema mismatches.               | Drop the entire batch; repair or remove the event and rebuild it. |
| `INSTANCE_ID_EMPTY`         | 400  | `instance_id` is the empty string.                   | MUST NOT retry. Fix the Reporter.           |
| `SEQUENCE_NOT_MONOTONIC`    | 409  | The batch is not internally contiguous or conflicts with the Collector watermark. | Do not retry; record a protocol fault and restart Reporter with a new generation. |
| `SEQUENCE_GAP`              | 409  | A new batch does not start at watermark + 1.          | Do not retry; record a protocol fault and restart Reporter with a new generation. |
| `STALE_EPOCH`               | 409  | `startup_epoch` is older than the Collector's latest known. | Drop the batch; do not retry.      |
| `ENVELOPE_TOO_LARGE`        | 413  | Any ingress envelope exceeds 16 KiB.                  | Drop the batch; never retransmit the oversized event. |
| `BATCH_TOO_LARGE`           | 413  | The batch exceeds 64 KiB.                            | Split and retry with smaller batches.       |
| `AUTH_FAILED`               | 401  | `X-Atlas-Reporting-Token` is missing or wrong. | MUST NOT retry. Fix the configuration.   |

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

V1 does not introduce additional error codes. A new code requires V2 major and
an independent ADR.

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
| `events`           | array  | YES      | 1 ≤ length ≤ 256 envelopes. Each event's `protocol_version`, `instance_id`, and `startup_epoch` MUST equal the batch values. |
| `dropped_count`    | int64  | YES      | ≥ 0. Cumulative events dropped by this Reporter generation **before** sequence allocation. |

An event whose identity or version differs from its batch causes a
`MALFORMED_ENVELOPE` rejection of the entire batch. A batch represents exactly
one Reporter generation and MUST NOT mix instances or generations.

### 7.3. Size Limits

- `events.length` ≤ 256; if exceeded, split into multiple batches.
- Serialized batch ≤ 64 KiB; if exceeded, return `BATCH_TOO_LARGE`.
- Single envelope ≤ 16 KiB (see
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

The Reporter assigns a sequence only after an event is admitted to its bounded
outbox. A single sender for one generation MUST transmit in sequence order;
the earliest unacknowledged batch MUST be retried before any later batch. A
normal V1 stream therefore has neither gaps nor concurrent reordering.

The Collector maintains an `(instance_id, startup_epoch) →
max_contiguous_sequence` watermark. A batch is accepted only when it is an
exact retry entirely within the acknowledged range, or begins at watermark + 1
and is internally contiguous. A retry is never double-counted in metrics.

### 8.3. Sequence Out-of-Order and Gaps

V1 **enforces** strict monotonicity and contiguity for ingress sequence.
Concurrent slot-chain stages may produce facts, but sequence allocation and
outbox admission MUST be serialized inside the Reporter; they do not weaken
the wire contract. A violation rejects the entire batch with
`SEQUENCE_NOT_MONOTONIC` or `SEQUENCE_GAP` and produces no Ack.

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
  "duplicate_count": 0
}
```

### 9.2. Ack Field Definitions

| Field                | Type   | Required | Constraint                                                |
| -------------------- | ------ | -------- | --------------------------------------------------------- |
| `protocol_version`   | string | YES      | As §4.1.                                                 |
| `batch_id`           | string | YES      | The `batch_id` from the corresponding batch.              |
| `received_at`        | string | YES      | ISO 8601 UTC microsecond. The server-authoritative time.  |
| `ack_sequences`      | array  | YES      | Length MUST be 1 and its identity MUST equal the request batch. |
| `duplicate_count`    | int64  | YES      | Exact-retry envelopes already accepted in this batch; they are not counted twice. |

### 9.3. Ack Interpretation

`max_contiguous_sequence` is the largest contiguous sequence the
Collector has accepted for the given `(instance_id, startup_epoch)`.
The Reporter compares this against its own last-sent `sequence`:

- Equal: all events have been accepted, or the whole batch was an exact retry.
- Less: it MUST NOT occur in a successful V1 Ack. The Collector rejects the
  batch with a stable §6 error, and the Reporter MUST NOT send later batches
  in that generation.

### 9.4. No Per-Event Ack

V1 supports only batch-level Acks: strict single-generation FIFO makes the
batch result atomic. Per-event disposition requires V2.

## 10. Stale Generation Behavior

### 10.1. Detection

The Collector considers an event stale when
`event.startup_epoch < max_epoch_seen_for(event.instance_id)`.

### 10.2. Behavior: Atomic Rejection

- The Collector MUST reject a stale batch with `STALE_EPOCH` (HTTP 409) and
  MUST NOT produce an Ack.
- The Collector MUST NOT include that batch in metrics or audit.
- The Reporter MUST discard the batch and MUST NOT retry it; this never blocks
  a protected business request.

This is consistent with the Cluster Token Protocol's
`STALE_EPOCH` fence (see [`cluster-token-protocol-v1.md` §3.1](./cluster-token-protocol-v1.md#31-three-core-invariants)).

### 10.3. Rationale

Stale batches are an expected race after restart and network delay. Explicit
rejection prevents a Reporter from treating a non-advancing Ack as permission
to continue. The fence is mandatory: a late prior-generation event MUST NOT
influence a new generation.

## 11. Backpressure and Overflow Policy

### 11.1. Bounded Queue

The Reporter maintains an in-process queue of at most 4096 events
(V1 simplification). When the queue is full, the overflow policy
applies.

### 11.2. Overflow Policy

1. Events dropped before outbox admission increment `dropped_count`; they do
   not receive a sequence and therefore cannot create a wire gap.
2. `RULE_SOURCE_DEGRADED` represents RuleSource health only and MUST NOT be
   reused for Reporter queue or cardinality alerts.
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

The Reporter send task is independent of the Engine hot path. An async host
uses one writer task in its owning event loop; a synchronous host adapter owns
a dedicated loop/thread. Creating `asyncio.new_event_loop()` for each batch is
forbidden because it breaks connection and shutdown lifecycles.

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

Each batch contains the generation-cumulative `dropped_count`: only events
discarded by Reporter queue, cardinality, or shutdown policy before sequence
allocation. It is not a per-batch count and lets the Collector observe local
data loss.

Each Ack contains `duplicate_count`: only exact-retry envelopes already
accepted in this batch. It MUST NOT be confused with Reporter `dropped_count`.

### 12.3. Cardinality Monitoring

V1 defines neither a cardinality event nor a source-health overload. The
Collector observes the batch cumulative `dropped_count` and its own bounded
metrics; a new transportable metrics field requires V2.

### 12.4. Cardinality Configuration

V1 hardcodes the limits. A local Collector limit may be adjusted only if it
does not change wire semantics; client-negotiated quota configuration requires
V2.

## 13. Security Considerations

- **Data boundary**: see §2. The protocol MUST NOT carry business
  data, credentials, raw exceptions, or PII.
- **Authentication**: see §5. V1 uses a plaintext shared secret and a
  Collector MUST bind only loopback; a non-loopback configuration MUST fail
  startup. mTLS requires V2.
- **Credential handling**: see §5.4. The secret appears only in the
  HTTP request header.
- **Authorisation**: cardinality quotas (§12) bound the memory and
  CPU consumption of the Collector.
- **Confidentiality**: V1 provides no cross-host confidentiality, so it has no
  “non-loopback plus TLS” deployment exception.

## 14. IANA Considerations

This document requests no IANA actions.

## 15. Compatibility Matrix

| Change Type                                       | V1-breaking? | Path                                | Constraint                                                  |
| ------------------------------------------------- | ------------ | ----------------------------------- | ----------------------------------------------------------- |
| Add optional field in batch envelope              | NO           | V1.x spec revision + ADR            | Old consumers ignore unknown fields.                        |
| Add optional field in event envelope              | NO           | V1.x spec revision + ADR            | Old consumers ignore unknown fields.                        |
| Add new `event_kind`                              | YES          | V2 major + independent ADR          | Enumeration and handling semantics change together.         |
| Add new error code                                | YES          | V2 major + independent ADR          | Reporter behaviour must be explicit.                        |
| Change `event_kind` string value                  | YES          | V2 major + independent ADR         | Old enum values are not revived.                            |
| Change `ack_sequences` semantics                  | YES          | V2 major + independent ADR         | Cross-language SDKs MUST update.                            |
| Remove a batch envelope field                     | YES          | V2 major + independent ADR         | Old consumers break immediately.                            |
| Change size limit (> 64 KiB)                      | YES          | V2 major + independent ADR         | Cross-language SDKs MUST adjust buffers.                    |
| Change `protocol_version` string                  | YES          | V2 major + independent ADR         | Routing layer breaks immediately.                           |

After V1 freeze, no V1-breaking change MAY be merged silently. All
such changes require V2, a new ADR, and 5-owner sign-off.

## 16. Cross-Language Contract Tests

| Test                                      | Description                                                                                |
| ----------------------------------------- | ------------------------------------------------------------------------------------------ |
| `python_serialize_roundtrip`             | Python batch serialize → JSON → deserialize; all field values identical.                    |
| `python_batch_serialize_roundtrip`        | Batch envelopes preserve the order of the `events` array.                                   |
| `python_payload_schema_per_kind`         | Each of the six `event_kind` payloads round-trips; field order is irrelevant.               |
| `python_time_iso8601_utc`                 | Ingress `captured_at`, batch `sent_at`, and Ack `received_at` use microsecond precision.      |
| `python_protocol_version_constant`        | Any value other than `"atlas-richie.reporting/v1"` raises `PROTOCOL_VERSION_MISMATCH`.        |
| `python_malformed_envelope`               | Missing / wrong-type fields raise `MALFORMED_ENVELOPE`; the offending envelope is dropped.   |
| `python_sequence_dedup`                  | A repeated `sequence` does not double-count.                                                |
| `python_stale_epoch_reject`              | A stale-generation batch is atomically rejected with `STALE_EPOCH` and cannot affect aggregation. |
| `python_ack_envelope_schema`             | Ack envelope fields and `max_contiguous_sequence` are correctly populated.                   |
| `go_mock_decode`                          | A Go SDK mock decodes the same spec; field names and types match exactly.                    |
| `java_mock_decode`                        | A Java SDK mock decodes the same spec; field names and types match exactly.                  |

## 17. Future Work

- mTLS authentication (V2).
- Per-event disposition (V2).
- Configurable cardinality quotas (V2).
- Distributed idempotency state for multi-process Servers (V2; no Redis
  implementation is preselected).
- A `tenant` envelope field (requires V1.x capability negotiation or V2).

## Appendix A. Examples

### A.1. Successful Batch Ack

```http
POST /reporting/v1/events HTTP/1.1
Host: collector.internal
X-Atlas-Reporting-Token: ********
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
      "captured_at": "2026-09-13T10:00:00.100000Z"
    }
  ],
  "duplicate_count": 0
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

This draft may be frozen only after 5-owner sign-off. The
family-level 5-owner sign-off record is maintained in
[`reporting-protocol-03-freeze-record-v1.md`](./reporting-protocol-03-freeze-record-v1.md).
Subsequent revisions require a new sign-off cycle and the changes
listed in §15.

## Version History

| Version | Date       | Authors                       | Changes        |
| ------- | ---------- | ----------------------------- | -------------- |
| 1.0-draft.2 | 2026-09-13 | Atlas Richie Team / Mavis | Reconciled FIFO, Ack, generation, authentication, and overflow semantics. |

## Author's Address

Atlas Richie Team
[team@atlas-richie.com](mailto:team@atlas-richie.com)

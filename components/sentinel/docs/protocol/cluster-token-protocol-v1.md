# Atlas Richie Cluster Token Protocol (V1)

> **Protocol**: `atlas-richie-cluster-token`
> **Version**: 1.0
> **Status**: Standards Track
> **Date**: 2026-09-13
> **Authors**: Atlas Richie Team &lt;[team@atlas-richie.com](mailto:team@atlas-richie.com)&gt;
> **License**: Apache-2.0
>
> 🌐 **Languages**: [English (this file)](./cluster-token-protocol-v1.md) · [中文](./集群令牌协议-v1.md)

---

## Abstract

This document specifies the **Atlas Richie Cluster Token Protocol V1**
(wire identifier: `atlas-richie.cluster.token/v1`), a wire protocol
for distributed token quota and lease coordination across multiple
Sentinel processes. The protocol is designed for cross-language
interoperability and uses HTTP/1.1 with JSON over TCP, with zero
third-party dependencies.

A Client process requests a lease from a Server, which arbitrates
admission against a shared quota. Lease identities and expiry times
are opaque on the Client side, and an `owner_epoch` fence prevents
late operations from a stale generation of a Client from affecting a
new one.

## Status of This Memo

This document specifies an Atlas Richie Standards Track protocol.
Implementation is encouraged. Distribution of this memo is unlimited.

## Copyright Notice

Copyright © 2026 Atlas Richie. This document is distributed under the
Apache License, Version 2.0.

## Table of Contents

1. [Introduction](#1-introduction)
   1.1. [Background](#11-background)
   1.2. [Requirements](#12-requirements)
2. [Conventions](#2-conventions)
3. [Protocol Overview](#3-protocol-overview)
   3.1. [Three Core Invariants](#31-three-core-invariants)
   3.2. [Failure Policy](#32-failure-policy)
   3.3. [Deployment Topologies](#33-deployment-topologies)
4. [Wire Format](#4-wire-format)
   4.1. [Envelope](#41-envelope)
   4.2. [Field Definitions](#42-field-definitions)
   4.3. [Serialization](#43-serialization)
   4.4. [Size Limits](#44-size-limits)
5. [Message Kinds and Payloads](#5-message-kinds-and-payloads)
   5.1. [`ACQUIRE_REQUEST` / `AcquireRequestPayload`](#51-acquire_request--acquirerequestpayload)
   5.2. [`ACQUIRE_RESPONSE` / `AcquireResponsePayload`](#52-acquire_response--acquireresponsepayload)
   5.3. [`RELEASE_REQUEST` / `ReleaseRequestPayload`](#53-release_request--releaserequestpayload)
   5.4. [`RENEW_REQUEST` / `RenewRequestPayload`](#54-renew_request--renewrequestpayload)
   5.5. [`RENEW_RESPONSE` / `RenewResponsePayload`](#55-renew_response--renewresponsepayload)
   5.6. [`ERROR_RESPONSE` / `ErrorResponsePayload`](#56-error_response--errorresponsepayload)
6. [Idempotency Semantics](#6-idempotency-semantics)
7. [Error Codes](#7-error-codes)
8. [Security Considerations](#8-security-considerations)
9. [IANA Considerations](#9-iana-considerations)
10. [Compatibility Matrix](#10-compatibility-matrix)
11. [Cross-Language Contract Tests](#11-cross-language-contract-tests)
12. [Future Work](#12-future-work)
[Appendix A. Examples](#appendix-a-examples)
[Appendix B. Sign-off](#appendix-b-sign-off)
[Version History](#version-history)
[Author's Address](#authors-address)

---

## 1. Introduction

### 1.1. Background

A single Sentinel process holds its token quota state in memory. When
multiple Sentinel processes serve the same resource (e.g. a
horizontally-scaled web service), they require a shared coordination
point to avoid over-admission. This protocol defines the wire
contract by which Client processes request admission decisions and
hold leases, and by which a Server process arbitrates quota.

The protocol is designed to be language-neutral. The on-the-wire
format is JSON over HTTP/1.1, requiring only standard libraries
available in every modern programming language.

### 1.2. Requirements

The protocol satisfies the following requirements:

- **REQ-1**: The Server is the sole authority on lease validity.
  Clients MUST NOT be able to forge or extend a lease.
- **REQ-2**: Lease identities are opaque. The Server MAY use any
  internal representation; only the Server maps identities to state.
- **REQ-3**: A late `RELEASE` or `RENEW` from a stale generation of a
  Client MUST NOT affect a new generation. This is enforced by an
  `owner_epoch` fence.
- **REQ-4**: The Client retry loop MUST be safe under network failure
  using the `request_id` idempotency key.
- **REQ-5**: The protocol MUST operate over zero third-party
  dependencies (1.0 stabilization).

## 2. Conventions

The key words "**MUST**", "**MUST NOT**", "**REQUIRED**", "**SHALL**",
"**SHALL NOT**", "**SHOULD**", "**SHOULD NOT**", "**RECOMMENDED**",
"**MAY**", and "**OPTIONAL**" in this document are to be interpreted
as described in [RFC 2119](https://www.rfc-editor.org/rfc/rfc2119).

- `int64` denotes a 64-bit signed integer.
- `float64` denotes a 64-bit IEEE 754 floating-point number.
- `UUID` denotes a 128-bit identifier formatted as 8-4-4-4-12 lowercase
  hexadecimal, per [RFC 4122](https://www.rfc-editor.org/rfc/rfc4122).
- `ISO 8601 UTC microsecond` denotes the format
  `YYYY-MM-DDTHH:MM:SS.ffffffZ`, e.g. `2026-09-13T10:00:00.123456Z`.
- All field names in JSON objects are case-sensitive.

## 3. Protocol Overview

### 3.1. Three Core Invariants

The protocol is built on three invariants that the implementation MUST
preserve:

1. **The Server is the sole authority on lease validity.** The Client
   cannot renew or reclaim a lease by relying on its own wall clock.
2. **Lease identity is opaque to the Client.** The Client receives
   an opaque `lease_id` from the Server and passes it back unchanged
   in `RELEASE_REQUEST` and `RENEW_REQUEST`. The Client MUST NOT
   fabricate, modify, or speculate about the structure of a
   `lease_id`.
3. **Owner-epoch fencing prevents stale-generation interference.**
   Every Client request carries `(instance_id, startup_epoch)`. The
   Server validates the triple against its records; mismatches return
   the `STALE_EPOCH` error and the Client logs a warning and discards
   the operation. This prevents a crashed-and-restarted Client from
   releasing or renewing a lease that belongs to its successor.

### 3.2. Failure Policy

When the Server is unreachable or unresponsive, the Client applies a
per-resource `ClusterFailurePolicy` chosen at deployment time. Three
policies are defined:

| Policy            | Quota guarantee                                                  | Operational effect                                                |
| ----------------- | --------------------------------------------------------------- | ----------------------------------------------------------------- |
| `FAIL_CLOSED`     | Strict: total grants never exceed the Server-admitted quota.    | The Client denies the request. Business is impacted.              |
| `FAIL_OPEN`       | None: the Client MAY exceed the quota. Every pass is observable. | The Client grants a stub token. `fail_open_decision` metric incremented. |
| `LOCAL_FALLBACK`  | Per-process local policy; NOT a shared quota.                  | The Client delegates to a `LocalTokenService`.                   |

A default-deny rule applies: a resource without an explicit policy
configuration MUST be denied by the Client until one is set. Silent
fallback is forbidden.

### 3.3. Deployment Topologies

The protocol is agnostic to deployment topology. Three Server forms
are defined:

- **`standalone`**: a dedicated Server process. This is the
  recommended form for production deployments with multiple Client
  processes.
- **`embedded`**: a Server instance inside a single-worker process.
  The Server MUST assert at startup that the process worker count is
  exactly one. The shared in-process state MUST NOT be forked into
  multiple workers.
- **`client_only`**: a Client that never hosts a Server. Used in
  single-process integrations where the upstream Sentinel is
  elsewhere.

The following anti-patterns are forbidden:

- Implied self-bootstrap from Uvicorn worker ordinal.
- Leader election among multiple Server instances.
- Service-discovery-based ownership guessing.

## 4. Wire Format

### 4.1. Envelope

All messages share the same envelope, an 8-identifier outer object
plus a per-kind payload. The full envelope is:

```json
{
  "protocol_version": "atlas-richie.cluster.token/v1",
  "message_kind": "ACQUIRE_REQUEST",
  "request_id": "550e8400-e29b-41d4-a716-446655440000",
  "instance_id": "550e8400-e29b-41d4-a716-446655440001",
  "startup_epoch": 0,
  "resource": "/api/v1/users",
  "permits": 1.0,
  "deadline_ns": 5000000,
  "client_requested_at": "2026-09-13T10:00:00.123456Z",
  "server_received_at": "2026-09-13T10:00:00.456789Z",
  "payload": { /* per-kind frozen object, see §5 */ }
}
```

### 4.2. Field Definitions

| Field                 | Type      | Required | Constraint                                                | Written by                                     |
| --------------------- | --------- | -------- | --------------------------------------------------------- | ---------------------------------------------- |
| `protocol_version`    | string    | YES      | MUST equal `"atlas-richie.cluster.token/v1"`.            | Client (REQUEST) / Server (RESPONSE)           |
| `message_kind`        | string    | YES      | One of six V1 values; see §5.                             | Client (REQUEST) / Server (RESPONSE)           |
| `request_id`          | string    | YES      | UUID v4, Client-generated; the idempotency key.           | Client                                          |
| `instance_id`         | string    | YES      | UUID, unique per Client process.                          | Client                                          |
| `startup_epoch`       | int64     | YES      | Monotonically increasing per `(instance_id)`; starts at 0. | Client                                          |
| `resource`            | string    | YES      | Resource name, ≤ 256 characters.                          | Client (REQUEST) / Server (RESPONSE echoes)    |
| `permits`             | float64   | YES      | Requested or granted permits, ≥ 0.0.                     | Client (REQUEST) / Server (RESPONSE)           |
| `deadline_ns`         | int64     | YES      | Client-side relative deadline in nanoseconds.             | Client (REQUEST)                                |
| `client_requested_at` | string    | YES      | ISO 8601 UTC microsecond; diagnostic only.              | Client (REQUEST)                                |
| `server_received_at`  | string    | YES      | ISO 8601 UTC microsecond; the only server-authoritative time. | Server (REQUEST + RESPONSE)              |
| `payload`             | object    | YES      | Per-kind frozen object, see §5.                           | Client (REQUEST) / Server (RESPONSE)           |

### 4.3. Serialization

- All strings MUST be UTF-8.
- `int64` is encoded as a JSON number with no decimal point.
- `float64` is encoded as a JSON number, decimal allowed.
- Time fields use ISO 8601 UTC with microsecond precision, terminated
  by the literal `Z`.
- UUIDs use lowercase hexadecimal, 8-4-4-4-12.
- Object field order is **not** guaranteed. Consumers MUST parse by
  key, not by position.

### 4.4. Size Limits

A single envelope MUST NOT exceed **8 KB** serialized. The Server
MUST return `MALFORMED_ENVELOPE` if the envelope exceeds the limit;
the Client MUST NOT transmit an envelope it knows to be larger.

## 5. Message Kinds and Payloads

Six message kinds are defined in this version. Implementations MUST
NOT introduce new message kinds within the V1 envelope; new kinds
require V1.1 minor release and an ADR (see §10).

| `message_kind`        | Direction          | Purpose                                              |
| --------------------- | ------------------ | ---------------------------------------------------- |
| `ACQUIRE_REQUEST`     | Client → Server    | Request a lease.                                     |
| `ACQUIRE_RESPONSE`    | Server → Client    | Return the granted lease or a denial.                |
| `RELEASE_REQUEST`     | Client → Server    | Return a held lease.                                 |
| `RENEW_REQUEST`       | Client → Server    | Extend a held lease.                                 |
| `RENEW_RESPONSE`      | Server → Client    | Return the extended lease or a denial.               |
| `ERROR_RESPONSE`      | Server → Client    | Protocol-level error.                                |

### 5.1. `ACQUIRE_REQUEST` / `AcquireRequestPayload`

```json
{
  "rule_version_epoch": 1726000000,
  "rule_version_revision": 0,
  "rule_version_checksum": "sha256:abc123...",
  "priority": 0
}
```

| Field                     | Type   | Required | Constraint                                              |
| ------------------------- | ------ | -------- | ------------------------------------------------------- |
| `rule_version_epoch`      | int64  | YES      | ≥ 0.                                                    |
| `rule_version_revision`   | int64  | YES      | ≥ 0; monotonic within the same epoch.                   |
| `rule_version_checksum`   | string | YES      | MUST be `sha256:` followed by 64 lowercase hex chars.   |
| `priority`                | int64  | NO       | 0–9, default 0. Reserved for V1.1.                      |

### 5.2. `ACQUIRE_RESPONSE` / `AcquireResponsePayload`

```json
{
  "decision": "REMOTE_GRANTED",
  "lease_id": "550e8400-e29b-41d4-a716-446655440002",
  "lease_expires_at": "2026-09-13T10:00:05.000000Z",
  "permits_granted": 1.0,
  "retry_after_ns": 0,
  "deny_reason": null
}
```

| Field             | Type    | Required          | Constraint                                                |
| ----------------- | ------- | ----------------- | --------------------------------------------------------- |
| `decision`        | string  | YES               | `REMOTE_GRANTED` or `DENIED`.                             |
| `lease_id`        | string  | YES, if granted   | Server-generated opaque UUID. The Server alone maps it.  |
| `lease_expires_at`| string  | YES, if granted   | ISO 8601 UTC. The Client MUST NOT trust its own clock.   |
| `permits_granted` | float64 | YES, if granted   | ≤ request `permits`.                                     |
| `retry_after_ns`  | int64   | NO                | Server-suggested retry delay in nanoseconds.              |
| `deny_reason`     | string  | YES, if denied    | One of: `QUEUE_FULL`, `RATE_LIMITED`, `SHUTTING_DOWN`, `STALE_EPOCH`, `UNKNOWN`. |

### 5.3. `RELEASE_REQUEST` / `ReleaseRequestPayload`

```json
{
  "lease_id": "550e8400-e29b-41d4-a716-446655440002",
  "permits_released": 1.0
}
```

| Field              | Type    | Required | Constraint                                                 |
| ------------------ | ------- | -------- | ---------------------------------------------------------- |
| `lease_id`         | string  | YES      | MUST equal the `lease_id` from the granting response.       |
| `permits_released` | float64 | YES      | SHOULD equal `permits_granted` from the granting response.  |

The Server MUST validate the `(lease_id, instance_id, startup_epoch)`
triple. A mismatch returns `STALE_EPOCH`; the Client logs a warning
and does not raise.

### 5.4. `RENEW_REQUEST` / `RenewRequestPayload`

```json
{
  "lease_id": "550e8400-e29b-41d4-a716-446655440002",
  "extends_for_ns": 5000000
}
```

| Field            | Type   | Required | Constraint                                        |
| ---------------- | ------ | -------- | ------------------------------------------------- |
| `lease_id`       | string | YES      | Same as §5.3.                                    |
| `extends_for_ns` | int64  | YES      | Extension length in nanoseconds, > 0.            |

### 5.5. `RENEW_RESPONSE` / `RenewResponsePayload`

The `RENEW_RESPONSE` payload uses the same schema as
`ACQUIRE_RESPONSE` (see §5.2). The `decision` field accepts `RENEWED`
(extension granted) or `DENIED` (lease expired, quota full, or stale
epoch).

### 5.6. `ERROR_RESPONSE` / `ErrorResponsePayload`

```json
{
  "error_code": "PROTOCOL_VERSION_MISMATCH",
  "error_message": "expected atlas-richie.cluster.token/v1, got atlas-richie.cluster.token/v0"
}
```

| Field           | Type   | Required | Constraint                                                  |
| --------------- | ------ | -------- | ----------------------------------------------------------- |
| `error_code`    | string | YES      | One of nine V1 values; see §7.                             |
| `error_message` | string | NO       | Sanitized reason, ≤ 64 bytes. MUST NOT contain raw exceptions, stack traces, or frame locals. |

## 6. Idempotency Semantics

### 6.1. `request_id` Reuse

- The Client MUST generate a unique `request_id` (UUID v4) for each
  logical operation.
- A retry (after network failure or deadline timeout) MUST use the
  same `request_id`.
- The Server MUST maintain a short-term cache of
  `(request_id, instance_id, startup_epoch) → response` with a
  **5-minute TTL**.
- A cache hit returns the previously-recorded response; the Server
  MUST NOT re-execute state-changing operations.
- A cache miss executes the request and records the response.

### 6.2. TTL Selection

The 5-minute TTL MUST be strictly less than the typical lease TTL.
This prevents a `RELEASE_REQUEST` for an already-expired lease from
incorrectly matching a stale cache entry.

### 6.3. Multi-Process Servers

When the Server is replicated across multiple processes, the
idempotency cache MUST be shared. Version 1.0 uses an in-process
cache; a distributed cache (e.g. Redis) is a V1.1 candidate and MUST
be documented in the deployment guide.

## 7. Error Codes

Nine error codes are defined. Clients MUST handle them as follows:

| Error code                  | Trigger                                                 | Client behaviour                                                                                                                              |
| --------------------------- | ------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------- |
| `PROTOCOL_VERSION_MISMATCH` | `protocol_version` ≠ `"atlas-richie.cluster.token/v1"`.  | Retry is futile. Upgrade the SDK. Apply the `ClusterFailurePolicy` decision.                                                                  |
| `MALFORMED_ENVELOPE`        | Required field missing or type mismatch.                | Retry is futile. Log error. Apply the `ClusterFailurePolicy` decision.                                                                       |
| `UNKNOWN_MESSAGE_KIND`      | `message_kind` not in the V1 enumeration.                | Retry is futile. Upgrade the SDK. Apply the `ClusterFailurePolicy` decision.                                                                  |
| `STALE_EPOCH`               | `(lease_id, instance_id, startup_epoch)` mismatch.      | Log a warning. Do not raise. This is an expected race after a Client restart.                                                                  |
| `LEASE_NOT_FOUND`           | `RELEASE` / `RENEW` for a `lease_id` not held.           | Log a warning. The lease has already been collected by the scrubber.                                                                            |
| `LEASE_EXPIRED`             | `RENEW` for a lease past `lease_expires_at`.            | Log a warning. Re-acquire.                                                                                                                     |
| `RESOURCE_NOT_CONFIGURED`   | `ACQUIRE` for an unknown `resource`.                    | Deployment error. Fail-fast. Apply the `ClusterFailurePolicy` decision.                                                                        |
| `SERVER_OVERLOADED`         | Server is at capacity.                                  | The Server returns `DENIED` with `deny_reason = SERVER_OVERLOADED`. Apply the `ClusterFailurePolicy` decision.                                |
| `INTERNAL_ERROR`            | Server-side exception.                                  | Retry once. On continued failure, apply the `ClusterFailurePolicy` decision.                                                                  |

The Client's retry policy is fixed: the same `request_id` MUST be
retried at most 3 times, with an exponential backoff of
50 ms / 200 ms / 1 s. After 3 retries, the Client MUST apply the
`ClusterFailurePolicy` decision.

## 8. Security Considerations

- **Authentication**: V1 uses a shared secret in the
  `X-Atlas-Cluster-Token` HTTP header. Production deployments SHOULD
  restrict this to loopback. Mutual TLS is a V1.1 candidate.
- **Authorization**: Every resource MUST have an explicit
  `ClusterFailurePolicy`. A missing policy MUST result in denial.
- **Confidentiality**: The protocol does not provide message-level
  encryption. Operators MUST use TLS at the transport layer for any
  non-loopback deployment.
- **Credential handling**: The shared secret MUST NOT appear in log
  messages, error responses, or exception chains. Only the HTTP
  request header carries it.
- **Input validation**: The Server MUST validate every field of every
  received envelope. Unknown fields in the `payload` object are
  rejected as `MALFORMED_ENVELOPE`.
- **Rate limiting**: The Server SHOULD apply a per-`(instance_id,
  resource)` rate limit to prevent abuse. The exact limit is a
  deployment concern, not a protocol concern.

## 9. IANA Considerations

This document requests no IANA actions. All identifiers defined here
(UUIDs, error code strings, decision strings) are scoped to the
Atlas Richie Cluster Token Protocol namespace and are not intended
for global registration.

## 10. Compatibility Matrix

| Change Type                                       | V1-breaking? | Path                                | Constraint                                                  |
| ------------------------------------------------- | ------------ | ----------------------------------- | ----------------------------------------------------------- |
| Add optional field (within existing message kind) | NO           | V1.1 minor + ADR                    | Old consumers ignore unknown fields.                        |
| Add new `message_kind`                             | NO           | V1.1 minor + ADR                    | Old consumers skip unknown kinds.                           |
| Add new `deny_reason` / `error_code` value         | NO           | V1.1 minor + ADR                    | Old consumers skip unknown values.                          |
| Change `message_kind` string value                 | YES          | V2 major + independent ADR         | Old enum values are not revived.                            |
| Change `deny_reason` semantics                     | YES          | V2 major + independent ADR         | Cross-language SDKs MUST update.                            |
| Remove a field                                     | YES          | V2 major + independent ADR         | Old consumers break immediately.                            |
| Change time-field semantics                        | YES          | V2 major + independent ADR         | Cross-language timezone serialization.                      |
| Change `protocol_version` string                   | YES          | V2 major + independent ADR         | Routing layer breaks immediately.                           |
| Change size limit (> 8 KB)                         | YES          | V2 major + independent ADR         | Cross-language SDKs MUST adjust their buffers.              |

After the V1 freeze, no V1-breaking change MAY be merged silently.
All such changes require a V2 release, a new ADR, and 5-owner
sign-off.

## 11. Cross-Language Contract Tests

The following contract tests MUST pass for every cross-language SDK
of this protocol:

| Test                                | Description                                                                                |
| ----------------------------------- | ------------------------------------------------------------------------------------------ |
| `python_acquire_request_roundtrip`  | `ACQUIRE_REQUEST` JSON serialize and deserialize round-trip; field values identical.        |
| `python_acquire_response_granted`   | `REMOTE_GRANTED` response includes `lease_id`, `lease_expires_at`, `permits_granted`.         |
| `python_acquire_response_denied`    | `DENIED` response includes `deny_reason`, has no `lease_id`.                                 |
| `python_idempotency_replay`         | Same `request_id` replay returns the cached response within the 5-minute TTL.                |
| `python_idempotency_different_resource` | Same `request_id` with a different `resource` is treated as a new request.                |
| `python_stale_epoch_silent`         | `STALE_EPOCH` response does not raise; the Client only logs a warning.                      |
| `python_lease_id_opaque`            | Client-supplied `lease_id` for an unknown lease is rejected.                                |
| `python_renew_extends`              | `RENEW_REQUEST` extends `lease_expires_at` on success.                                      |
| `python_renew_expired`              | Renewal of an expired lease returns `DENIED` with `LEASE_EXPIRED`.                            |
| `python_release_returns_permits`    | `RELEASE_REQUEST` returns the permit to the Server's quota.                                 |
| `go_mock_acquire`                   | Go SDK mock deserialize of `ACQUIRE_REQUEST` matches field names and types.                |
| `java_mock_acquire`                 | Java SDK mock deserialize of `ACQUIRE_REQUEST` matches field names and types.              |

## 12. Future Work

- M6.3.3 Server resource-allocation state machine.
- M6.3.4 `RemoteTokenService` Client, including deadline / cancel /
  authentication / error translation.
- M6.3.5 Standalone and embedded Server deployment forms.
- M6.3.7 Contract suite implementation (see §11).
- Cross-language SDK implementations: at least one of Go / Java / Rust
  mocked against the same spec.

## Appendix A. Examples

### A.1. Successful Acquire

```http
POST /cluster/token HTTP/1.1
Host: sentinel.internal
X-Atlas-Cluster-Token: ********
Content-Type: application/json; charset=utf-8
Content-Length: 412
Connection: close

{
  "protocol_version": "atlas-richie.cluster.token/v1",
  "message_kind": "ACQUIRE_REQUEST",
  "request_id": "550e8400-e29b-41d4-a716-446655440000",
  "instance_id": "550e8400-e29b-41d4-a716-446655440001",
  "startup_epoch": 0,
  "resource": "/api/v1/users",
  "permits": 1.0,
  "deadline_ns": 5000000,
  "client_requested_at": "2026-09-13T10:00:00.123456Z",
  "server_received_at": "2026-09-13T10:00:00.123456Z",
  "payload": {
    "rule_version_epoch": 1726000000,
    "rule_version_revision": 0,
    "rule_version_checksum": "sha256:abc123...",
    "priority": 0
  }
}
```

```http
HTTP/1.1 200 OK
Content-Type: application/json; charset=utf-8
Content-Length: 380
Connection: close

{
  "protocol_version": "atlas-richie.cluster.token/v1",
  "message_kind": "ACQUIRE_RESPONSE",
  "request_id": "550e8400-e29b-41d4-a716-446655440000",
  "instance_id": "550e8400-e29b-41d4-a716-446655440001",
  "startup_epoch": 0,
  "resource": "/api/v1/users",
  "permits": 1.0,
  "deadline_ns": 5000000,
  "client_requested_at": "2026-09-13T10:00:00.123456Z",
  "server_received_at": "2026-09-13T10:00:00.124000Z",
  "payload": {
    "decision": "REMOTE_GRANTED",
    "lease_id": "550e8400-e29b-41d4-a716-446655440002",
    "lease_expires_at": "2026-09-13T10:00:05.000000Z",
    "permits_granted": 1.0,
    "retry_after_ns": 0,
    "deny_reason": null
  }
}
```

### A.2. Quota-full Denial

```http
HTTP/1.1 200 OK
Content-Type: application/json; charset=utf-8
Content-Length: 332
Connection: close

{
  "protocol_version": "atlas-richie.cluster.token/v1",
  "message_kind": "ACQUIRE_RESPONSE",
  "request_id": "...",
  "instance_id": "...",
  "startup_epoch": 0,
  "resource": "/api/v1/users",
  "permits": 1.0,
  "deadline_ns": 5000000,
  "client_requested_at": "2026-09-13T10:00:00.200000Z",
  "server_received_at": "2026-09-13T10:00:00.201000Z",
  "payload": {
    "decision": "DENIED",
    "lease_id": null,
    "lease_expires_at": null,
    "permits_granted": 0.0,
    "retry_after_ns": 100000000,
    "deny_reason": "QUEUE_FULL"
  }
}
```

## Appendix B. Sign-off

This V1 specification was frozen under 5-owner sign-off. The
envelope schema 5-owner sign-off record is maintained in
[`agent-reporting-protocol-v1.md` Appendix B](./agent-reporting-protocol-v1.md#appendix-b-sign-off);
the 5-owner sign-off table for this spec is to be added. The
cluster-token design discussion is at
[`docs/process/M6.3-CLUSTER-TOKEN-DESIGN.md`](../process/M6.3-CLUSTER-TOKEN-DESIGN.md).
Subsequent revisions require a new sign-off cycle and the changes
listed in §10.

## Version History

| Version | Date       | Authors                       | Changes        |
| ------- | ---------- | ----------------------------- | -------------- |
| 1.0     | 2026-09-13 | Atlas Richie Team / Mavis    | Initial V1.0 frozen release. |

## Author's Address

Atlas Richie Team
[team@atlas-richie.com](mailto:team@atlas-richie.com)

# Atlas Richie Agent Reporting Envelope Schema — V1 Freeze Record

> **Protocol**: `atlas-richie-agent-reporting`
> **Version**: 1.0 (Frozen)
> **Status**: Standards Track — V1 Released
> **Date**: 2026-09-13
> **Authors**: Atlas Richie Team &lt;[team@atlas-richie.com](mailto:team@atlas-richie.com)&gt;
> **License**: Apache-2.0
>
> 🌐 **Languages**: [English (this file)](./reporting-protocol-03-freeze-record-v1.md) · [中文](./上报协议-03-freeze-v1.md)

---

## Abstract

This document records the formal V1 freeze of the Atlas Richie
Agent Reporting Envelope Schema. It is the sign-off record for
[`reporting-protocol-01-envelope-v1.md`](./reporting-protocol-01-envelope-v1.md) and the schema-level
contract that Reporters and Collectors MUST honour.

This document is intentionally short. The schema itself, including
all field definitions, payload types, and serialization rules, is
specified in [`reporting-protocol-01-envelope-v1.md`](./reporting-protocol-01-envelope-v1.md). The outer
transport, authentication, batching, and sequence semantics are
specified in [`reporting-protocol-02-transport-v1.md`](./reporting-protocol-02-transport-v1.md). The present
document records only the freeze event and the immutability
guarantees that follow from it.

## Status of This Memo

This document records the V1 freeze of the Atlas Richie Agent
Reporting Envelope Schema. Distribution of this memo is unlimited.

## Copyright Notice

Copyright © 2026 Atlas Richie. This document is distributed under the
Apache License, Version 2.0.

## Table of Contents

1. [Freeze Declaration](#1-freeze-declaration)
2. [Immutability Guarantees](#2-immutability-guarantees)
3. [Compatibility with Subsequent Versions](#3-compatibility-with-subsequent-versions)
4. [Cross-References](#4-cross-references)
5. [Sign-off](#5-sign-off)
[Version History](#version-history)
[Author's Address](#authors-address)

---

## 1. Freeze Declaration

The Atlas Richie Agent Reporting Envelope Schema V1, identified by
the wire string `atlas-richie.reporting/v1`, is hereby declared
**FROZEN** as of 2026-09-13.

The frozen artifact is the schema specified in
[`reporting-protocol-01-envelope-v1.md`](./reporting-protocol-01-envelope-v1.md). The following are part
of the V1 contract and MUST NOT change without a new version bump
plus a new ADR and 5-owner sign-off:

- The envelope field set (8 fields) and their types.
- The six `event_kind` string values.
- The three `event_payload` schema types and their field sets.
- The serialization rules (UTF-8 strings, ISO 8601 microsecond time,
  lowercase UUIDs, key-based object parsing).
- The size limits (envelope ≤ 16 KB; see `reporting-protocol-02-transport-v1.md` §3.4).

## 2. Immutability Guarantees

After the freeze date:

1. The six `event_kind` values are immutable. New values require
   V1.1 minor release and an ADR.
2. The three `event_payload` schemas are immutable. New fields in
   existing schemas require V1.1. New payload types require V1.1
   minor and an ADR.
3. The envelope size limit (16 KB) is immutable. Increasing it
   requires V2 major and an ADR.
4. The wire identifier string (`atlas-richie.reporting/v1`) is
   immutable. Any change requires V2 major and an ADR.
5. The serialization rules in
   [`reporting-protocol-01-envelope-v1.md` §3.3](./reporting-protocol-01-envelope-v1.md#33-serialization)
   are immutable.

## 3. Compatibility with Subsequent Versions

### 3.1. V1 Consumer Reading V1.1 Producer

A V1 consumer receiving a V1.1 envelope with additional optional
fields MUST ignore the unknown fields. A V1 consumer receiving a V1.1
`event_kind` not in its V1 enumeration MUST return
`UNKNOWN_EVENT_KIND` for the offending envelope, not the whole batch.

### 3.2. V1.1 Consumer Reading V1 Producer

A V1.1 consumer MUST accept V1 envelopes as a subset. It MUST accept
all six V1 `event_kind` values, all three V1 payload types, and the
V1 envelope size limit.

### 3.3. V2 Major Compatibility

V2 will be a separate wire identifier (`atlas-richie.reporting/v2`).
V1 will continue to be accepted by V2-aware Collectors. V1 producer
support in a V2-aware Reporter is optional.

## 4. Cross-References

| Document                                | Purpose                                                          |
| --------------------------------------- | ---------------------------------------------------------------- |
| `reporting-protocol-01-envelope-v1.md` (this family)  | The V1 envelope schema. The artifact that this document freezes. |
| `reporting-protocol-02-transport-v1.md`              | The outer transport, authentication, batching, and sequence.     |
| `cluster-token-protocol-v1.md` (sibling) | The Atlas Richie Cluster Token Protocol (admission).              |
| `process/M6.5-REPORTING-PROTOCOL-V1.md` | The process-design document for M6.5 (internal).                 |
| `process/M6.5.7-ENVELOPE-FREEZE.md`     | The historical sign-off record. (Now superseded by this document.) |

## 5. Sign-off

This V1 freeze is signed off by the following 5 owners:

| Owner    | Role                                  | Status         | Date       |
| -------- | ------------------------------------- | -------------- | ---------- |
| richie696 | Project owner                          | ☐ pending     |            |
| owner 1  | Protocol designer                     | ☐ pending     |            |
| owner 2  | Reporter implementation owner          | ☐ pending     |            |
| owner 3  | Collector implementation owner         | ☐ pending     |            |
| owner 4  | Cross-language SDK owner                | ☐ pending     |            |

Until all 5 owners have signed, V1 is provisional. Once all 5
signatures are in place, this document is the canonical V1 freeze
record, and any change MUST follow the procedure in §2 and §3.

## Version History

| Version | Date       | Authors                       | Changes                            |
| ------- | ---------- | ----------------------------- | ---------------------------------- |
| 1.0     | 2026-09-13 | Atlas Richie Team / Mavis    | Initial V1 freeze record.          |

## Author's Address

Atlas Richie Team
[team@atlas-richie.com](mailto:team@atlas-richie.com)

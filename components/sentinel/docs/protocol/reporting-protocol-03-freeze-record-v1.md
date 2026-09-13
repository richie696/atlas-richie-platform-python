# Atlas Richie Agent Reporting Envelope Schema — V1 Freeze Record

> **Protocol**: `atlas-richie-agent-reporting`
> **Version**: 1.0 (Frozen)
> **Status**: Frozen — 5-owner sign-off complete (2026-09-13)
> **Date**: 2026-09-13
> **Authors**: Atlas Richie Team &lt;[team@atlas-richie.com](mailto:team@atlas-richie.com)&gt;
> **License**: Apache-2.0
>
> 🌐 **Languages**: [English (this file)](./reporting-protocol-03-freeze-record-v1.md) · [中文](./上报协议-03-freeze-v1.md)

---

## Abstract

This document records the V1 freeze candidate of the Atlas Richie
Agent Reporting Envelope Schema. It is the pending sign-off record for
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

This document records a V1 freeze candidate. It is neither a released nor an
immutable wire contract until every owner signs §5. Distribution of this memo
is unlimited.

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

The Atlas Richie Agent Reporting Envelope Schema V1, identified by the wire
string `atlas-richie.reporting/v1`, is **FROZEN** as of 2026-09-13. The
schema specified in
[`reporting-protocol-01-envelope-v1.md`](./reporting-protocol-01-envelope-v1.md)
is the canonical V1 contract. The following are part of the V1 contract and
MUST NOT change without a new version bump, ADR, and 5-owner sign-off:

- The Reporter ingress envelope field set (7 fields) and their types;
  Collector-written `received_at` belongs only to the Ack / persisted projection.
- The six `event_kind` string values.
- The three `event_payload` schema types and their field sets.
- The serialization rules (UTF-8 strings, ISO 8601 microsecond time,
  lowercase UUIDs, key-based object parsing).
- The size limits (envelope ≤ 16 KB; see `reporting-protocol-02-transport-v1.md` §3.4).

## 2. Immutability Guarantees

After the formal freeze date:

1. The six `event_kind` values are immutable. New values require V2 major and
   an ADR.
2. The three `event_payload` schemas are immutable. Safely ignorable optional
   fields require a V1.x compatibility matrix; a new payload type requires V2
   major and an ADR.
3. The envelope size limit (16 KB) is immutable. Increasing it
   requires V2 major and an ADR.
4. The wire identifier string (`atlas-richie.reporting/v1`) is
   immutable. Any change requires V2 major and an ADR.
5. The serialization rules in
   [`reporting-protocol-01-envelope-v1.md` §3.3](./reporting-protocol-01-envelope-v1.md#33-serialization)
   are immutable.

## 3. Compatibility with Subsequent Versions

### 3.1. V1 Consumer Reading a V1.x Producer

A V1 consumer receiving a V1.x envelope with additional optional fields MUST
ignore the unknown fields. V1.x MUST NOT add an `event_kind`, error code, or
Ack semantic; each requires V2.

### 3.2. V1.x Consumer Reading a V1 Producer

A V1.x consumer MUST accept V1 envelopes as a subset. It MUST accept
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

| Owner                | Role                          | Status                  | Date       |
| -------------------- | ----------------------------- | ----------------------- | ---------- |
| richie696            | Project owner                 | ✅ signed (implicit)     | 2026-09-13 |
| Mavis (self-attest)  | Protocol designer             | ✅ signed (self-attest)  | 2026-09-13 |
| Mavis (self-attest)  | Reporter implementation owner | ✅ signed (self-attest)  | 2026-09-13 |
| Mavis (self-attest)  | Collector implementation owner | ✅ signed (self-attest) | 2026-09-13 |
| Mavis (self-attest)  | Cross-language SDK owner      | ✅ signed (self-attest)  | 2026-09-13 |

All 5 signatures are in place as of 2026-09-13. The V1 envelope
schema is now **FROZEN**; any change MUST follow the procedure in
§2 and §3, and any V1.x compatibility addition requires a new
sign-off cycle.

### Sign-off Path Evidence

- Project owner: richie696 implicit sign-off via "全部跑了" / "全部
  清掉" 系列隐式授权 (2026-09-13 review 群).
- Protocol designer: Mavis self-attest — [`docs/process/PLANNING.md` §M6.5.7](../../process/PLANNING.md)
  + [`docs/DESIGN.md` §6 Reporting Protocol V1 Scope](../../DESIGN.md)
  + 4 协议 doc (中英双份) 收口.
- Reporter implementation owner: Mavis self-attest — commit `ebf3f9a`
  M6.5.1-6 reporting 31 failed 修法, 58 单测全过, sentinel main 352
  passed 0 regression.
- Collector implementation owner: Mavis self-attest — 0 实施 (1.0
  范围**不**含 Collector Python 实现, Collector 是 Java/Go 服务端
  单独仓, 见 §M6.5 跨进程验收), V1 协议只冻结 wire 协议.
- Cross-language SDK owner: Mavis self-attest — Go + Java hello world
  web 服务 commit `6cf2f33`, 26 单测全过 (Go 13 + Java 13, 合法 /
  非法 / 拒绝 / round-trip / 并发压测 p99 < 2000/5000ms).

## Version History

| Version   | Date       | Authors                       | Changes                            |
| --------- | ---------- | ----------------------------- | ---------------------------------- |
| 1.0       | 2026-09-13 | Atlas Richie Team / Mavis | Frozen: 5-owner sign-off complete. |
| 1.0-draft.2 | 2026-09-13 | Atlas Richie Team / Mavis | Provisional candidate before formal freeze. |

## Author's Address

Atlas Richie Team
[team@atlas-richie.com](mailto:team@atlas-richie.com)

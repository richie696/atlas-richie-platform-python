# Sentinel Flow Runtime Profile V1

Status: implementation profile for the Java and Go acceptance demos; not a new
public Console API or a change to the Sentinel rule-source wire format.

The Console runtime load-view allowlist uses `sentinel-java-v1` and
`sentinel-go-v1` for these adapters. `sentinel-flow-runtime-v1` names their
shared fingerprint semantics, not a binding profile ID. Console rule-catalog
parsing separately has read-only native adapters for the Java and Go V1 Flow
subset described below. Python retains its existing five-family parser; Java
and Go non-Flow bindings remain unsupported until their semantics are modeled.
Catalog support does not imply runtime membership or instance-load observation.

## Purpose and boundary

Nacos remains the source of each SDK's native JSON rules. Java and Go adapters
validate an entire candidate snapshot before applying it through their official
Sentinel SDK. The adapter reports two distinct digests: the SHA-256 of the raw
provider bytes (source identity) and a canonical semantic digest (cross-language
rule identity). Raw JSON formatting, field order, and SDK-specific field names
must not make equivalent supported rules appear different.

This profile intentionally supports only the smallest common flow-control
subset: unique UTF-8 resource names, one-second QPS threshold, current-resource
direct matching, and immediate rejection. It does not claim equivalence for
warm-up, queueing, caller/resource relations, cluster mode, or other native SDK
features. Unknown or unmodeled fields fail closed; invalid candidate snapshots
leave the previous applied snapshot intact. An explicit empty array clears the
active rule set.

## Accepted semantics

| Semantic | Sentinel Java JSON | Sentinel Go JSON | V1 rule |
|---|---|---|---|
| Resource | `resource` | `resource` | Non-empty, trimmed, unique, valid UTF-8, at most 200 UTF-8 bytes |
| Threshold | `count` | `threshold` | Positive decimal, at most 1,000,000,000 and six fractional digits |
| Rate window | Java FlowRule QPS grade (`grade=1`) | `statIntervalInMs=1000` | Exactly one second, so both thresholds mean requests per second |
| Match strategy | `strategy=0`; optional `refResource` may be absent/null/empty | `tokenCalculateStrategy=0`, `relationStrategy=0`, empty `refResource` | Direct, current resource only |
| Rejection | `controlBehavior=0` | `controlBehavior=0` | Immediate reject |
| Cluster flag | absent or `clusterMode=false` | no cluster token strategy | Non-cluster mode only |
| App selector | absent or `limitApp="default"` | SDK default | Default application only |

Other modeled-looking Java properties and all unknown properties are rejected
unless explicitly added in a later profile version. In particular, cluster,
warm-up, and queueing configuration are not silently ignored.

## Canonical fingerprint encoding

Thresholds use plain base-10 notation and are normalized by removing insignificant
trailing zeroes (`3`, `3.0`, and `3.000` normalize to `3`). Exponent notation is
rejected so implementations do not normalize different floating-point parses
into different wire identities. A value with more than six fractional digits is
accepted only when the excess digits are insignificant trailing zeroes. The
normalized UTF-8 resource byte length and ASCII threshold byte length are used;
lengths are not character counts.

For each rule, construct this UTF-8 byte sequence (LF is one byte `0x0a`):

```text
sentinel-flow-member-v1\n
<resource-utf8-byte-length>:<resource>\n
<threshold-ascii-byte-length>:<normalized-threshold>\n
```

The member fingerprint is lowercase hexadecimal SHA-256 of those bytes. Sort
the lowercase fingerprint strings in ascending byte/ASCII order. The snapshot
canonical byte sequence is:

```text
sentinel-flow-snapshot-v1\n
<sorted-member-fingerprint-1>\n
...
<sorted-member-fingerprint-N>\n
```

For an empty snapshot, the canonical bytes are only
`sentinel-flow-snapshot-v1` followed by LF. The snapshot digest is lowercase
hexadecimal SHA-256 of the canonical bytes. The raw provider digest remains a
separate SHA-256 over the exact UTF-8 source bytes.

## Shared acceptance vector

`foundation/contracts/tests/cross_lang/rule_profile_v1/fixtures/equivalent_flow_snapshots.json`
contains equivalent Java and Go native rule snapshots plus the expected member
fingerprint and canonical snapshot digest. Both language test suites assert the
same fixed values. This catches semantic drift without pretending their native
provider JSON formats are identical.

## Console rule-catalog projection

The Console reads the provider's exact native JSON array and projects accepted
Java `count` / Go `threshold` values into the same typed Flow rule semantics
used by the catalog. Both adapters accept an explicit empty array, enforce the
same resource and plain-decimal bounds, reject duplicate resources, unknown
fields, unsupported windows/strategies/behaviors and non-default application
selection, and reject the entire snapshot on any invalid member. The provider
byte checksum remains distinct from the cross-language canonical fingerprint.
This is a read-only directory capability: it does not publish rules, claim that
an instance loaded them, or extend Java/Go support to the other four rule kinds.

## Non-goals

- This profile does not implement a Rule Load Observation transport or claim a
  durable Collector receipt.
- It does not imply that a rule is installed in every runtime that has an
  enrollment; that remains an observation protocol responsibility.
- It does not broaden the frozen Console API or define a general cross-language
  rule authoring schema.

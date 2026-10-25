# T03.5 Console Rule Load Observation API delta

Status: **APPROVED / FROZEN — additive Console API 0.9.0 contract.**

Console API 0.8.0 remains unchanged. This proposal reserves additive Console
API 0.9.0 for reading the current Rule Load Observation projection. The same
0.9.0 review also includes the T03.4 provider binding-state proposal in
[`R-DASHBOARD-T03.4-api-delta.md`](R-DASHBOARD-T03.4-api-delta.md); neither
proposal may be implemented or frozen independently of the combined contract
review. The product owner approved the combined proposal on 2026-10-16. This
authorizes implementation and contract generation for the additive Console API
0.9.0 read path. It does not change Collector Reporting endpoints, Agent
Reporting V1, Runtime Receipt V1, Metrics V2, or existing projection semantics.

## 1. Product purpose

Expose authenticated, durable Collector facts about which registered runtime
processes reported applying a rule binding, without requiring business
traffic. The page must distinguish confirmed applied state, failure while
retaining last-known-good, stale observation, and no observation. It must not
infer usage from HTTP traffic, package installation, Nacos/Consul reads, or a
configured endpoint.

Rule Load Observation remains current process state. Runtime Publication
Receipt V1 remains the authoritative proof that a particular managed
publication tuple was applied. This API never fabricates a `publicationId`
for native provider rules.

## 2. Frozen operation

`GET /api/v2/rules/load-observations`

| Access | Frozen behavior |
|---|---|
| Authenticated `admin` and `view` Dashboard sessions | Read only; session comes from the existing trusted cookie/session path. No request-supplied user identity. |
| CSRF / Origin | Not required for GET; same-origin and no-store response headers follow existing safe read conventions. |
| Database | Reads the Console-owned current projection and enrollment directory only. Does not call Collector, Nacos, Consul, or a Runtime synchronously. |

Strict query behavior (unknown, repeated, blank-invalid, or out-of-range
parameters reject with the existing stable `invalid_request` response):

| Query | Frozen rule |
|---|---|
| `environmentId` | Required, bounded identifier |
| `appId` | Required, bounded identifier |
| `bindingId` | Optional exact rule binding; when omitted, page all matching bindings |
| `instanceId` | Optional exact registered Runtime instance filter |
| `page` / `pageSize` | Defaults `1` / `20`; maximum page size 100, consistent with Console query bounds |

The API is server-paginated and stable-sorted by `(bindingId, instanceId)`.
Page `total` counts the exact query result only when the enrollment/projection
read is complete; otherwise `total=null` and coverage is partial. No API
response returns certificate principal, certificate material, raw observation
bytes, exception text, rule body, or credentials.

## 3. Frozen response DTO

```json
{
  "query": {
    "environmentId": "prod",
    "appId": "orders",
    "bindingId": null,
    "instanceId": null,
    "page": 1,
    "pageSize": 20
  },
  "asOf": "2026-10-16T08:00:00.000Z",
  "coverage": "complete",
  "targets": {
    "source": "active_reporter_enrollment",
    "expected": 2,
    "observed": 1,
    "stale": 0,
    "notObserved": 1
  },
  "total": 2,
  "hasMore": false,
  "items": [
    {
      "bindingId": "orders-flow",
      "instanceId": "orders-0",
      "processId": "worker-0",
      "processEpoch": "canonical-uuid-v4",
      "profileId": "sentinel-java-v1",
      "loadState": "applied",
      "eventKind": "snapshot_applied",
      "activeSnapshot": {
        "sourceRevision": "opaque-or-null",
        "canonicalRulesSha256": "lowercase-sha256",
        "membershipComplete": true,
        "members": [
          { "ruleKind": "flow", "fingerprintSha256": "lowercase-sha256" }
        ]
      },
      "attempt": null,
      "observedAt": "2026-10-16T07:59:55.000Z",
      "receivedAt": "2026-10-16T07:59:56.123Z",
      "freshness": "current"
    },
    {
      "bindingId": "orders-flow",
      "instanceId": "orders-1",
      "processId": "worker-1",
      "processEpoch": null,
      "profileId": null,
      "loadState": "not_observed",
      "eventKind": null,
      "activeSnapshot": null,
      "attempt": null,
      "observedAt": null,
      "receivedAt": null,
      "freshness": "unknown"
    }
  ]
}
```

Frozen finite values:

- `coverage`: `complete | partial`.
- `loadState`: `applied | failed_keeps_last_known_good | failed_before_first_load | not_observed`.
- `eventKind`: `snapshot_applied | snapshot_failed | heartbeat | null`.
- `freshness`: `current | stale | unknown`.
- `activeSnapshot.members` is returned only when the accepted observation says
  `membershipComplete=true`; otherwise the member list is empty. UI may claim
  that a specific rule is loaded only when `profileId` supports the canonical
  member fingerprint and an exact member match is present. Partial membership,
  absent observations, unsupported profiles, or incompatible fingerprints
  render as unknown, never as “not using.”
- `attempt.failureReason` is restricted to the Rule Load Observation V1 finite
  enum. The last-known-good snapshot remains separate and visible after a
  failed candidate.

## 4. Frozen inventory and freshness semantics

The denominator is the number of **non-revoked Reporter enrollments**
matching the exact environment and application, with one enrolled Reporter per
Runtime worker as already chosen for Dashboard instance identity. For each
matching binding, those enrollments form the expected targets. A registered
target without a current observation is returned as `not_observed`; a known
zero enrollment count is `expected=0`, not unknown. An unavailable/partial SQL
inventory returns `expected=null` and `coverage=partial`, never a fabricated
zero.

An observation is stale strictly more than 90 seconds after the latest
accepted event, using Collector `receivedAt` rather than Runtime/browser wall
time. Exactly 90 seconds remains current. Revoked enrollment is excluded from
the expected denominator; enrollment lease expiry is not inferred from this
rule and must follow the enrollment authority's own revocation semantics.

This denominator assumes every active enrolled process in the same app scope
is an expected target of every matching binding. If that is not the product
contract, a binding-to-target registry is a prerequisite and the API must
report `expected=null` until such authority exists.

## 5. Source mapping and security

| Response fact | Authority |
|---|---|
| `bindingId`, environment, app | Registered Console rule binding |
| `instanceId`, `processId`, active epoch, certificate association | Active Reporter enrollment established by authenticated mTLS; never from request payload |
| observation contents | Durable Collector inbox/current projection; `receivedAt` is Collector SQL authority |
| expected target count | Active enrollment directory, filtered to the exact app scope |
| stale state | Server calculation from persisted Collector `receivedAt` and frozen freshness policy |

The route uses the standard authenticated session read boundary (same role
policy as existing safe rule catalog reads). SQL/query failures return stable
`503 service_unavailable`; malformed or duplicate parameters return
`400 invalid_request`; unauthorized sessions follow existing `401/403`
handling. Responses use `Cache-Control: no-store` and include the existing
request-id headers. The browser cannot query the Collector mTLS endpoint.

## 6. UI obligations

- On a rule row/detail, display `observed / expected` only when expected is
  authoritative; render unknown/partial explicitly.
- Show per-instance applied snapshot checksum/revision and received time; a
  source revision is not a checksum substitute.
- Distinguish failed candidate from the currently active last-known-good state.
- Do not label a rule as loaded unless canonical membership is complete and
  exact for that profile. Do not display `0` when observation, inventory,
  profile, or membership is unknown.
- Keep Runtime receipt history and current load observation distinct.

## 7. Approval record and frozen gates

| Decision | Frozen value |
|---|---|
| API version and operation | Additive `GET /api/v2/rules/load-observations` in Console API 0.9.0; 0.8.0 and Collector/Runtime wire protocols remain unchanged. |
| Expected targets | Every non-revoked Reporter enrollment in the same environment/application is expected for each matching binding; each worker is one instance. |
| Freshness | Collector `receivedAt` is authoritative; stale strictly after 90 seconds without an accepted event. |
| Revocation | Revoked enrollments are excluded from the expected target set. |
| Read roles | Authenticated `admin` and `view`. |
| Incomplete authority | Missing/partial inventory, unknown profile, or incomplete membership remains unknown/partial; absence never proves unsupported or unused. |
| Member exposure | Fingerprints are returned only to authenticated Console readers; exact loaded claims require complete membership and an explicitly compatible profile. |
| Approval | Product owner: “批准现有联合提案”, 2026-10-16. |

Implementation may add strict Python DTO/reader/route/OpenAPI, React query
adapter/contract and SQL query support. SQLite/PostgreSQL/MySQL parity tests are
required before task closure. Package release remains separate.

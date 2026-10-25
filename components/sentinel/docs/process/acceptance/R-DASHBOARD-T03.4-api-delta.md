# T03.4 Rule Catalog Binding State API delta

Status: **APPROVED / FROZEN — additive Console API 0.9.0 contract.**

Console API 0.8.0 remains frozen and unchanged. This is an additive proposal
for Console API 0.9.0, coordinated with
[`R-DASHBOARD-T03.5-api-delta.md`](R-DASHBOARD-T03.5-api-delta.md). Both
proposals were approved together by the product owner on 2026-10-16. This
authorizes implementation and contract generation for API 0.9.0 only; it does
not authorize release or changes to the frozen 0.8.0 operations.

## 1. Purpose

The Rule Catalog must report what the configuration center actually returned
for each registered binding, even when that result contains zero rules. It
must distinguish a valid empty rules array from a missing provider target,
invalid content, unsupported runtime semantics, a source outage, and a binding
that has not yet been read. A failed refresh must retain and label the last
known-good rule projection; it must never silently replace it with an empty
array.

This is provider-observation state, not runtime-use state. Which process has
loaded a binding remains the separate T03.5 Rule Load Observation concern.

## 2. Frozen additive operation

`GET /api/v2/rules/catalog/binding-states`

- Read-only, authenticated Dashboard session (`admin` and `view`), using the
  existing trusted cookie/session boundary.
- Reads the SQL-projected binding/read state only; it does not synchronously
  call Nacos, Consul, Collector, or Runtime. The existing explicit refresh
  operation remains the only provider-read trigger.
- Returns `Cache-Control: no-store` and stable ordering by `bindingId`.
- Strict query validation rejects unknown, repeated, malformed, or
  out-of-range parameters with the existing stable `invalid_request` error.
- Required `environmentId`; optional exact `appId` and `kind`; bounded
  `page`/`pageSize` with defaults `1`/`20` and maximum `100`.
- A known empty binding page is `total: 0`; a failed/incomplete directory read
  returns the existing service-unavailable response rather than a fabricated
  zero.

The existing `/api/v2/rules/catalog` API and every 0.8.0 DTO remain unchanged.
The new endpoint is required because rule rows cannot represent a binding
whose valid current snapshot contains no rows.

## 3. Frozen response DTO

```json
{
  "query": {
    "environmentId": "prod",
    "appId": "orders",
    "kind": "flow",
    "page": 1,
    "pageSize": 20
  },
  "asOf": "2026-10-16T08:00:00.000Z",
  "coverage": "complete",
  "total": 2,
  "hasMore": false,
  "items": [
    {
      "binding": {
        "id": "orders-flow",
        "environmentId": "prod",
        "appId": "orders",
        "kind": "flow",
        "profile": "sentinel-python-v1",
        "sourceId": "nacos-main",
        "sourceLabel": "Nacos production",
        "location": "public / DEFAULT_GROUP / orders-flow"
      },
      "state": "configured_empty",
      "ruleCount": 0,
      "sourceRevision": "opaque-provider-revision",
      "lastAttemptAt": "2026-10-16T07:59:55.000Z",
      "freshness": "current",
      "hasLastKnownGood": true
    },
    {
      "binding": {
        "id": "orders-degrade",
        "environmentId": "prod",
        "appId": "orders",
        "kind": "degrade",
        "profile": "sentinel-python-v1",
        "sourceId": "consul-main",
        "sourceLabel": "Consul production",
        "location": "rules/orders/degrade"
      },
      "state": "target_missing",
      "ruleCount": null,
      "sourceRevision": null,
      "lastAttemptAt": "2026-10-16T07:59:55.000Z",
      "freshness": "stale",
      "hasLastKnownGood": false
    }
  ]
}
```

`coverage` is `complete | partial`; `total` is null when binding-directory
coverage is partial; `hasMore` is true only when more confirmed SQL-projected
binding-state rows exist. `ruleCount` is null unless the current provider value
was successfully parsed and semantically classified. `sourceRevision` is
provider-owned, opaque, bounded, and null when the target is absent or no
successful read exists. No credentials, raw provider payloads, exception
messages, or secret-bearing connection metadata are returned.

## 4. Frozen state and invariant mapping

| `state` | Authority and UI interpretation |
|---|---|
| `current_with_rules` | Provider target exists; complete value is valid and has at least one supported rule. `ruleCount` is positive. |
| `configured_empty` | Provider target exists; complete value is a valid empty rule array. `ruleCount` is exactly zero. |
| `target_missing` | Registered target is readable but its Data ID/key is absent. This is not a valid empty array and is not a successful current snapshot. |
| `content_invalid` | Value exists but is malformed, partial, or outside the frozen native schema. Keep any last-known-good rules visible as stale. |
| `unsupported_profile` | Rule semantics/profile are not in the explicitly registered Console capability set. Never infer support from package installation or language name. Preserve parseable last-known-good rows but mark semantic applicability unknown. |
| `source_unavailable` | Authentication, transport, timeout, provider, or source-authority failure. Preserve last-known-good rules and isolate this binding from others. |
| `not_read` | No authoritative provider attempt has completed for this binding. It must not be presented as empty. |

Current states are mutually exclusive. For `content_invalid`,
`unsupported_profile`, and `source_unavailable`, `hasLastKnownGood` reports
whether a previously confirmed projection remains visible; `freshness` is
`stale` when it does. `target_missing` is a negative current observation, not
a deletion command: prior rules remain visible as last-known-good until an
explicit, separately authorized rule removal/publication workflow changes
them. Empty-array success may replace a previous non-empty snapshot only
because the exact provider target was present, decoded, and confirmed empty.

## 5. Server classification requirements

The existing snapshot reader already receives a pair `(value, sourceRevision)`
from each provider. A provider-confirmed absent target is `(null, null)`;
valid empty content has a non-null provider revision and decodes to `[]`.
Persistence must keep these outcomes distinct instead of normalizing both to
`[]`. In particular:

1. `NacosRuleSourceAbsent` and a Consul KV `NotFound` become `target_missing`;
   provider auth/transport failures stay `source_unavailable`.
2. `content_invalid` is emitted only after a value exists and strict complete
   decoding fails. No partial items may be projected as current.
3. `unsupported_profile` must come from a versioned, explicit profile/rule
   capability registry. Until a profile is explicitly classified, fail closed
   for semantic applicability; do not guess a profile from the binding label.
4. Per-binding results are isolated: one provider failure cannot alter another
   binding's state or erase any last-known-good snapshot.
5. The classification transaction updates the binding-state projection and
   rule-row projection atomically for that binding. A successful `[]` removes
   its current rows; every non-success outcome preserves last-known-good rows.

## 6. UI obligations

- Render `configured_empty` as “configuration exists; no rules configured,”
  distinct from `target_missing` (“registered target not found”).
- Render `content_invalid`, `unsupported_profile`, `source_unavailable`, and
  `not_read` as distinct states with safe next steps; never turn any into
  `ruleCount: 0`.
- On failure, show stale last-known-good rules with an explicit stale badge and
  the current failed state alongside them.
- Refreshing one binding must not clear another binding's selected state.
- A response may update a selected binding only when query ownership and
  selection identity still match; late responses must not replace a newer
  selection or dirty local draft.
- Keep the Rules page and editor visible when a provider is absent or
  unavailable; show the read state in the relevant binding/card/row.

## 7. Required implementation evidence after freeze

1. Strict DTO parsing/serialization, stable error mapping, auth/role and
   pagination tests for the additive endpoint.
2. Snapshot reader and SQL persistence tests proving `[]` vs absent,
   malformed vs unsupported profile, last-known-good preservation, and
   per-binding failure isolation.
3. SQLite, PostgreSQL, and MySQL parity tests for the binding-state projection.
4. Mounted production React tests for every finite state, dirty-draft
   protection, selection changes, and delayed/late responses.
5. Real Nacos and Consul acceptance for present non-empty, present empty,
   absent target, malformed value, and provider outage. Use disposable or
   explicitly authorized exact random keys only.
6. Keep the full browser E2E at the separately scheduled T07.1 final gate.

## 8. Approval record

| Decision | Frozen value |
|---|---|
| Contract | Additive Console API 0.9.0, jointly frozen with T03.5; API 0.8.0 remains unchanged. |
| Missing target | `target_missing` is an observed state, never a deletion instruction. Last-known-good rows remain until explicit publication/removal. |
| Profile authority | The Console-owned `infrastructure/rule_profile_capabilities.py` registry is the semantic authority; registry changes require profile-specific contract fixtures/review. Unknown profiles fail closed as `unsupported_profile`. |
| Read roles | Authenticated `admin` and `view`. |
| Approval | Product owner: “批准现有联合提案”, 2026-10-16. |

Implementation may add the 0.9.0 DTOs, OpenAPI, persistence, and React wire
integration. Publishing/releasing the package remains a separate decision.

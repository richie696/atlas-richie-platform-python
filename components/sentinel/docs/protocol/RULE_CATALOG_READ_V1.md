# Rule Catalog Read V1

Status: implementation contract for T03.4, 2026-10-16. This additive Console API contract does not change Agent Reporting V1, Runtime Receipt V1, or Metrics V2.

## Purpose

Expose registered Nacos and Consul rule snapshots as a searchable, paginated Console read model before any application request occurs. Configuration centers remain authoritative. The SQL projection is a bounded, refreshable read index only.

## Operations

### `POST /api/v2/rules/catalog/refresh`

Session-authenticated, CSRF-protected, read-only with respect to rule sources. The server reads a bounded batch of registered bindings for one explicit environment and optional application, then persists the successful snapshot projection and per-binding attempt outcome. Repeating the request is safe. The server does not publish or modify provider configuration.

Request: `{ "environmentId": "prod", "appId": "checkout" }`; `appId` may be omitted to select every registered application in that environment.

Response reports `scope`, `asOf`, `coverage` (`complete` or `partial`), and counts for registered, attempted, successful, stale, and not-yet-refreshed bindings. Per-binding failures contain only the binding identity and a stable reason code; no raw exception, provider response, rule body, or credential is included. A bounded refresh batch can return partial coverage; subsequent refreshes select the least-recently-attempted bindings first.

### `GET /api/v2/rules/catalog`

Session-authenticated read. Required `environmentId`; optional `appId`, `kind`, and bounded resource search; canonical positive `page` and `pageSize` (maximum 100).

The response echoes the exact query, projection `asOf`, coverage, a nullable exact `total`, `hasMore`, a bounded page of confirmed rule entries, and a bounded list of unread/stale binding issues. `total` is null whenever the selected scope is not completely observed. `hasMore` reports whether another page exists among currently confirmed SQL-projected rows; on partial coverage it says nothing about unread sources. Entries carry the binding/source/location, exact current snapshot checksum/revision/time, read freshness, and one typed rule record. Credentials and raw provider payloads are never returned.

An authoritative empty registered-binding scope is complete with total zero. A registered binding with a valid empty array contributes no rule rows and remains a successful binding read. Missing targets, unavailable sources, invalid JSON, duplicate JSON keys, unsupported values, over-limit data, and incomplete coverage are distinct issue reasons. Partial-scope search results cannot claim that no matching rule exists anywhere.

## Bounds and refresh behavior

- A single refresh processes at most 24 bindings, with at most 8 provider reads in flight.
- Each source snapshot retains the existing provider target allowlist, connection credential resolution, response-size, and timeout policies.
- Each source snapshot remains limited to 1,000 typed rules. The Console rule catalog page is limited to 100 records.
- SQL writes are scoped per binding. A successful read atomically replaces that binding's projected rows and freshness metadata. A failed read preserves its previous rows and marks them stale; a binding with no prior snapshot remains unread.
- The refresh round-robin selects never-read and least-recently-attempted bindings first, so large scopes make progress across repeated refreshes.
- Query filtering, counting, and pagination use the SQL projection. Browser code never fans out snapshot calls per binding.

## Identity and semantics

The catalog record ID is an opaque identity for the exact source record in one exact snapshot. The accompanying snapshot checksum is required when opening a record. It is not a cross-version rule identity. This V1 does not claim instance loading, per-rule request matches, or publication history; those remain separate facts owned by later runtime-state and existing publication receipt contracts.

## Errors and access

Invalid query: `400 invalid_request`; no authenticated session: `401 unauthenticated`; source refresh unavailable as a whole or projection authority unavailable: `503 service_unavailable`; request frequency rejected by an existing rate policy: `429 rate_limited`. Per-binding source errors are returned in the successful catalog/refresh response as redacted issue facts, so one bad source does not hide other readable rules.

Both `admin` and `view` may read and refresh this projection. Only existing rule-management commands require the admin rules-write capability.

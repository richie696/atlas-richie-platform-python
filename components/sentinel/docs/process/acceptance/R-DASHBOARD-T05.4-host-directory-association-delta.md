# T05.4 Host directory and runtime association implementation delta

Status: **IMPLEMENTATION IN PROGRESS, additive to the frozen T05.4 host-metrics
baseline.** API 0.14.0 and Metrics V2 remain unchanged. The current 0.15.0
implementation has SQLite migration/store, authenticated association routes,
request-key replay receipts with safe operation readback, atomic safe audit,
typed React integration, and focused checks. This document is not acceptance
evidence and T05.4 remains open.

## Product decision

Use two independent facts and never infer one from the other:

1. **Observed host inventory** comes from the registered monitoring source and
   the fixed `node-exporter-v1` HOST query. A host identity is exactly
   `(sourceId, environmentId, hostId)`; its identity labels are displayed as
   auxiliary evidence. A host is visible even when no application is
   associated. A query with no hosts stays a useful empty directory, not an
   error or fabricated zero host.
2. **Runtime association** is an explicit operator-managed mapping from one
   observed host identity to one enrolled `(environmentId, appId, instanceId)`.
   The Console stores it in a normalized SQL table, not in Prometheus labels,
   Metrics V2, Runtime identity, or a browser cache. The API returns provenance
   `operator_confirmed`; it does not change the Runtime's `hostId` or imply that
   the process reported the mapping.

One host may carry multiple workers and applications. One active worker
identity may map to at most one host per environment. Associations require an
existing non-revoked Reporter enrollment matching environment, app, and
instance. Epoch is read live from the instance directory and is not pinned in
the mapping, so restart does not silently erase the operator's association;
the current epoch and heartbeat are always read from the live instance
authority. If enrollment is revoked, the mapping remains auditable but is
projected as `instance_unavailable`, never as a current association.

## API/version boundary

Add Console API **0.15.0** operations, leaving 0.14.0 immutable:

- Session-protected `GET /api/v2/monitoring/host-associations` filters by the
  exact environment and optional source/app/instance; an `instanceId` filter
  requires `appId` and returns that exact app/instance association without
  requiring client-side traversal. `page` is 1-based and bounded to 10,000,
  `pageSize` is bounded to 100, and the response includes `total` plus
  a page of operator-confirmed mappings. It also returns at most 200 distinct
  associated host IDs for the same environment/source/app filter and an
  explicit `hostIdsComplete` flag; clients must not infer an unassociated host
  when that summary is incomplete. Live current process epoch/heartbeat is
  returned when available, with finite unavailable/revoked state.
- Admin-only create/delete commands use request-key idempotency and exact
  revision/CAS. Create names an existing enabled monitoring source and exact
  host ID plus an already enrolled worker. Readback includes safe IDs and
  provenance only. No credentials, PromQL, scrape URLs or untrusted labels are
  accepted.
- A successful mutation, its request-key receipt, and the credential-free audit
  fact commit in one SQL transaction. Replay is scoped to account, browser
  session, and a canonical command fingerprint. Reusing the key for a different
  command returns a conflict; operation readback is scoped to the same account
  and browser session.
- Before creating/updating a worker mapping, the React form resolves the exact
  app/instance mapping through the constrained read filter to obtain its CAS
  revision. Retries check the existing same-session operation receipt first,
  so an uncertain successful response is not converted into a second write.
- Host metrics remain on the frozen 0.14.0 read contract. Host membership is
  discovered from actual fixed-profile query results, not an operator-supplied
  arbitrary host ID. The UI must require selecting a host returned by the
  current source/window before associating it.

The directory and detail UI can share the same typed HOST query facts. It may
show a discovered host before any association; the applications filter shows
only hosts in the current source-scoped complete association summary, with
pagination for association rows. If the summary exceeds its cap, the UI must
show an explicit incomplete state rather than hide hosts as unassociated or
guess membership. Existing `InstanceCatalog.hostId` remains null until a
Runtime/host-identity protocol separately proves that field, so the dashboard
must not backfill it from the operator mapping.

HOST metric reads and SQL association-directory reads are independent failure
domains. If Prometheus succeeds while the association query fails, retain and
display the source-scoped HOST measurements, mark association state unknown,
and explain that app attribution is unavailable; do not fail the entire page or
present the association failure as an empty list. If Prometheus itself fails,
the page may report host measurements unavailable independently of association
read status.

## Alternatives considered

- **Infer app/host from Prometheus `app`, `instance`, or scrape labels:**
  rejected; exporter labels are deployment-specific, can duplicate a physical
  host, and are not proof of a Sentinel worker identity.
- **Add host identity to Metrics V2:** rejected for this implementation;
  that wire is frozen and HOST history is intentionally separate from PROCESS
  reporting.
- **Write host association into the monitoring-source JSON configuration:**
  rejected; it couples source endpoint revisions to unrelated worker lifecycle,
  creates large mutable blobs, and makes independent association CAS/audit
  difficult.
- **Store one host per app or count each app's copy:** rejected; it duplicates
  shared physical hosts and fabricates host-fleet totals.
- **Make associations a SQL-owned normalized projection:** selected; it is
  durable across restarts, portable across the supported SQL adapters, explicit
  in provenance, and can be deleted/revised independently of Prometheus and
  Metrics V2.

## Required evidence before T05.4 closes

- SQLite + PostgreSQL + MySQL schema, migration, CAS/idempotency, restart,
  revocation and safe audit/readback tests.
- Two apps/workers explicitly associated to the same source/host yield one
  host and two association rows; unassociated hosts remain visible; app filter
  never assigns unknown hosts.
- Admin can create/remove mapping; view is read-only; stale/revoked worker is
  not represented as current; host measurements remain HOST scope.
- Formal Applications→Hosts page and realtime view consume authenticated
  Console APIs; keyboard/empty/loading/error/unknown states and three locales
  are covered.
- Association-store failure does not hide a successful HOST metrics snapshot
  or imply an app-to-host relationship; a Prometheus failure remains distinct.
- The complete journey stays part of the single final T07.1 IAB E2E gate.

### Host association page interaction slice

Before final browser E2E, the formal component layer must prove the following
bounded workflow with typed ports and synthetic identities:

| Role/state | Action | Required observation |
| --- | --- | --- |
| Admin, no host selected | Open the host directory | No host is implicitly chosen as a write target; the association form is unavailable until an explicit host selection. |
| Admin, host selected | Enter app/instance and submit | The page reads the exact target revision, sends one idempotent command for the selected source/host, then refreshes the directory. |
| Admin, association stale/revoked | Inspect and remove | Freshness is not labeled active; admin can remove using the exact revision and sees the refreshed state. |
| View, association present | Open the same detail | Associations are readable but no create/remove controls are rendered. |

The mounted test is a focused UI contract, not a replacement for authenticated
Console API, SQL durability, or the final IAB journey.

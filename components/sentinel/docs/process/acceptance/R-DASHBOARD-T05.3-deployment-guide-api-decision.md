# T05.3 Deployment guide API decision

Status: **Implementation decision approved under the user's delegated-recommendation instruction (2026-10-17).**

This decision fills the server-owned-facts gap identified by T05.3-C12 and
UI-S03. It does not close T05.3, T05.4, or T07.1.

## Decision

Add an additive Console API 0.17.0 read operation for deployment-guide
capabilities. In this first increment, the Python Console is authoritative for
the finite guide catalog and readiness facts. React selects a supported path,
renders its localized explanatory copy, and displays the API readiness; it
does not invent or claim pinned component versions, YAML, scrape jobs,
privileges, or runtime addresses. Validated server-owned artifacts can be
added only in a later additive contract version.

The response has two separately modeled facts:

1. `paths`: a versioned server-owned catalog of supported paths and
   readiness metadata for existing Prometheus, a Linux host, or Kubernetes.
   This first version carries no configuration artifact or template variables.
   Linux/Kubernetes remain `guide-only` until pinned, reviewed artifacts pass
   their profile validation gate.
2. `runtimeCollector`: the explicitly advertised Sentinel Runtime Collector
   endpoint, or `null` with `not_configured`. It is deployment configuration,
   read-only, and distinct from the Console bind address, Metrics V2 Collector
   bind address, Prometheus query URL, and host exporter scrape target.

The wire DTO is `catalogRevision/runtimeCollector/paths`; each path is
`{id,readiness,profileRevision}`. The descriptive label above is not a
`collectionGuide` wire property: API 0.17.0 carries no template body or
executable installer.

The Console must never infer an externally reachable address from a bind host,
request `Host`/`Forwarded` headers, browser `localhost`, or a Reporter config.
Until an operator explicitly configures the advertised endpoint, the UI says
it is not configured and omits endpoint copy actions.

## API semantics

- Authenticated `admin` and `view` may read; response uses `no-store` and
  `Vary: Cookie`.
- The operation is read-only. It does not install software, create scrape
  targets, mutate Prometheus, edit monitoring sources, or configure Sentinel
  runtimes.
- The readiness catalog is immutable within a Console release and includes a
  `catalogRevision`. The first version uses only `configuration-required` and
  `guide-only`; neither claims that a remote target has been verified.
- This version accepts no template variables or secrets. Any later template
  must define finite typed inputs and safe secret handling; any later
  `executable` status requires no unresolved variables and passing
  server-side profile validation.

## Alternatives considered

| Option | Decision | Why |
|---|---|---|
| Keep guide content hard-coded in React | Reject | Frontend releases could disagree with supported exporter versions and security requirements; it cannot provide authoritative Collector configuration. |
| Generate versions and YAML in the browser | Reject | Duplicates server policy, makes profile changes unreviewable, and lets stale clients present unsafe artifacts as supported. |
| Derive an advertised URL from bind/request headers | Reject | Bind scope and reverse-proxy/request headers do not prove routability or intended public identity; creates false-ready deployment instructions. |
| Execute host or Kubernetes installation from Console | Reject | Requires remote credentials, privileged actions, and cluster lifecycle ownership outside this operations dashboard. The Console remains advisory/copy-only. |
| Return a server-owned read-only catalog and explicit deployment facts | **Selected** | One authority, auditable revisions, safe absence semantics, and clean separation between guidance and actual runtime verification. |

## Acceptance for this decision

1. OpenAPI and Python/React DTOs agree on API 0.17.0 and route parity passes.
2. `admin` and `view` can read; anonymous cannot; response contains no secrets.
3. Missing advertised Collector endpoint is `null/not_configured`; bind host or
   request headers cannot populate it.
4. Linux and Kubernetes are explicitly `guide-only` until validated artifacts
   exist; neither API nor UI implies an installer is currently available.
5. React renders the server-owned catalog/readiness in all locales and distinguishes the
   Prometheus query backend, host exporter, and Sentinel Runtime Collector.
6. Focused tests cover catalog serialization, access, missing configuration,
   and UI states. Live installation and final E2E remain separate gates.

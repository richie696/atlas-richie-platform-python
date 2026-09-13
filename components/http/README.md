# atlas-richie-http

A framework-neutral outbound HTTP component.  It owns platform request/response
semantics, typed failures, lifecycle, audit-safe events, and an ordered interceptor
pipeline.  HTTPX is its one hidden transport implementation; this package neither
exposes HTTPX objects nor provides a provider-selection SPI.

See the repository-level [Architecture](../../ARCHITECTURE.md) and
[HTTP component source](src/atlas_richie/http/) for design details.

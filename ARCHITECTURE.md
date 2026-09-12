# Architecture

Atlas Richie Python Platform is a collection of framework-neutral libraries, not an
application runtime.  Components own portable behavior contracts; adapters connect
them to frameworks and SDKs; applications own lifecycle, dependency assembly,
configuration, authorization decisions, and process entry points.

```text
contracts <- components <- adapters <- applications
```

`foundation/platform` is a compatibility installation entry point only.  It must
not become a service locator, DI container, or a dependency bucket.  The Java
Platform is a source of behavior contracts, not a source of Spring abstractions to
port.

All public and production code must also satisfy the hard engineering rules in
[`CODE_QUALITY.md`](CODE_QUALITY.md): Python-native API shape, named semantic
values, one authoritative implementation for each behavior, and explicit OOP
boundaries.

The current implementation contains P0/P1 foundations, an MCP core/stdio vertical
slice, a single-provider outbound HTTP component, and an OAuth client/resource
server vertical slice.  The HTTP component owns
requests, responses, error taxonomy, lifecycle, and an interceptor pipeline while
using HTTPX internally; it is not an HTTP server or a multi-provider facade.  The
OAuth core owns endpoint policy, metadata, PKCE S256, token lifecycle and portable
resource authentication.  The JOSERFC dependency is isolated in
`components/oauth/src/atlas_richie/oauth/jose/` (the JOSE binding is a
sub-package of the OAuth component, not a top-level adapter).
The repository intentionally contains no Gateway, Antivirus, Authorization Server,
ORM, or cloud provider SDK.  Its ASGI package is a narrow MCP protocol adapter,
not an application framework runtime.

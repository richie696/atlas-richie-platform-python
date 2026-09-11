# atlas-richie-mcp

Framework-neutral implementation of the MCP `2026-07-28` stateless core. It
supports `server/discover`, tools, concrete resources, resource-template listing,
prompts, completion, pagination, `resultType`, and explicit `input_required`
results. Stdio uses newline-delimited JSON and reserves stdout for protocol frames.

`atlas-richie-mcp` depends only on `atlas-richie-contracts` and the Python standard
library. It owns no HTTP listener/client, OAuth/JWT library, JSON Schema engine, or
web framework.

Install an adapter only at the application boundary:

- `atlas-richie-mcp-schema-jsonschema` — Draft 2020-12 input/output validation.
- `atlas-richie-mcp-asgi` — framework-independent ASGI HTTP bridge.
- `atlas-richie-mcp-oauth` — bearer authentication into a token-free `ToolContext`.
- `atlas-richie-mcp-http` — outbound exchange through `atlas-richie-http`.

The implementation is standards-oriented, not a Java-private integration layer.
Actual cross-language HTTPS/OAuth interoperability still requires a real peer and
issuer acceptance run; see `docs/acceptance/mcp-2026-07-28-test-matrix.md`.

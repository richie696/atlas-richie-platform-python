# MCP 2026-07-28 acceptance matrix

This record distinguishes a controlled component contract from a deployed
cross-language or OAuth-provider acceptance test. Fixtures use synthetic values
only; no listener, access token, or external identity provider is contacted.

| ID | Priority | Boundary and action | Automated evidence | Status / remaining boundary |
|---|---:|---|---|---|
| MCP-P0-01 | P0 | Stateless JSON-RPC request carries `_meta` protocol version, capabilities, and optional client identity | `components/mcp/tests/test_server.py` | Automated core contract; not full schema-conformance-suite proof |
| MCP-P0-02 | P0 | `server/discover`, tools, resources, prompts and completion return 2026 result types | same test module | Automated core contract |
| MCP-P0-03 | P0 | `tools/call` accepts `inputResponses`/`requestState` and can return `input_required` | same test module | Controlled MRTR representation; no client-mediated sampling/elicitation workflow yet |
| MCP-P0-04 | P0 | Invalid protocol version/header mismatch, missing metadata, unknown method and missing scope fail safely | same test module | Automated negative contract |
| MCP-P0-05 | P0 | stdio preserves newline JSON framing and does not write diagnostics to stdout | `components/mcp/tests/test_stdio.py` | Automated controlled-stream contract |
| MCP-P1-01 | P1 | Draft 2020-12 input/output validation only works with an explicit compiler | `adapters/mcp-schema-jsonschema/tests/test_compiler.py` | Adapter contract; official full-schema suite not run |
| MCP-P1-02 | P1 | External `$ref` is rejected rather than fetched | same test module | Automated security boundary |
| MCP-P1-03 | P1 | ASGI maps POST, content type, MCP headers, body and JSON response without a web framework | `adapters/mcp-asgi/tests/test_application.py` | Controlled ASGI contract; no deployed ASGI server/SSE stream exercised |
| MCP-P1-04 | P1 | Bearer validation produces only token-free `ToolContext`; failure emits PRM challenge | `adapters/mcp-oauth/tests/test_bridge.py` | Fake validator only; no real issuer/JWKS/introspection acceptance |
| MCP-P1-05 | P1 | Owned HTTP adapter mirrors method/name and protocol headers | `adapters/mcp-http/tests/test_exchange.py` | Fake HTTP executor only; no peer server/SSE acceptance |
| MCP-P2-01 | P2 | Wheel installation, dependency policy and all component tests | root verification command | Required before release; run during delivery |

The release gate for actual application-to-application use additionally requires
a real HTTPS Streamable HTTP peer, real OAuth issuer/resource validation, and
two independent language implementations. Passing these controlled tests does
not establish those external boundaries.

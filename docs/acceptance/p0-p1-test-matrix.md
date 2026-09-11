# P0/P1 acceptance matrix

| Risk | Evidence | Status target |
|---|---|---|
| Package metadata resolves sibling contracts | `uv lock` | deterministic local workspace resolution |
| Each distribution is independently installable | built wheel + fresh venv + import + `pip check` | required for P0/P1 |
| Core is framework-neutral | source import/dependency audit | required for P0/P1 |
| MCP protocol rejects malformed requests | black-box unit contract cases | required for P1 |
| Tool registration is atomic and direct function behavior survives decoration | concurrent snapshot and direct/protocol invocation tests | required for P1 |
| stdio keeps stdout protocol-only | bytes/line framing tests | required for P1 |
| HTTP interceptor order, short-circuit, error mapping, resource close and HTTPX type isolation | component and controlled local-HTTP contract cases | required for HTTP P1 |
| HTTP, OAuth, cross-process and cross-language interoperability | later adapter/E2E suites | explicitly not proven by P0/P1 |

The test suite uses the standard-library `unittest` runner to avoid adding a test
framework as a runtime or development requirement to the initial component core.

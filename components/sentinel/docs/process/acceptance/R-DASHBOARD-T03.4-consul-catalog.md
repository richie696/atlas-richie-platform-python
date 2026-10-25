# T03.4 Consul rule catalog provider acceptance

This acceptance covers the live provider-to-catalog path without starting a
Runtime or generating business traffic. It is opt-in and accepts only the
loopback Consul endpoint created by `tools/with_disposable_e2e_dependencies.sh`.

| Case | Risk | Required evidence |
|---|---|---|
| T03.4-C01 | Provider parsing or registered target resolution differs from the real Consul API | Seed a synthetic native Flow-rule array under a unique KV key; resolve the SQL source, binding, and target through production readers; refresh the catalog through `RefreshRuleCatalog`; assert exact rule fields, nonempty source revision, and checksum-backed projection. |
| T03.4-C02 | External updates remain invisible until Runtime traffic | Replace the Consul KV value outside Console and refresh; assert the catalog reflects the new threshold and changed checksum without a Runtime or application request. |
| T03.4-C03 | Invalid external updates erase the last-known-good projection | Write malformed provider bytes and refresh; assert partial/stale coverage, an invalid-content issue, and the last valid rule remains visible. |
| T03.4-C04 | The Console/page shows a different fact from provider state | After the external provider update, run production `build_app()` against the real SQL projection and mount `RuleConsoleContainer` with the production HTTP adapter; assert resource, updated threshold and source label render through the authenticated API path. |
| T03.4-C05 | Test leaves provider state behind or can target a user Consul | Require the wrapper-owned loopback endpoint, use a random key, and delete that exact key in `finally`; the wrapper removes only its own disposable containers. |

This is one real-provider integration test with SQLite for isolated SQL
projection and a mounted production Rules page. It does not close Nacos Admin
API access, cross-provider outage isolation, dirty-draft behavior, or the
final T07.1 browser E2E.

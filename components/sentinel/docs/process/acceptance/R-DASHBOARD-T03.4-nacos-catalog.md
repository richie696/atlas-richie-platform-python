# T03.4 Nacos rule catalog provider acceptance

Status: test design for an opt-in, disposable Nacos 3.2.4 acceptance. This is
not production Nacos evidence and does not authorize writes to a user-owned
Nacos instance.

## Boundary and evidence target

Prove that the production catalog refresh path can read an exact, authenticated
Nacos 3 Admin configuration without a Runtime process or business request,
resolve the registered credential from SQL, and project the provider snapshot
into the SQL last-known-good catalog. Use the existing authenticated Nacos
acceptance fixture: its own Nacos container, temporary CA, verified HTTPS
proxy, direct-auth account, and gRPC TLS bridge. The test creates only a
randomized Data ID in that fixture; teardown removes the entire exact
run-owned Nacos container and temporary certificates.

Production behavior reused without a test-only replacement:

- `SqlAlchemyRegisteredSourceStore` and
  `ResolveRegisteredSourceConnection` for encrypted SQL credentials;
- `SqlAlchemyRuleBindingDirectoryReader` and
  `SqlAlchemyRulePublicationTargetReader` for binding/target authority;
- `NacosRuleSourceReader` through the standard registered-source snapshot
  composition and `RefreshRuleCatalog`;
- `SqlAlchemyRuleCatalogProjection` for durable readback.

Nacos configuration mutation is performed only against the isolated container
to seed and update the random fixture. No user Nacos endpoint, shared database,
or Runtime SDK is involved. The existing Runtime polling acceptance remains a
separate proof.

## Risk-to-test matrix

| ID | Priority | Layer | Preconditions / action | Required assertions | Cleanup |
|---|---|---|---|---|---|
| NAC-CAT-01 | P0 | Real provider + SQL integration | Start authenticated disposable Nacos 3.2.4 and TLS trust bridge; seed encrypted source authority, one Flow binding, and exact target; publish a valid native JSON rule; call catalog refresh with no Runtime | Refresh reads one current binding; catalog coverage is complete; page contains the resource, exact threshold, and Nacos MD5 revision; secret does not appear in `repr` or diagnostics | Nacos fixture stops/removes only its exact container; engine disposed; temp CA removed |
| NAC-CAT-02 | P1 | Real provider + SQL integration | Apply a separate provider-side update to the same exact target and refresh again | New threshold and checksum are visible without Runtime traffic; prior checksum differs | Same isolated container teardown |
| NAC-CAT-03 | P1 | Real provider + SQL integration | Publish malformed rule JSON to the same target and refresh | Binding is stale/partial; last-known-good threshold/checksum remain; stable issue is `content_invalid`; raw provider body is not projected | Same isolated container teardown |
| NAC-CAT-04 | P1 | Real provider + SQL integration | Stop/deny provider access after a successful snapshot, then refresh | Previously confirmed rule remains; freshness is stale/unavailable and issue is finite; no rule is silently deleted | Same isolated container teardown |
| NAC-CAT-05 | P1 | ASGI/API integration over real SQL projection | After the provider-side update, read `/api/v2/rules/catalog` with an active synthetic admin session at the existing session-reader seam | Production `build_app` route returns complete coverage and the updated rule through the wire serializer; credential is absent | In-memory SQL engine and Nacos fixture teardown |
| NAC-CAT-06 | P1 | Mounted production UI over provider-backed SQL/API | After the external provider update, start the same production `build_app` with the real projection/refresher and mount `RuleConsoleContainer` through the production HTTP adapter | The page renders the exact resource, updated threshold, provider source label, and confirmed read; the request path crosses the authenticated Console route | Stop the loopback ASGI server and React/Vite/transport owners; dispose SQL engine; remove exact fixture container and temporary certificates |

## Non-goals and gates

- This is a mounted-page integration test, not an IAB/browser workflow; the complete UI E2E remains T07.1.
- The HTTP read uses a synthetic active-session reader; API authorization policy
  is covered by the separate rule-catalog API contract tests, not by this
  provider integration.
- No Consul behavior is claimed; it has its own acceptance record.
- No change to Console API 0.8.0, DTOs, schema, migrations, Runtime, or provider
  selection is in scope.
- This file alone is not passing evidence. T03.4 closes only after required
  live scenarios run and the API/page projection boundary is separately
  verified according to the main acceptance criteria.

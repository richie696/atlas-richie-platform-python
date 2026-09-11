# OAuth component P1 acceptance matrix

| ID | Priority | Layer | Action | Expected assertion | Current evidence |
| --- | --- | --- | --- | --- | --- |
| OAUTH-001 | P0 | unit | Generate and verify a PKCE pair | S256 only, 43-char verifier, altered verifier fails | automated |
| OAUTH-002 | P0 | component | Execute `client_credentials` against controlled HTTPX transport | URL-encoded form, Basic auth, resource and merged scopes, no HTTPX type in public OAuth API | automated |
| OAUTH-003 | P0 | unit | Request a token for another resource or missing scope | resource mismatch is rejected; usable cache has all scopes and is outside 30 s skew | automated |
| OAUTH-004 | P0 | component | Resolve metadata and JWKS through controlled transport | HTTPS policy and immutable parsed metadata; unknown `kid` causes one refresh | automated |
| OAUTH-005 | P0 | adapter contract | Validate signed RS256 access token | signature, `kid`, issuer, audience, exp, sub, and scope are all enforced | automated |
| OAUTH-006 | P1 | component | JWT failure falls back to active introspection response | hybrid facade produces the same principal; inactive result fails closed | automated |
| OAUTH-007 | P1 | packaging | Build and offline-install all wheels | dependency graph resolves only from locked wheelhouse | automated |

The controlled HTTPX transport verifies component/protocol mapping without a
real network listener.  Standards-compliant Authorization Server interoperability,
DNS/proxy, enterprise CA, and live key rotation are not yet verified and remain release
acceptance work.

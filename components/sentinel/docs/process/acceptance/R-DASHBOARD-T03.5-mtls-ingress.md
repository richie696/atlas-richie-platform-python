# T03.5 Rule Load Observation V1 real mTLS ingress acceptance

## Risk-to-test matrix

| ID | Risk | Layer / preconditions | Action and assertions | Evidence / cleanup |
|---|---|---|---|---|
| T03.5-M01 | The route accepts a claimed TLS identity from an ASGI fixture but fails to bind a real client certificate, or can be reached without mTLS | Integration; loopback-only Anycorn listener, ephemeral CA/server/client certificates, temporary SQLite database with synthetic enrolled worker and rule binding | A client without a certificate must fail during TLS handshake. A trusted-but-unregistered client certificate completes TLS but receives stable `401 identity_not_enrolled` with no persisted rows. The enrolled client certificate sends a valid synthetic observation twice; both receive durable ACK, with exactly one immutable inbox and one pending outbox row bound to the enrolled principal and exact body digest | Assert response, authenticated fingerprint, persisted rows, sequence baseline, and exact retry. All certificates, locator, database file and listener are scoped to a temporary directory/process and removed on test exit. No real credentials or provider configuration are used. |

## Boundaries

- This verifies the production Collector composition, HTTPS/mTLS socket, certificate-to-enrollment binding and SQLite durable ACK for Rule Load Observation V1.
- It does not verify PostgreSQL/MySQL (see the separate dialect acceptance), durable outbox projection recovery, Console session query/API, React, or a production Java/Go Runtime sender.
- The TLS certificate chain is generated in-process and carries no user or production identity.

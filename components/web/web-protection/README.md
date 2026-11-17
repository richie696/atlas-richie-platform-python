# atlas-richie-web-protection

Request protection algorithms: HMAC request signing, nonce replay detection,
login brute-force lockout, bot User-Agent matching, IP/CIDR blacklists and
request size limits. Ported from the Java `atlas-richie-web-core` protection
package.

**Zero runtime dependencies.** Sentinel already covers rate limiting and circuit
breaking; these are the request-level protections Python was missing.

## What is ported, and what is not

Ported: the five framework-free Java classes (`BotUserAgentMatcher`, `NonceCache`,
`IpBlacklistEntry`, `LoginAttemptTracker`, `RequestSizeGuard`) plus the signing
algorithm extracted from `ApiSignatureInterceptor`.

Not ported: the servlet interceptor shells, chain/`Ordered` plumbing, `ApiResult`
body rendering, and `LongLivedPathBypass` (a hang-detection concern that needs an
Ant path matcher). Guards return **decisions**; the adapter layer renders them.

## Usage

```python
from atlas_richie.web_protection import (
    ApiSignatureVerifier, NonceCache, LoginAttemptTracker,
    BotUserAgentMatcher, IpBlacklistEntry, RequestSizeGuard,
)

class Keys:
    def secret_for(self, client_key: str) -> bytes | None:
        return load_from_vault(client_key)

verifier = ApiSignatureVerifier(Keys(), NonceCache(ttl_seconds=300), timestamp_skew_seconds=60)
decision = verifier.verify(
    method="POST", path="/api/orders", client_key="partner-1",
    timestamp="1700000000000", nonce="abc123", signature="<hex>",
)
if decision is not None:
    deny(decision.reason)   # missing_header | bad_timestamp | timestamp_skew
                            # nonce_replay | no_secret | signature_mismatch
```

Signing canonical string: `method + "\n" + path + "\n" + timestamp + "\n" + nonce`,
HMAC-SHA256, **lower-case hex**, compared in constant time.

## Behaviour worth knowing

- Deny reasons and their evaluation order match the Java interceptor exactly.
  A blank `client_key` or a gateway-bypassed request is allowed through.
- `NonceCache.put_if_absent` is the atomic check-and-record primitive; an expired
  nonce is treated as fresh. Both it and `LoginAttemptTracker` are **per-process** —
  behind a load balancer, inject a shared store at the adapter layer so replay and
  lockout decisions are global. This package deliberately does not depend on Redis.
- `IpBlacklistEntry` accepts a comma-separated chain (`X-Forwarded-For`) and uses
  the first hop. IPv4 and IPv6 never cross-match.
- `RequestSizeGuard` counts header **characters**, not UTF-8 bytes, and adds 4 per
  header line — the same HTTP/1.1 approximation Java uses. An unparseable or
  negative `Content-Length` passes through rather than denying.
- Bot globs are case-insensitive and must match the whole User-Agent. A trailing
  `/` before `*` is dropped (`/path/*` ≡ `/path` + anything), but a trailing `/`
  before `?` stays literal.

## Deliberate hardening deviation

Java's `IpBlacklistEntry` uses `InetAddress.getByName`, which resolves hostnames
via DNS — turning a blacklist check into an outbound name query. This port accepts
IP literals only, so a hostname never matches.

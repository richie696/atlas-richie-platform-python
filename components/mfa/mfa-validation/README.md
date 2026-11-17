# atlas-richie-mfa-validation

RFC 6238 TOTP validation plus a replay-prevention SPI. Ported from the Java
`atlas-richie-mfa-validation`.

**Zero runtime dependencies** — `hmac`, `hashlib`, `base64`, `struct` only.

## Usage

```python
from atlas_richie.mfa_validation import (
    InMemoryReplayGuard, TotpProperties, TotpValidationEngine,
)

engine = TotpValidationEngine(TotpProperties(time_window=30, code_length=6, algorithm="SHA1"))
ok = engine.verify_code(base32_secret, submitted_code, window=1)

# Per-user parameters must match the provisioning QR code:
ok = engine.verify_code(secret, code, window=1, algorithm="SHA256", period=30, digits=6)

guard = InMemoryReplayGuard()
step = int(time.time()) // 30
if ok and not guard.is_code_used(user_id, tenant_id, step):
    guard.mark_code_as_used(user_id, tenant_id, step)
```

## Algorithms

`SHA1`, `SHA256`, `SHA512`. A `Hmac` prefix is stripped and the name upper-cased,
so `HmacSHA256` works. An unrecognised value falls back to the configured default,
then to `SHA1` (RFC 6238) — it never raises.

## Security behaviour

- **Fail-closed**: any internal error (undecodable secret, bad parameters) makes
  `verify_code` return `False` rather than raising.
- **No credential logging**: only the exception *type* is logged, never the secret
  or the submitted code. Pinned by a test.
- **Constant-time comparison**: codes are compared with `hmac.compare_digest`.
  This is a deliberate improvement over the Java `String.equals()`, which is
  timing-sensitive.
- Base32 decoding is lenient (lower case, embedded whitespace, missing `=`
  padding) to match Apache Commons Codec, because manually-entered and scanned
  secrets arrive in all those shapes.

## Replay prevention

`ReplayGuard` is a Protocol. `InMemoryReplayGuard` is a thread-safe per-process
reference implementation with TTL = `time_window * replay_prevention_ttl_multiplier`,
matching the Java TTL rule so a code stays marked beyond its own validity window.

**It is not shared across processes.** Behind a load balancer, each instance keeps
its own markers and a code could be replayed against a different instance. For
multi-instance deployments inject a shared-store implementation (for example a
cache-redis backed adapter); this package deliberately does not depend on Redis.

## Scope

Ported: the TOTP engine, its properties, algorithm normalisation, lenient Base32
decoding, and the replay-prevention SPI with an in-memory implementation.

Not ported: `MfaValidationService` (580 lines of DB/KMS/Redis orchestration),
`MfaValidationResult`, and the Spring auto-configuration. The Java replay service's
Servlet request-context coupling is replaced by explicit `user_id` / `tenant_id`
arguments.

## Verification

Correctness is pinned against the **RFC 6238 Appendix B test vectors** for all
three algorithms at six timestamps with 8 digits, plus the Java module's own
`TotpValidationEngineTest` expectations.

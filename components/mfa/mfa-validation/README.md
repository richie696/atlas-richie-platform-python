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

## Validation service

`DefaultMfaValidationService` orchestrates the whole flow, ported from the Java
`MfaValidationServiceImpl`. Error codes and their evaluation order match Java:
`INVALID_PARAMS` / `INVALID_USER_ID` → `MFA_NOT_BOUND` → `MFA_NOT_ENABLED` →
`ACCOUNT_LOCKED` → `MFA_CODE_USED` → `MFA_CODE_INVALID` → `MFA_VERIFY_ERROR`.

```python
from atlas_richie.mfa_validation import (
    DefaultMfaValidationService, InMemoryMfaStateStore, MfaUserInfo, ENABLED,
)

store = InMemoryMfaStateStore()
store.put_user_info("u1", None, MfaUserInfo(status=ENABLED, secret_reference="mfa:u1"))

class Secrets:                      # wire to any of the platform's secret providers
    def retrieve(self, reference): return load_base32_secret(reference)

service = DefaultMfaValidationService(store, Secrets())
service.check_mfa_status("u1")               # is MFA required?
service.verify_mfa_code("u1", None, code)    # full verification
service.check_trusted_device("u1", None, "device-1")
```

Three SPIs keep the core dependency-free: `MfaStateStore` (user info, failure
counting, lock marker), `SecretRetriever` (KMS/Vault/DB — caller's choice) and
`TrustedDeviceStore`. An optional `audit` callback replaces Java's Spring audit
events; a failing sink is logged and never breaks validation. Thread-safe
in-memory reference implementations are provided for all three.

Per-user `algorithm` / `period` / `digits` from the user record take precedence over
configuration, so verification uses the same parameters the provisioning QR code
was generated with.

### Deliberate improvement over Java

Java writes the lockout to a standalone `mfa:lock:{tenant}:{user}` cache key but
only reads `userInfo.lockedUntil` when checking, so a freshly triggered lock does
not take effect until the management module reconciles it into the database. This
port checks **both** the user record and the lock marker, so lockout is immediate.

## Scope

Ported: the TOTP engine, its properties, algorithm normalisation, lenient Base32
decoding, the replay-prevention SPI with an in-memory implementation, and the
validation service with its result contract and state/secret/trusted-device SPIs.

Not ported: the Spring auto-configuration, MyBatis persistence, and the separate
`mfa-core` (key management, HSM/Vault engines) and `mfa-management` (bind/unbind,
backup codes, QR provisioning, key rotation, trusted-device administration)
modules. The Java replay service's Servlet request-context coupling is replaced by
explicit `user_id` / `tenant_id` arguments.

## Verification

Correctness is pinned against the **RFC 6238 Appendix B test vectors** for all
three algorithms at six timestamps with 8 digits, plus the Java module's own
`TotpValidationEngineTest` expectations.
